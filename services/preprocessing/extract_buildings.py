#!/usr/bin/env python3
"""
Extract building polygons from an OSM PBF file.

Handles both:
- Simple buildings (OSM ways with building=* tag)
- Complex buildings (OSM multipolygon relations with building=* tag)

Usage:
    python extract_buildings.py <input_pbf> <output_geojson>

Example:
    python extract_buildings.py ../backend/data/pbf/paris-latest.osm.pbf ./buildings.geojson
"""

import argparse
import json
import sys
from collections import defaultdict

import osmium


class DataCollector(osmium.SimpleHandler):
    """First pass: collect all nodes and ways needed for buildings."""

    def __init__(self):
        super().__init__()
        self.nodes = {}  # node_id -> (lon, lat)
        self.ways = {}   # way_id -> {'nodes': [...], 'tags': {...}}
        self.building_relations = []  # List of relations with building tags

    def node(self, n):
        """Store node coordinates."""
        self.nodes[n.id] = (n.location.lon, n.location.lat)

    def way(self, w):
        """Store way data (nodes and tags)."""
        node_refs = [n.ref for n in w.nodes]
        self.ways[w.id] = {
            'nodes': node_refs,
            'tags': dict(w.tags),
            'is_building': bool(w.tags.get('building'))
        }

    def relation(self, r):
        """Collect building relations (multipolygons)."""
        # Check if this is a building multipolygon
        if r.tags.get('type') == 'multipolygon' and r.tags.get('building'):
            members = []
            for m in r.members:
                if m.type == 'w':  # Only way members
                    members.append({
                        'ref': m.ref,
                        'role': m.role
                    })
            if members:
                self.building_relations.append({
                    'id': r.id,
                    'tags': dict(r.tags),
                    'members': members
                })


class BuildingExtractor:
    """Extract buildings from collected OSM data."""

    def __init__(self, nodes, ways, relations):
        self.nodes = nodes
        self.ways = ways
        self.relations = relations
        self.buildings = []
        self.building_count = 0
        self.relation_way_ids = set()  # Track ways used in relations

    def extract(self):
        """Extract all buildings (ways and relations)."""
        # First, identify which ways are part of building relations
        for rel in self.relations:
            for member in rel['members']:
                self.relation_way_ids.add(member['ref'])

        # Extract simple way buildings (not part of relations)
        print("  Extracting simple buildings (ways)...", file=sys.stderr)
        for way_id, way_data in self.ways.items():
            if way_data['is_building'] and way_id not in self.relation_way_ids:
                self._extract_way_building(way_id, way_data)

        way_count = self.building_count
        print(f"    Extracted {way_count} way buildings", file=sys.stderr)

        # Extract multipolygon relation buildings
        print("  Extracting complex buildings (relations)...", file=sys.stderr)
        for rel in self.relations:
            self._extract_relation_building(rel)

        rel_count = self.building_count - way_count
        print(f"    Extracted {rel_count} relation buildings", file=sys.stderr)

        return self.buildings

    def _get_way_coords(self, way_id):
        """Get coordinates for a way."""
        if way_id not in self.ways:
            return None

        way_data = self.ways[way_id]
        coords = []
        for node_ref in way_data['nodes']:
            if node_ref in self.nodes:
                coords.append(self.nodes[node_ref])
            else:
                return None  # Missing node
        return coords

    def _extract_way_building(self, way_id, way_data):
        """Extract a simple way building."""
        coords = self._get_way_coords(way_id)
        if coords is None or len(coords) < 4:
            return

        self._add_building(way_id, coords, way_data['tags'])

    def _extract_relation_building(self, rel):
        """Extract a multipolygon relation building."""
        outer_rings = []
        inner_rings = []

        for member in rel['members']:
            way_id = member['ref']
            role = member['role']
            coords = self._get_way_coords(way_id)

            if coords is None:
                continue

            if role == 'outer' or role == '':  # Empty role defaults to outer
                outer_rings.append(coords)
            elif role == 'inner':
                inner_rings.append(coords)

        if not outer_rings:
            return

        # For simplicity, use the first outer ring as the main polygon
        # A full implementation would merge connected outer ways
        main_coords = outer_rings[0]
        if len(main_coords) < 4:
            return

        # Ensure polygon is closed
        if main_coords[0] != main_coords[-1]:
            main_coords.append(main_coords[0])

        # Build polygon with holes (inner rings)
        rings = [main_coords]
        for inner in inner_rings:
            if len(inner) >= 4:
                if inner[0] != inner[-1]:
                    inner.append(inner[0])
                rings.append(inner)

        # Use negative relation ID to distinguish from way IDs
        building_id = -rel['id']

        feature = {
            "type": "Feature",
            "properties": {
                "building_id": building_id,
                "building_type": rel['tags'].get('building', 'yes'),
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": rings
            }
        }

        # Add optional properties
        if rel['tags'].get('name'):
            feature["properties"]["name"] = rel['tags'].get('name')
        if rel['tags'].get('addr:street'):
            feature["properties"]["street"] = rel['tags'].get('addr:street')
        if rel['tags'].get('addr:housenumber'):
            feature["properties"]["housenumber"] = rel['tags'].get('addr:housenumber')

        self.buildings.append(feature)
        self.building_count += 1

        if self.building_count % 10000 == 0:
            print(f"  Processed {self.building_count} buildings...", file=sys.stderr)

    def _add_building(self, building_id, coords, tags):
        """Add a building feature to the output."""
        # Ensure polygon is closed
        if coords[0] != coords[-1]:
            coords.append(coords[0])

        feature = {
            "type": "Feature",
            "properties": {
                "building_id": building_id,
                "building_type": tags.get('building', 'yes'),
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords]
            }
        }

        # Add optional properties
        if tags.get('name'):
            feature["properties"]["name"] = tags.get('name')
        if tags.get('addr:street'):
            feature["properties"]["street"] = tags.get('addr:street')
        if tags.get('addr:housenumber'):
            feature["properties"]["housenumber"] = tags.get('addr:housenumber')

        self.buildings.append(feature)
        self.building_count += 1

        if self.building_count % 10000 == 0:
            print(f"  Processed {self.building_count} buildings...", file=sys.stderr)


def extract_buildings(input_pbf, output_geojson):
    """Extract buildings from OSM PBF file to GeoJSON."""

    print(f"Extracting buildings from {input_pbf}...", file=sys.stderr)

    # Single pass: collect all data (nodes, ways, relations)
    print("  Collecting OSM data (nodes, ways, relations)...", file=sys.stderr)
    collector = DataCollector()
    collector.apply_file(input_pbf, locations=True)
    print(f"    Collected {len(collector.nodes)} nodes", file=sys.stderr)
    print(f"    Collected {len(collector.ways)} ways", file=sys.stderr)
    print(f"    Collected {len(collector.building_relations)} building relations", file=sys.stderr)

    # Extract buildings from collected data
    print("  Extracting building polygons...", file=sys.stderr)
    extractor = BuildingExtractor(
        collector.nodes,
        collector.ways,
        collector.building_relations
    )
    buildings = extractor.extract()

    print(f"  Total: {len(buildings)} buildings extracted", file=sys.stderr)

    # Create GeoJSON FeatureCollection
    geojson = {
        "type": "FeatureCollection",
        "features": buildings
    }

    # Write output
    print(f"Writing to {output_geojson}...", file=sys.stderr)
    with open(output_geojson, 'w') as f:
        json.dump(geojson, f)

    print(f"Done! Extracted {len(buildings)} buildings.", file=sys.stderr)
    return len(buildings)


def main():
    parser = argparse.ArgumentParser(
        description='Extract building polygons from OSM PBF file'
    )
    parser.add_argument('input_pbf', help='Input OSM PBF file')
    parser.add_argument('output_geojson', help='Output GeoJSON file')

    args = parser.parse_args()

    extract_buildings(args.input_pbf, args.output_geojson)


if __name__ == '__main__':
    main()

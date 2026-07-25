#!/usr/bin/env python3
"""
Extract road segments from an OSM PBF file.

This creates CSV files compatible with the link_buildings_to_segments.py script.

Usage:
    python extract_roads.py <input_pbf> <output_dir>

Example:
    python extract_roads.py ../backend/data/pbf/paris-latest.osm.pbf ./output/roads
"""

import argparse
import os
import sys

import osmium


# Highway types to include (matching what RoutingKit uses for cars)
HIGHWAY_TYPES = {
    'motorway', 'motorway_link',
    'trunk', 'trunk_link',
    'primary', 'primary_link',
    'secondary', 'secondary_link',
    'tertiary', 'tertiary_link',
    'residential', 'living_street',
    'service', 'unclassified',
    'road'
}


class NodeCollector(osmium.SimpleHandler):
    """First pass: collect all node coordinates."""

    def __init__(self):
        super().__init__()
        self.nodes = {}

    def node(self, n):
        self.nodes[n.id] = (n.location.lon, n.location.lat)


class RoadExtractor(osmium.SimpleHandler):
    """Second pass: extract road segments."""

    def __init__(self, nodes):
        super().__init__()
        self.nodes = nodes
        self.way_count = 0

        # Output data
        self.latitudes = []
        self.longitudes = []
        self.heads = []
        self.tails = []
        self.way_indices = []
        self.way_osmids = []

        # Node ID to index mapping
        self.node_to_idx = {}

    def _get_node_idx(self, node_id):
        """Get or create index for a node."""
        if node_id not in self.node_to_idx:
            if node_id not in self.nodes:
                return None
            idx = len(self.latitudes)
            self.node_to_idx[node_id] = idx
            lon, lat = self.nodes[node_id]
            self.latitudes.append(lat)
            self.longitudes.append(lon)
        return self.node_to_idx[node_id]

    def way(self, w):
        """Process ways with highway=* tags."""
        highway = w.tags.get('highway')
        if not highway or highway not in HIGHWAY_TYPES:
            return

        # Get node references
        node_refs = [n.ref for n in w.nodes]
        if len(node_refs) < 2:
            return

        # Create edges for each segment in the way
        way_idx = len(self.way_osmids)
        self.way_osmids.append(w.id)

        prev_idx = None
        for node_ref in node_refs:
            node_idx = self._get_node_idx(node_ref)
            if node_idx is None:
                prev_idx = None
                continue

            if prev_idx is not None:
                # Create edge from prev to current
                self.tails.append(prev_idx)
                self.heads.append(node_idx)
                self.way_indices.append(way_idx)

            prev_idx = node_idx

        self.way_count += 1
        if self.way_count % 5000 == 0:
            print(f"  Processed {self.way_count} ways...", file=sys.stderr)


def extract_roads(input_pbf, output_dir):
    """Extract roads from OSM PBF file to CSV files."""

    print(f"Extracting roads from {input_pbf}...", file=sys.stderr)

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    # First pass: collect all node coordinates
    print("  Pass 1: Collecting node coordinates...", file=sys.stderr)
    node_collector = NodeCollector()
    node_collector.apply_file(input_pbf, locations=True)
    print(f"  Collected {len(node_collector.nodes)} nodes", file=sys.stderr)

    # Second pass: extract roads
    print("  Pass 2: Extracting road segments...", file=sys.stderr)
    extractor = RoadExtractor(node_collector.nodes)
    extractor.apply_file(input_pbf, locations=True)

    print(f"  Extracted {extractor.way_count} ways", file=sys.stderr)
    print(f"  {len(extractor.latitudes)} unique nodes", file=sys.stderr)
    print(f"  {len(extractor.heads)} edges", file=sys.stderr)

    # Write output files
    print(f"Writing to {output_dir}...", file=sys.stderr)

    with open(os.path.join(output_dir, "latitude.csv"), 'w') as f:
        for lat in extractor.latitudes:
            f.write(f"{lat}\n")

    with open(os.path.join(output_dir, "longitude.csv"), 'w') as f:
        for lon in extractor.longitudes:
            f.write(f"{lon}\n")

    with open(os.path.join(output_dir, "head.csv"), 'w') as f:
        for h in extractor.heads:
            f.write(f"{h}\n")

    with open(os.path.join(output_dir, "tail.csv"), 'w') as f:
        for t in extractor.tails:
            f.write(f"{t}\n")

    with open(os.path.join(output_dir, "way.csv"), 'w') as f:
        for w in extractor.way_indices:
            f.write(f"{w}\n")

    with open(os.path.join(output_dir, "way_osmid.csv"), 'w') as f:
        for osm_id in extractor.way_osmids:
            f.write(f"{osm_id}\n")

    print(f"Done!", file=sys.stderr)
    return extractor.way_count


def main():
    parser = argparse.ArgumentParser(
        description='Extract road segments from OSM PBF file'
    )
    parser.add_argument('input_pbf', help='Input OSM PBF file')
    parser.add_argument('output_dir', help='Output directory for CSV files')

    args = parser.parse_args()

    extract_roads(args.input_pbf, args.output_dir)


if __name__ == '__main__':
    main()

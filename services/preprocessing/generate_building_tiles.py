#!/usr/bin/env python3
"""
Generate building GeoJSON with segment IDs for tippecanoe processing.

This script:
1. Loads buildings GeoJSON
2. Loads building-to-segment mapping
3. Adds segment_osm_id property to each building
4. Outputs GeoJSON suitable for tippecanoe

Usage:
    python generate_building_tiles.py <buildings_geojson> <mapping_json> <output_geojson>

Example:
    python generate_building_tiles.py \
        ./buildings.geojson \
        ./building_segment_mapping.json \
        ./buildings_with_segments.geojson

Then run tippecanoe:
    tippecanoe -e ../frontend/app/static/data/tiles/buildings -Z12 -z17 \
        --no-tile-compression --layer=buildings \
        buildings_with_segments.geojson
"""

import argparse
import json
import sys
from collections import defaultdict


def generate_building_tiles(buildings_geojson, mapping_json, output_geojson):
    """Generate building GeoJSON with segment IDs."""

    # Load buildings
    print(f"Loading buildings from {buildings_geojson}...", file=sys.stderr)
    with open(buildings_geojson) as f:
        buildings = json.load(f)

    print(f"  Loaded {len(buildings['features'])} buildings", file=sys.stderr)

    # Load mapping
    print(f"Loading mapping from {mapping_json}...", file=sys.stderr)
    with open(mapping_json) as f:
        segment_to_buildings = json.load(f)

    # Create reverse mapping: building_id -> list of segment_osm_ids
    building_to_segments = defaultdict(list)
    for segment_osm_id, building_ids in segment_to_buildings.items():
        for building_id in building_ids:
            building_to_segments[building_id].append(int(segment_osm_id))

    print(f"  Loaded mapping for {len(building_to_segments)} buildings", file=sys.stderr)

    # Add segment_osm_id to each building
    print("Adding segment IDs to buildings...", file=sys.stderr)
    linked_count = 0
    unlinked_count = 0

    output_features = []
    for feature in buildings['features']:
        building_id = feature['properties']['building_id']

        if building_id in building_to_segments:
            segs = building_to_segments[building_id]
            # Store first segment as primary (for tile rendering)
            feature['properties']['segment_osm_id'] = segs[0]
            feature['properties']['segment_count'] = len(segs)
            linked_count += 1
            output_features.append(feature)
        else:
            # Skip buildings without segment link to reduce tile size
            unlinked_count += 1

    print(f"  Linked buildings: {linked_count}", file=sys.stderr)
    print(f"  Unlinked buildings (excluded): {unlinked_count}", file=sys.stderr)

    # Create output GeoJSON
    output = {
        "type": "FeatureCollection",
        "features": output_features
    }

    # Write output
    print(f"Writing to {output_geojson}...", file=sys.stderr)
    with open(output_geojson, 'w') as f:
        json.dump(output, f)

    print(f"Done! Output {len(output_features)} buildings.", file=sys.stderr)

    # Print tippecanoe command
    print("\nTo generate tiles, run:", file=sys.stderr)
    print(f"  tippecanoe -e ../frontend/app/static/data/tiles/buildings -Z12 -z17 \\", file=sys.stderr)
    print(f"      --no-tile-compression --layer=buildings \\", file=sys.stderr)
    print(f"      {output_geojson}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description='Generate building GeoJSON with segment IDs for tippecanoe'
    )
    parser.add_argument('buildings_geojson', help='Input buildings GeoJSON file')
    parser.add_argument('mapping_json', help='Building-to-segment mapping JSON file')
    parser.add_argument('output_geojson', help='Output GeoJSON file')

    args = parser.parse_args()

    generate_building_tiles(
        args.buildings_geojson,
        args.mapping_json,
        args.output_geojson
    )


if __name__ == '__main__':
    main()

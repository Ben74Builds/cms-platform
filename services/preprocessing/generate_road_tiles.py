#!/usr/bin/env python3
"""
Generate road segment GeoJSON from graph CSVs for tippecanoe tile generation.

Reads the road graph CSVs (head, tail, way, way_osmid, latitude, longitude)
and produces a GeoJSON file with one LineString per OSM way ID.

Usage:
    python generate_road_tiles.py <roads_dir> <output_geojson>

Example:
    python generate_road_tiles.py ./output/roads ./output/roads.geojson

Then run tippecanoe:
    tippecanoe -e ../frontend/app/static/data/tiles/roads -Z12 -z17 \
        --no-tile-compression --layer=roads roads.geojson
"""

import argparse
import json
import sys
from collections import defaultdict


def read_ints(filepath):
    with open(filepath) as f:
        return [int(line.strip()) for line in f if line.strip()]


def read_floats(filepath):
    with open(filepath) as f:
        return [float(line.strip()) for line in f if line.strip()]


def chain_edges(edges):
    """Chain directed edges into ordered linestrings.

    edges: list of (tail_node, head_node) tuples
    Returns list of coordinate sequences (each is a linestring).
    """
    if not edges:
        return []

    # Build adjacency: node -> list of (next_node)
    from_node = defaultdict(list)
    to_node = defaultdict(set)
    for t, h in edges:
        from_node[t].append(h)
        to_node[h].add(t)

    # Find start nodes (in-degree 0 from this way's edges, or just pick one)
    all_nodes = set(from_node.keys()) | set(n for s in to_node.values() for n in s)
    start_nodes = [n for n in all_nodes if n not in to_node or not to_node[n]]
    if not start_nodes:
        # Cycle - pick any node
        start_nodes = [edges[0][0]]

    visited_edges = set()
    chains = []

    for start in start_nodes:
        chain = [start]
        current = start
        while current in from_node:
            nexts = [n for n in from_node[current] if (current, n) not in visited_edges]
            if not nexts:
                break
            nxt = nexts[0]
            visited_edges.add((current, nxt))
            chain.append(nxt)
            current = nxt
        if len(chain) >= 2:
            chains.append(chain)

    # Handle any remaining unvisited edges
    for t, h in edges:
        if (t, h) not in visited_edges:
            chains.append([t, h])

    return chains


def generate_road_geojson(roads_dir, output_path):
    from pathlib import Path
    roads_dir = Path(roads_dir)

    print("Loading road graph CSVs...", file=sys.stderr)
    way_osmid = read_ints(roads_dir / "way_osmid.csv")
    way = read_ints(roads_dir / "way.csv")
    head = read_ints(roads_dir / "head.csv")
    tail = read_ints(roads_dir / "tail.csv")
    lat = read_floats(roads_dir / "latitude.csv")
    lon = read_floats(roads_dir / "longitude.csv")

    print(f"  {len(way_osmid)} ways, {len(way)} edges, {len(lat)} nodes", file=sys.stderr)

    # Group edges by way osm_id
    print("Grouping edges by way...", file=sys.stderr)
    way_edges = defaultdict(list)  # osm_id -> list of (tail, head)
    for i in range(len(way)):
        osm_id = way_osmid[way[i]]
        way_edges[osm_id].append((tail[i], head[i]))

    # Generate features
    print(f"Generating {len(way_edges)} road features...", file=sys.stderr)
    features = []
    for osm_id, edges in way_edges.items():
        chains = chain_edges(edges)

        if not chains:
            continue

        # Convert node indices to coordinates
        coord_chains = []
        for chain in chains:
            coords = [[round(lon[n], 7), round(lat[n], 7)] for n in chain]
            coord_chains.append(coords)

        if len(coord_chains) == 1:
            geometry = {
                "type": "LineString",
                "coordinates": coord_chains[0]
            }
        else:
            geometry = {
                "type": "MultiLineString",
                "coordinates": coord_chains
            }

        features.append({
            "type": "Feature",
            "properties": {
                "osm_id": osm_id,
                "edge_count": len(edges),
            },
            "geometry": geometry
        })

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    print(f"Writing {len(features)} features to {output_path}...", file=sys.stderr)
    with open(output_path, 'w') as f:
        json.dump(geojson, f)

    print(f"Done! {len(features)} road segments.", file=sys.stderr)
    print(f"\nTo generate tiles, run:", file=sys.stderr)
    print(f"  tippecanoe -e ../frontend/app/static/data/tiles/roads -Z12 -z17 \\", file=sys.stderr)
    print(f"      --no-tile-compression --layer=roads \\", file=sys.stderr)
    print(f"      {output_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Generate road GeoJSON from graph CSVs')
    parser.add_argument('roads_dir', help='Directory containing road CSV files')
    parser.add_argument('output_geojson', help='Output GeoJSON file')
    args = parser.parse_args()
    generate_road_geojson(args.roads_dir, args.output_geojson)


if __name__ == '__main__':
    main()

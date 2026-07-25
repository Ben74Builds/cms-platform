#!/usr/bin/env python3
"""
Link building centroids to nearest road segments.

This script reads:
1. Buildings GeoJSON (from extract_buildings.py)
2. Road graph data (way_osmid.csv, latitude.csv, longitude.csv, head.csv, tail.csv)

And outputs a mapping of segment IDs to building IDs:
{segment_osm_id: [building_id1, building_id2, ...], ...}

Usage:
    python link_buildings_to_segments.py <buildings_geojson> <graph_data_dir> <output_json>

Example:
    python link_buildings_to_segments.py \
        ./buildings.geojson \
        ../backend/data/backup/paris \
        ./building_segment_mapping.json
"""

import argparse
import json
import os
import sys
from collections import defaultdict

import numpy as np
from rtree import index
from shapely.geometry import Point, LineString, shape
from shapely.ops import nearest_points


# Maximum distance in meters to link a building to a segment
MAX_DISTANCE_METERS = 25


def load_graph_data(graph_data_dir):
    """Load road graph data from CSV files.

    Supports two file naming conventions:
    1. Standard: latitude.csv, longitude.csv, etc. in subdirectory
    2. Backup prefix: backuplatitude.csv, backuplongitude.csv, etc. in parent directory
    """
    print(f"Loading graph data from {graph_data_dir}...", file=sys.stderr)

    # Try to find files - support both naming conventions
    def find_file(name):
        # Try standard path first (e.g., graph_data_dir/latitude.csv)
        standard_path = f"{graph_data_dir}/{name}.csv"
        if os.path.exists(standard_path):
            return standard_path

        # Try backup prefix in parent directory (e.g., ../data/backuplatitude.csv)
        parent_dir = os.path.dirname(graph_data_dir)
        backup_path = f"{parent_dir}/backup{name}.csv"
        if os.path.exists(backup_path):
            return backup_path

        # Try backup prefix in data directory
        data_dir = os.path.dirname(parent_dir) if 'backup' in graph_data_dir else graph_data_dir
        backup_path2 = f"{data_dir}/backup{name}.csv"
        if os.path.exists(backup_path2):
            return backup_path2

        raise FileNotFoundError(f"Could not find {name}.csv in {graph_data_dir} or backup{name}.csv")

    # Load node coordinates
    with open(find_file("latitude")) as f:
        latitudes = [float(line.strip()) for line in f]
    with open(find_file("longitude")) as f:
        longitudes = [float(line.strip()) for line in f]

    # Load way OSM IDs
    with open(find_file("way_osmid")) as f:
        way_osmids = [int(line.strip()) for line in f]

    # Load edge endpoints (head and tail are node indices)
    with open(find_file("head")) as f:
        heads = [int(line.strip()) for line in f]
    with open(find_file("tail")) as f:
        tails = [int(line.strip()) for line in f]

    # Load way index for each edge
    with open(find_file("way")) as f:
        way_indices = [int(line.strip()) for line in f]

    print(f"  Loaded {len(latitudes)} nodes", file=sys.stderr)
    print(f"  Loaded {len(way_osmids)} ways", file=sys.stderr)
    print(f"  Loaded {len(heads)} edges", file=sys.stderr)

    return {
        'latitudes': latitudes,
        'longitudes': longitudes,
        'way_osmids': way_osmids,
        'heads': heads,
        'tails': tails,
        'way_indices': way_indices
    }


def build_segment_index(graph_data):
    """Build spatial index for road segments."""
    print("Building spatial index for road segments...", file=sys.stderr)

    latitudes = graph_data['latitudes']
    longitudes = graph_data['longitudes']
    heads = graph_data['heads']
    tails = graph_data['tails']
    way_indices = graph_data['way_indices']
    way_osmids = graph_data['way_osmids']

    # Create R-tree index
    idx = index.Index()

    # Store segment data: segment_idx -> (way_osm_id, LineString)
    segments = {}

    # Track unique way OSM IDs we've seen
    seen_way_osmids = set()

    for i, (head_idx, tail_idx, way_idx) in enumerate(zip(heads, tails, way_indices)):
        way_osm_id = way_osmids[way_idx]

        # Get coordinates for the segment endpoints
        lon1, lat1 = longitudes[tail_idx], latitudes[tail_idx]
        lon2, lat2 = longitudes[head_idx], latitudes[head_idx]

        # Create LineString for the segment
        line = LineString([(lon1, lat1), (lon2, lat2)])

        # Store segment data
        segments[i] = {
            'way_osm_id': way_osm_id,
            'way_idx': way_idx,
            'geometry': line
        }

        # Add bounding box to spatial index
        idx.insert(i, line.bounds)

        if i % 10000 == 0:
            print(f"  Indexed {i} segments...", file=sys.stderr)

    print(f"  Indexed {len(segments)} segments", file=sys.stderr)
    return idx, segments


def haversine_distance(lon1, lat1, lon2, lat2):
    """Calculate the great circle distance between two points in meters."""
    R = 6371000  # Earth's radius in meters

    lat1_rad = np.radians(lat1)
    lat2_rad = np.radians(lat2)
    delta_lat = np.radians(lat2 - lat1)
    delta_lon = np.radians(lon2 - lon1)

    a = np.sin(delta_lat / 2) ** 2 + \
        np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(delta_lon / 2) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

    return R * c


def link_buildings_to_segments(buildings_geojson, graph_data_dir, output_json, max_distance=MAX_DISTANCE_METERS):
    """Link buildings to nearest road segments."""

    # Load buildings
    print(f"Loading buildings from {buildings_geojson}...", file=sys.stderr)
    with open(buildings_geojson) as f:
        buildings = json.load(f)

    print(f"  Loaded {len(buildings['features'])} buildings", file=sys.stderr)

    # Load graph data
    graph_data = load_graph_data(graph_data_dir)

    # Build spatial index
    seg_idx, segments = build_segment_index(graph_data)

    # Map: segment way_osm_id -> list of building_ids
    segment_to_buildings = defaultdict(list)

    # Map: way_idx -> way_osm_id (for the output format the backend expects)
    way_idx_to_osmid = {}
    for seg_data in segments.values():
        way_idx_to_osmid[seg_data['way_idx']] = seg_data['way_osm_id']

    # Process each building
    linked_count = 0
    skipped_count = 0

    # Convert max distance to approximate degrees (rough approximation)
    # At Paris latitude (~48.8), 1 degree longitude ~ 74 km, 1 degree latitude ~ 111 km
    max_dist_deg = max_distance / 74000  # Use smaller value for buffer

    # Threshold for "large" buildings that need vertex-based distance checking (in degrees)
    # Buildings with bbox diagonal > ~20m may have edges significantly closer to roads than centroid
    large_building_threshold = 20 / 74000  # ~20m in degrees

    # --- Pass 1: Fast centroid-based linking (handles majority of buildings) ---
    print("Pass 1: Centroid-based linking...", file=sys.stderr)
    large_buildings = []  # Store large buildings for pass 2

    for i, feature in enumerate(buildings['features']):
        building_id = feature['properties']['building_id']

        # Get building centroid
        try:
            geom = shape(feature['geometry'])
            centroid = geom.centroid
            building_lon, building_lat = centroid.x, centroid.y
        except Exception:
            skipped_count += 1
            continue

        # Check if this building is "large" enough to need vertex checking
        bmin_lon, bmin_lat, bmax_lon, bmax_lat = geom.bounds
        bbox_size = max(bmax_lon - bmin_lon, bmax_lat - bmin_lat)

        # Search for nearby segments using centroid
        search_bounds = (
            building_lon - max_dist_deg,
            building_lat - max_dist_deg,
            building_lon + max_dist_deg,
            building_lat + max_dist_deg
        )

        # Find ALL segments within max_distance (not just the nearest)
        linked_way_osmids = set()

        for seg_idx_candidate in seg_idx.intersection(search_bounds):
            seg_data = segments[seg_idx_candidate]
            line = seg_data['geometry']

            # Calculate distance from centroid to segment using nearest point on line
            nearest_point = line.interpolate(line.project(Point(building_lon, building_lat)))
            dist = haversine_distance(building_lon, building_lat, nearest_point.x, nearest_point.y)

            if dist <= max_distance:
                linked_way_osmids.add(seg_data['way_osm_id'])

        if linked_way_osmids:
            for way_osm_id in linked_way_osmids:
                segment_to_buildings[way_osm_id].append(building_id)
            linked_count += 1

        # If building is large, queue for pass 2 to find additional links via vertices
        if bbox_size > large_building_threshold:
            large_buildings.append((building_id, geom, linked_way_osmids))
        elif not linked_way_osmids:
            skipped_count += 1

        if (i + 1) % 10000 == 0:
            print(f"  Processed {i + 1}/{len(buildings['features'])} buildings...", file=sys.stderr)

    print(f"  Pass 1: Linked {linked_count} buildings", file=sys.stderr)
    print(f"  {len(large_buildings)} large buildings queued for pass 2", file=sys.stderr)

    # --- Pass 2: Vertex-based linking for large buildings only ---
    print("Pass 2: Vertex-based linking for large buildings...", file=sys.stderr)
    extra_links = 0

    for j, (building_id, geom, already_linked) in enumerate(large_buildings):
        # Get vertex coordinates
        try:
            exterior_coords = list(geom.exterior.coords)
        except AttributeError:
            continue

        # Search from each vertex to find segments near building edges
        new_way_osmids = set()
        for vx, vy in exterior_coords:
            vertex_search = (
                vx - max_dist_deg,
                vy - max_dist_deg,
                vx + max_dist_deg,
                vy + max_dist_deg
            )
            for seg_idx_candidate in seg_idx.intersection(vertex_search):
                seg_data = segments[seg_idx_candidate]
                way_osm_id = seg_data['way_osm_id']
                if way_osm_id in already_linked or way_osm_id in new_way_osmids:
                    continue
                line = seg_data['geometry']
                nearest_pt = line.interpolate(line.project(Point(vx, vy)))
                dist = haversine_distance(vx, vy, nearest_pt.x, nearest_pt.y)
                if dist <= max_distance:
                    new_way_osmids.add(way_osm_id)

        if new_way_osmids:
            for way_osm_id in new_way_osmids:
                segment_to_buildings[way_osm_id].append(building_id)
            if not already_linked:
                linked_count += 1
            extra_links += len(new_way_osmids)
        elif not already_linked:
            skipped_count += 1

        if (j + 1) % 1000 == 0:
            print(f"  Pass 2: Processed {j + 1}/{len(large_buildings)} large buildings...", file=sys.stderr)

    print(f"  Pass 2: Found {extra_links} additional segment links", file=sys.stderr)
    print(f"  Total: Linked {linked_count} buildings to {len(segment_to_buildings)} segments", file=sys.stderr)
    print(f"  Skipped {skipped_count} buildings (no nearby segment)", file=sys.stderr)

    # Convert to regular dict for JSON serialization
    output = {str(k): v for k, v in segment_to_buildings.items()}

    # Write output
    print(f"Writing to {output_json}...", file=sys.stderr)
    with open(output_json, 'w') as f:
        json.dump(output, f)

    print(f"Done!", file=sys.stderr)
    return len(segment_to_buildings), linked_count


def main():
    parser = argparse.ArgumentParser(
        description='Link building centroids to nearest road segments'
    )
    parser.add_argument('buildings_geojson', help='Input buildings GeoJSON file')
    parser.add_argument('graph_data_dir', help='Directory containing graph CSV files')
    parser.add_argument('output_json', help='Output JSON mapping file')
    parser.add_argument(
        '--max-distance',
        type=float,
        default=MAX_DISTANCE_METERS,
        help=f'Maximum distance in meters to link building to segment (default: {MAX_DISTANCE_METERS})'
    )

    args = parser.parse_args()

    link_buildings_to_segments(
        args.buildings_geojson,
        args.graph_data_dir,
        args.output_json,
        args.max_distance
    )


if __name__ == '__main__':
    main()

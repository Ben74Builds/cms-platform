#!/usr/bin/env python3
"""
Generate synthetic GPS vehicle data for Andorra.

Creates 3 vehicles that drive along actual Andorra road segments,
with realistic status changes (available/unavailable), interventions,
and GPS position updates. Data is inserted into the PostgreSQL data_id table.

Usage:
    python generate_andorra_data.py [--days N] [--speed-factor N]

    --days N           Number of days of data to generate (default: 7)
    --speed-factor N   GPS update frequency multiplier (default: 1)
"""

import argparse
import json
import random
import sys
from datetime import datetime, timedelta

import psycopg2

# Andorra road network coordinates (sampled from roads.geojson)
# We'll load actual road segments for realistic paths


def load_road_coords(geojson_path):
    """Load road coordinates from GeoJSON for realistic vehicle paths."""
    with open(geojson_path) as f:
        data = json.load(f)

    roads = []
    for feat in data['features']:
        geom = feat['geometry']
        if geom['type'] == 'LineString':
            coords = [(c[1], c[0]) for c in geom['coordinates']]  # lat, lon
            if len(coords) >= 2:
                roads.append(coords)
        elif geom['type'] == 'MultiLineString':
            for line in geom['coordinates']:
                coords = [(c[1], c[0]) for c in line]
                if len(coords) >= 2:
                    roads.append(coords)
    return roads


def interpolate_points(p1, p2, n_steps):
    """Interpolate n_steps points between p1 and p2."""
    points = []
    for i in range(1, n_steps + 1):
        t = i / n_steps
        lat = p1[0] + t * (p2[0] - p1[0])
        lon = p1[1] + t * (p2[1] - p1[1])
        points.append((round(lat, 7), round(lon, 7)))
    return points


def generate_vehicle_path(roads, duration_minutes=30):
    """Generate a realistic vehicle path by following connected road segments."""
    path = []
    # Pick a random starting road
    road = random.choice(roads)
    direction = random.choice([1, -1])
    if direction == -1:
        road = list(reversed(road))

    # Walk along this road, then jump to nearby roads
    segments_to_follow = random.randint(3, 8)
    for _ in range(segments_to_follow):
        for i in range(len(road) - 1):
            # Interpolate between waypoints for smooth GPS updates
            steps = random.randint(2, 5)
            path.extend(interpolate_points(road[i], road[i + 1], steps))

        # Find a nearby road to continue on
        last_point = road[-1]
        best_road = None
        best_dist = float('inf')
        for candidate in random.sample(roads, min(50, len(roads))):
            # Check start and end of candidate
            for endpoint in [candidate[0], candidate[-1]]:
                dist = abs(endpoint[0] - last_point[0]) + abs(endpoint[1] - last_point[1])
                if 0.0001 < dist < best_dist:  # Not same point, but close
                    best_dist = dist
                    best_road = candidate
                    if endpoint == candidate[-1]:
                        best_road = list(reversed(candidate))

        if best_road and best_dist < 0.005:  # ~500m threshold
            road = best_road
        else:
            road = random.choice(roads)
            if random.random() < 0.5:
                road = list(reversed(road))

    return path


# Andorra vehicle definitions
VEHICLES = [
    {
        'unit': 101,
        'unit_type': 2,  # Ambulance
        'unit_lso': 1,   # Station 1 - Andorra la Vella
        'base_lat': 42.5063,
        'base_lon': 1.5218,
    },
    {
        'unit': 102,
        'unit_type': 2,  # Ambulance
        'unit_lso': 2,   # Station 2 - Escaldes-Engordany
        'base_lat': 42.5104,
        'base_lon': 1.5382,
    },
    {
        'unit': 103,
        'unit_type': 3,  # Specialized vehicle
        'unit_lso': 1,   # Station 1 - Andorra la Vella
        'base_lat': 42.5063,
        'base_lon': 1.5218,
    },
]


def generate_data(roads, n_days=7):
    """Generate synthetic GPS records for Andorra vehicles."""
    records = []
    start_date = datetime(2025, 1, 1, 0, 0, 0)
    end_date = start_date + timedelta(days=n_days)
    intervention_counter = 7000000

    for vehicle in VEHICLES:
        current_time = start_date + timedelta(minutes=random.randint(0, 30))
        intervention_id = None
        available = 1
        status = 1
        current_lat = vehicle['base_lat']
        current_lon = vehicle['base_lon']

        while current_time < end_date:
            hour = current_time.hour

            # Activity pattern: less active at night
            if 0 <= hour < 6:
                event_prob = 0.05
                update_interval = random.randint(300, 900)  # 5-15 min
            elif 6 <= hour < 22:
                event_prob = 0.3
                update_interval = random.randint(15, 60)  # 15s-1min
            else:
                event_prob = 0.15
                update_interval = random.randint(60, 300)  # 1-5 min

            if available == 1 and random.random() < event_prob:
                # Start an intervention
                intervention_counter += 1
                intervention_id = intervention_counter
                available = 0
                status = random.choice([30, 41, 102])
                intervention_type = random.choice([1, 3, 5])

                # Generate a path for this intervention
                path = generate_vehicle_path(roads, duration_minutes=random.randint(10, 45))
                dest_lat, dest_lon = path[-1] if path else (current_lat, current_lon)

                # Dispatch record
                records.append({
                    'datetime': current_time,
                    'unit': vehicle['unit'],
                    'unit_type': vehicle['unit_type'],
                    'intervention_type': intervention_type,
                    'id_unit_selection': intervention_counter,
                    'intervention': intervention_id,
                    'unit_lso': vehicle['unit_lso'],
                    'status': status,
                    'availability': 0,
                    'latitude1': round(current_lat, 7),
                    'longitude1': round(current_lon, 7),
                    'latitude2': round(dest_lat, 7),
                    'longitude2': round(dest_lon, 7),
                })

                # Generate GPS updates along the path
                for j, (lat, lon) in enumerate(path):
                    current_time += timedelta(seconds=random.randint(3, 8))
                    current_lat, current_lon = lat, lon

                    # Occasional status changes during intervention
                    if j == len(path) // 2:
                        status = random.choice([4, 30, 41])

                    records.append({
                        'datetime': current_time,
                        'unit': vehicle['unit'],
                        'unit_type': vehicle['unit_type'],
                        'intervention_type': intervention_type,
                        'id_unit_selection': intervention_counter,
                        'intervention': intervention_id,
                        'unit_lso': vehicle['unit_lso'],
                        'status': status,
                        'availability': 0,
                        'latitude1': lat,
                        'longitude1': lon,
                        'latitude2': round(dest_lat, 7),
                        'longitude2': round(dest_lon, 7),
                    })

                # End intervention — return to available
                current_time += timedelta(seconds=random.randint(30, 120))
                available = 1
                status = 1
                intervention_type_end = intervention_type
                records.append({
                    'datetime': current_time,
                    'unit': vehicle['unit'],
                    'unit_type': vehicle['unit_type'],
                    'intervention_type': intervention_type_end,
                    'id_unit_selection': intervention_counter,
                    'intervention': intervention_id,
                    'unit_lso': vehicle['unit_lso'],
                    'status': 1,
                    'availability': 1,
                    'latitude1': current_lat,
                    'longitude1': current_lon,
                    'latitude2': None,
                    'longitude2': None,
                })
                intervention_id = None

            else:
                # Idle / small position drift when available
                if available == 1:
                    # Small random drift around current position (parked/idling)
                    drift_lat = random.uniform(-0.0002, 0.0002)
                    drift_lon = random.uniform(-0.0002, 0.0002)
                    current_lat = round(current_lat + drift_lat, 7)
                    current_lon = round(current_lon + drift_lon, 7)

                records.append({
                    'datetime': current_time,
                    'unit': vehicle['unit'],
                    'unit_type': vehicle['unit_type'],
                    'intervention_type': None,
                    'id_unit_selection': None,
                    'intervention': None,
                    'unit_lso': vehicle['unit_lso'],
                    'status': status,
                    'availability': available,
                    'latitude1': current_lat,
                    'longitude1': current_lon,
                    'latitude2': None,
                    'longitude2': None,
                })

            current_time += timedelta(seconds=update_interval)

    # Sort all records by datetime
    records.sort(key=lambda r: r['datetime'])
    return records


def insert_records(records, db_host, db_name, db_user, db_password):
    """Insert records into the data_id table."""
    conn = psycopg2.connect(
        host=db_host,
        database=db_name,
        user=db_user,
        password=db_password
    )
    cur = conn.cursor()

    # Delete any existing Andorra data (units 101-103)
    cur.execute("DELETE FROM data_id WHERE unit IN (101, 102, 103)")
    deleted = cur.rowcount
    if deleted > 0:
        print(f"Deleted {deleted} existing Andorra records", file=sys.stderr)

    inserted = 0
    for rec in records:
        cur.execute("""
            INSERT INTO data_id (
                datetime, unit, "unit type", "intervention type",
                "id unit selection", intervention, "unit lso",
                status, availability,
                latitude1, longitude1, latitude2, longitude2
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """, (
            rec['datetime'], rec['unit'], rec['unit_type'],
            rec['intervention_type'], rec['id_unit_selection'],
            rec['intervention'], rec['unit_lso'],
            rec['status'], rec['availability'],
            rec['latitude1'], rec['longitude1'],
            rec['latitude2'], rec['longitude2'],
        ))
        inserted += 1
        if inserted % 10000 == 0:
            print(f"  Inserted {inserted} records...", file=sys.stderr)

    conn.commit()
    cur.close()
    conn.close()
    return inserted


def main():
    parser = argparse.ArgumentParser(description='Generate synthetic Andorra GPS data')
    parser.add_argument('--days', type=int, default=7, help='Days of data to generate')
    parser.add_argument('--db-host', default='localhost', help='PostgreSQL host')
    parser.add_argument('--db-name', default='ems', help='Database name')
    parser.add_argument('--db-user', default='postgres', help='Database user')
    parser.add_argument('--db-password', default='postgres', help='Database password')
    parser.add_argument('--roads-geojson',
                        default='/home/benjamin/workspace/cms/services/preprocessing/output/andorra/roads.geojson',
                        help='Path to Andorra roads GeoJSON')
    args = parser.parse_args()

    print(f"Loading roads from {args.roads_geojson}...", file=sys.stderr)
    roads = load_road_coords(args.roads_geojson)
    print(f"  Loaded {len(roads)} road segments", file=sys.stderr)

    print(f"Generating {args.days} days of data for 3 vehicles...", file=sys.stderr)
    records = generate_data(roads, n_days=args.days)
    print(f"  Generated {len(records)} records", file=sys.stderr)

    print(f"Inserting into {args.db_host}/{args.db_name}...", file=sys.stderr)
    inserted = insert_records(records, args.db_host, args.db_name, args.db_user, args.db_password)
    print(f"Done! Inserted {inserted} records for units 101, 102, 103", file=sys.stderr)

    # Print summary
    from collections import Counter
    units = Counter(r['unit'] for r in records)
    for unit_id, count in sorted(units.items()):
        interventions = len(set(r['intervention'] for r in records if r['unit'] == unit_id and r['intervention']))
        print(f"  Unit {unit_id}: {count} records, {interventions} interventions", file=sys.stderr)


if __name__ == '__main__':
    main()

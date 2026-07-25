#!/usr/bin/env python3
"""
Simulation data generator with graph-based vehicle routing.

Generates realistic GPS records for emergency vehicles that follow actual roads
using Dijkstra shortest-path routing on the city's road graph.

Can be used standalone or called from the FastAPI backend.

Usage (standalone):
    python simulation_generator.py --city andorra --stations auto:3 --days 3
"""

import argparse
import heapq
import json
import math
import random
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import psycopg2

# =============================================================================
# paris Reference Patterns (extracted from real Paris data)
# =============================================================================

# Hourly incident frequency normalized to peak=1.0
paris_HOURLY_CURVE = [
    0.58, 0.46, 0.39, 0.33, 0.31, 0.27,  # 0-5h (night)
    0.32, 0.41, 0.54, 0.80, 0.91, 0.98,  # 6-11h (morning)
    1.00, 0.96, 0.97, 0.99, 0.96, 0.99,  # 12-17h (afternoon)
    0.97, 0.98, 0.93, 0.84, 0.77, 0.69,  # 18-23h (evening)
]

# Fleet composition ratios
paris_FLEET_RATIO = {2: 0.58, 3: 0.36, 5: 0.06}

# Incident type probabilities
paris_INCIDENT_TYPES = {3: 0.84, 2: 0.054, 1: 0.046, 9: 0.029, 6: 0.017, 4: 0.005, 5: 0.004}

# Average intervention duration in minutes by type
paris_DURATION_MINUTES = {3: 64, 2: 74, 1: 77, 9: 51, 6: 74, 4: 39, 5: 20}

# Average units per station in paris
paris_UNITS_PER_STATION = 5.4


# =============================================================================
# Road Graph
# =============================================================================

def haversine_meters(lat1, lon1, lat2, lon2):
    """Great circle distance in meters."""
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class RoadGraph:
    """Directed road graph with Dijkstra routing."""

    def __init__(self, roads_dir: str):
        roads_dir = Path(roads_dir)
        print(f"[RoadGraph] Loading from {roads_dir}...", file=sys.stderr)

        self.lat = self._load_floats(roads_dir / "latitude.csv")
        self.lon = self._load_floats(roads_dir / "longitude.csv")
        heads = self._load_ints(roads_dir / "head.csv")
        tails = self._load_ints(roads_dir / "tail.csv")

        self.n_nodes = len(self.lat)
        self.n_edges = len(heads)

        # Build adjacency list: node -> [(neighbor, weight_meters, edge_idx)]
        self.adj = defaultdict(list)
        for i in range(self.n_edges):
            t, h = tails[i], heads[i]
            dist = haversine_meters(self.lat[t], self.lon[t], self.lat[h], self.lon[h])
            self.adj[t].append((h, dist, i))

        # Build numpy arrays for fast nearest-node lookup
        self._lat_arr = np.array(self.lat)
        self._lon_arr = np.array(self.lon)

        # Filter to nodes that have edges (connected nodes only)
        connected = set()
        for i in range(self.n_edges):
            connected.add(tails[i])
            connected.add(heads[i])
        self._connected_nodes = list(connected)

        print(f"[RoadGraph] {self.n_nodes} nodes, {self.n_edges} edges, "
              f"{len(self._connected_nodes)} connected", file=sys.stderr)

    @staticmethod
    def _load_floats(path):
        with open(path) as f:
            return [float(line.strip()) for line in f]

    @staticmethod
    def _load_ints(path):
        with open(path) as f:
            return [int(line.strip()) for line in f]

    def nearest_node(self, lat: float, lon: float) -> int:
        """Find nearest graph node to a coordinate."""
        dlat = self._lat_arr - lat
        dlon = self._lon_arr - lon
        dist_sq = dlat * dlat + dlon * dlon
        return int(np.argmin(dist_sq))

    def random_connected_node(self) -> int:
        """Pick a random connected node."""
        return random.choice(self._connected_nodes)

    def shortest_path(self, src: int, dst: int, max_nodes: int = 50000) -> Optional[list]:
        """Dijkstra shortest path. Returns list of node IDs or None if unreachable."""
        if src == dst:
            return [src]

        dist = {src: 0.0}
        prev = {src: None}
        heap = [(0.0, src)]
        visited = 0

        while heap:
            d, u = heapq.heappop(heap)
            if u == dst:
                # Reconstruct path
                path = []
                node = dst
                while node is not None:
                    path.append(node)
                    node = prev[node]
                return list(reversed(path))

            if d > dist.get(u, float('inf')):
                continue

            visited += 1
            if visited > max_nodes:
                return None  # Give up on very long searches

            for v, w, _ in self.adj[u]:
                new_dist = d + w
                if new_dist < dist.get(v, float('inf')):
                    dist[v] = new_dist
                    prev[v] = u
                    heapq.heappush(heap, (new_dist, v))

        return None  # Unreachable

    def path_to_gps_points(self, node_path: list, speed_kmh: float = 40.0) -> list:
        """
        Convert a node path to GPS points with time offsets.
        Returns [(lat, lon, elapsed_seconds), ...]
        """
        if not node_path:
            return []

        speed_mps = speed_kmh * 1000 / 3600
        points = []
        elapsed = 0.0
        gps_interval = 5.0  # seconds between GPS updates

        points.append((self.lat[node_path[0]], self.lon[node_path[0]], 0.0))
        time_since_last = 0.0

        for i in range(len(node_path) - 1):
            n1, n2 = node_path[i], node_path[i + 1]
            lat1, lon1 = self.lat[n1], self.lon[n1]
            lat2, lon2 = self.lat[n2], self.lon[n2]
            edge_dist = haversine_meters(lat1, lon1, lat2, lon2)

            if edge_dist < 0.1:  # Skip zero-length edges
                continue

            edge_time = edge_dist / speed_mps
            # How many GPS points fit in this edge?
            remaining_to_next = gps_interval - time_since_last

            t = remaining_to_next
            while t <= edge_time:
                frac = t / edge_time
                lat = lat1 + frac * (lat2 - lat1)
                lon = lon1 + frac * (lon2 - lon1)
                elapsed += gps_interval
                points.append((round(lat, 7), round(lon, 7), elapsed))
                time_since_last = 0.0
                t += gps_interval

            time_since_last += edge_time - (t - gps_interval)
            elapsed_at_edge_end = elapsed + time_since_last

        # Always add final point
        last_node = node_path[-1]
        if len(points) < 2 or points[-1][:2] != (self.lat[last_node], self.lon[last_node]):
            elapsed += time_since_last
            points.append((round(self.lat[last_node], 7),
                           round(self.lon[last_node], 7), elapsed))

        return points

    def propose_stations(self, n_stations: int) -> list:
        """
        Propose station locations using k-means on connected node positions.
        Returns [{name, lat, lon}, ...]
        """
        from sklearn.cluster import KMeans

        # Sample nodes for k-means (use all connected nodes for small graphs,
        # subsample for large ones)
        nodes = self._connected_nodes
        if len(nodes) > 50000:
            nodes = random.sample(nodes, 50000)

        coords = np.array([(self.lat[n], self.lon[n]) for n in nodes])
        kmeans = KMeans(n_clusters=n_stations, n_init=10, random_state=42)
        kmeans.fit(coords)

        stations = []
        for i, center in enumerate(kmeans.cluster_centers_):
            # Snap to nearest actual node
            node = self.nearest_node(center[0], center[1])
            stations.append({
                'name': f'Station {i + 1}',
                'lat': round(self.lat[node], 7),
                'lon': round(self.lon[node], 7),
                'node_id': node,
            })

        return stations

    def random_node_within_range(self, origin: int, min_km: float = 1.0,
                                  max_km: float = 10.0, attempts: int = 50) -> int:
        """Pick a random connected node within a distance range from origin."""
        origin_lat = self.lat[origin]
        origin_lon = self.lon[origin]

        for _ in range(attempts):
            node = self.random_connected_node()
            dist = haversine_meters(origin_lat, origin_lon,
                                    self.lat[node], self.lon[node])
            if min_km * 1000 <= dist <= max_km * 1000:
                return node

        # Fallback: just pick any connected node
        return self.random_connected_node()


# =============================================================================
# Simulation Configuration
# =============================================================================

@dataclass
class SimulationConfig:
    city: str
    stations: list  # [{name, lat, lon, fleet: {2: N, 3: N}}]
    duration_days: int = 7
    hourly_curve: list = field(default_factory=lambda: list(paris_HOURLY_CURVE))
    hourly_scale: float = 1.0  # Multiply hourly curve by this
    incident_types: dict = field(default_factory=lambda: dict(paris_INCIDENT_TYPES))
    duration_by_type: dict = field(default_factory=lambda: dict(paris_DURATION_MINUTES))
    speed_kmh: float = 40.0
    unit_id_offset: int = 100
    start_date: str = '2025-01-01 00:00:00'


# =============================================================================
# Data Generator
# =============================================================================

class SimulationGenerator:
    """Generates realistic GPS simulation data using road graph routing."""

    def __init__(self, graph: RoadGraph, config: SimulationConfig,
                 progress_callback=None):
        self.graph = graph
        self.config = config
        self.progress_callback = progress_callback
        self.records = []

    def _report(self, progress: int, message: str):
        if self.progress_callback:
            self.progress_callback(progress, message)
        print(f"[Generator] {progress}% - {message}", file=sys.stderr)

    def generate(self) -> list:
        """Generate all simulation records. Returns list of record dicts."""
        self._report(0, "Preparing vehicles...")

        # Build vehicle list
        vehicles = []
        unit_id = self.config.unit_id_offset + 1
        station_nodes = []

        for station in self.config.stations:
            node = self.graph.nearest_node(station['lat'], station['lon'])
            station_nodes.append(node)
            fleet = station.get('fleet', {2: 3, 3: 2})

            for unit_type, count in fleet.items():
                for _ in range(int(count)):
                    vehicles.append({
                        'unit': unit_id,
                        'unit_type': int(unit_type),
                        'unit_lso': len(station_nodes),  # station index
                        'station_node': node,
                        'station_lat': station['lat'],
                        'station_lon': station['lon'],
                    })
                    unit_id += 1

        if not vehicles:
            self._report(100, "No vehicles configured")
            return []

        self._report(5, f"Created {len(vehicles)} vehicles across "
                        f"{len(self.config.stations)} stations")

        # Generate day by day
        start = datetime.strptime(self.config.start_date, '%Y-%m-%d %H:%M:%S')
        all_records = []
        intervention_counter = 8000000
        total_hours = self.config.duration_days * 24

        # Track vehicle availability
        vehicle_free_at = {v['unit']: start for v in vehicles}

        for day in range(self.config.duration_days):
            day_start = start + timedelta(days=day)
            day_progress_base = 10 + int(80 * day / self.config.duration_days)
            self._report(day_progress_base,
                         f"Generating day {day + 1}/{self.config.duration_days}...")

            for hour in range(24):
                hour_start = day_start + timedelta(hours=hour)

                # How many incidents this hour?
                curve_val = self.config.hourly_curve[hour]
                # Scale: for paris with 700 vehicles, peak ~1200 incidents/hour/week
                # Scale down proportionally to fleet size
                base_incidents_per_hour = 1200 / 7  # ~170/hour at peak for 700 vehicles
                fleet_ratio = len(vehicles) / 700
                expected = curve_val * base_incidents_per_hour * fleet_ratio * self.config.hourly_scale
                n_incidents = max(0, int(np.random.poisson(expected)))

                for _ in range(n_incidents):
                    # Pick a random available vehicle
                    available = [v for v in vehicles
                                 if vehicle_free_at[v['unit']] <= hour_start + timedelta(minutes=random.randint(0, 59))]
                    if not available:
                        continue

                    vehicle = random.choice(available)
                    incident_time = hour_start + timedelta(
                        minutes=random.randint(0, 59),
                        seconds=random.randint(0, 59))

                    if incident_time < vehicle_free_at[vehicle['unit']]:
                        continue

                    intervention_counter += 1
                    incident_type = self._pick_incident_type()
                    duration_min = self._pick_duration(incident_type)

                    # Pick incident location
                    dest_node = self.graph.random_node_within_range(
                        vehicle['station_node'], min_km=0.5, max_km=8.0)

                    # Route to incident
                    path_out = self.graph.shortest_path(
                        vehicle['station_node'], dest_node)

                    if path_out is None or len(path_out) < 2:
                        continue

                    gps_out = self.graph.path_to_gps_points(
                        path_out, self.config.speed_kmh)

                    # Route back
                    path_back = self.graph.shortest_path(
                        dest_node, vehicle['station_node'])
                    gps_back = []
                    if path_back and len(path_back) >= 2:
                        gps_back = self.graph.path_to_gps_points(
                            path_back, self.config.speed_kmh)

                    # Generate records for outbound trip
                    dest_lat = self.graph.lat[dest_node]
                    dest_lon = self.graph.lon[dest_node]
                    current_time = incident_time

                    # Dispatch record
                    all_records.append(self._make_record(
                        current_time, vehicle, intervention_counter,
                        incident_type, status=102, availability=0,
                        lat1=gps_out[0][0], lon1=gps_out[0][1],
                        lat2=round(dest_lat, 7), lon2=round(dest_lon, 7)))

                    # GPS updates along outbound path
                    for lat, lon, elapsed in gps_out[1:]:
                        t = incident_time + timedelta(seconds=elapsed)
                        all_records.append(self._make_record(
                            t, vehicle, intervention_counter,
                            incident_type, status=41, availability=0,
                            lat1=lat, lon1=lon,
                            lat2=round(dest_lat, 7), lon2=round(dest_lon, 7)))
                        current_time = t

                    # On-scene records (stationary at incident location)
                    scene_end = current_time + timedelta(minutes=duration_min)
                    t = current_time + timedelta(seconds=30)
                    while t < scene_end:
                        all_records.append(self._make_record(
                            t, vehicle, intervention_counter,
                            incident_type, status=4, availability=0,
                            lat1=round(dest_lat, 7), lon1=round(dest_lon, 7),
                            lat2=None, lon2=None))
                        t += timedelta(seconds=random.randint(30, 120))
                    current_time = scene_end

                    # Return trip
                    for lat, lon, elapsed in gps_back:
                        t = current_time + timedelta(seconds=elapsed)
                        all_records.append(self._make_record(
                            t, vehicle, intervention_counter,
                            incident_type, status=30, availability=0,
                            lat1=lat, lon1=lon,
                            lat2=round(vehicle['station_lat'], 7),
                            lon2=round(vehicle['station_lon'], 7)))
                        current_time = t

                    # Back at station — available again
                    current_time += timedelta(seconds=random.randint(30, 120))
                    all_records.append(self._make_record(
                        current_time, vehicle, intervention_counter,
                        incident_type, status=1, availability=1,
                        lat1=round(vehicle['station_lat'], 7),
                        lon1=round(vehicle['station_lon'], 7),
                        lat2=None, lon2=None))

                    vehicle_free_at[vehicle['unit']] = current_time

            # Generate idle updates for vehicles at their stations
            for vehicle in vehicles:
                day_end = day_start + timedelta(days=1)
                t = max(day_start, vehicle_free_at[vehicle['unit']])
                while t < day_end:
                    if t >= vehicle_free_at[vehicle['unit']]:
                        # Small GPS drift while parked
                        drift_lat = random.uniform(-0.00005, 0.00005)
                        drift_lon = random.uniform(-0.00005, 0.00005)
                        all_records.append(self._make_record(
                            t, vehicle, intervention=None,
                            intervention_type=None, status=1, availability=1,
                            lat1=round(vehicle['station_lat'] + drift_lat, 7),
                            lon1=round(vehicle['station_lon'] + drift_lon, 7),
                            lat2=None, lon2=None))
                    t += timedelta(seconds=random.randint(120, 600))

        # Sort by datetime
        self._report(90, f"Sorting {len(all_records)} records...")
        all_records.sort(key=lambda r: r['datetime'])

        self._report(95, f"Generated {len(all_records)} records")
        self.records = all_records
        return all_records

    def _pick_incident_type(self) -> int:
        types = list(self.config.incident_types.keys())
        probs = list(self.config.incident_types.values())
        total = sum(probs)
        probs = [p / total for p in probs]
        return int(np.random.choice(types, p=probs))

    def _pick_duration(self, incident_type: int) -> float:
        avg = self.config.duration_by_type.get(incident_type, 60)
        # Log-normal distribution centered on average
        return max(5, np.random.lognormal(math.log(avg), 0.4))

    @staticmethod
    def _make_record(dt, vehicle, intervention, intervention_type,
                     status, availability, lat1, lon1, lat2, lon2):
        return {
            'datetime': dt,
            'unit': vehicle['unit'],
            'unit_type': vehicle['unit_type'],
            'intervention_type': intervention_type,
            'id_unit_selection': intervention,
            'intervention': intervention,
            'unit_lso': vehicle['unit_lso'],
            'status': status,
            'availability': availability,
            'latitude1': lat1,
            'longitude1': lon1,
            'latitude2': lat2,
            'longitude2': lon2,
        }

    def insert_into_db(self, db_host, db_name, db_user, db_password):
        """Insert generated records into PostgreSQL data_id table."""
        if not self.records:
            return 0

        self._report(95, "Inserting into database...")

        conn = psycopg2.connect(
            host=db_host, database=db_name,
            user=db_user, password=db_password)
        cur = conn.cursor()

        # Get unit ID range for this simulation
        unit_ids = set(r['unit'] for r in self.records)
        min_unit = min(unit_ids)
        max_unit = max(unit_ids)

        # Delete existing records for these units
        cur.execute(
            "DELETE FROM data_id WHERE unit >= %s AND unit <= %s",
            (min_unit, max_unit))
        deleted = cur.rowcount
        if deleted > 0:
            print(f"[Generator] Deleted {deleted} existing records "
                  f"for units {min_unit}-{max_unit}", file=sys.stderr)

        # Batch insert
        inserted = 0
        for rec in self.records:
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
                conn.commit()
                pct = 95 + int(4 * inserted / len(self.records))
                self._report(pct, f"Inserted {inserted}/{len(self.records)} records...")

        conn.commit()
        cur.close()
        conn.close()

        self._report(100, f"Done! Inserted {inserted} records")
        return inserted


# =============================================================================
# Standalone CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Generate simulation data')
    parser.add_argument('--city', required=True, help='City slug')
    parser.add_argument('--roads-dir', help='Path to roads CSV directory')
    parser.add_argument('--stations', default='auto:3',
                        help='Station config: "auto:N" or JSON file path')
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--speed', type=float, default=40.0, help='Vehicle speed km/h')
    parser.add_argument('--unit-offset', type=int, default=100)
    parser.add_argument('--db-host', default='localhost')
    parser.add_argument('--db-name', default='ems')
    parser.add_argument('--db-user', default='postgres')
    parser.add_argument('--db-password', default='postgres')
    parser.add_argument('--dry-run', action='store_true',
                        help='Generate but do not insert into DB')
    args = parser.parse_args()

    # Resolve roads directory
    if args.roads_dir:
        roads_dir = args.roads_dir
    else:
        base = Path(__file__).parent.parent / 'preprocessing' / 'output'
        roads_dir = str(base / args.city / 'roads')

    # Load graph
    graph = RoadGraph(roads_dir)

    # Configure stations
    if args.stations.startswith('auto:'):
        n = int(args.stations.split(':')[1])
        stations = graph.propose_stations(n)
        # Apply paris fleet defaults
        for s in stations:
            total = round(paris_UNITS_PER_STATION)
            s['fleet'] = {
                2: round(total * paris_FLEET_RATIO[2]),
                3: round(total * paris_FLEET_RATIO[3]),
            }
        print(f"[CLI] Auto-proposed {n} stations:", file=sys.stderr)
        for s in stations:
            print(f"  {s['name']}: ({s['lat']}, {s['lon']}) "
                  f"fleet={s['fleet']}", file=sys.stderr)
    else:
        with open(args.stations) as f:
            stations = json.load(f)

    config = SimulationConfig(
        city=args.city,
        stations=stations,
        duration_days=args.days,
        speed_kmh=args.speed,
        unit_id_offset=args.unit_offset,
    )

    generator = SimulationGenerator(graph, config)
    records = generator.generate()

    if args.dry_run:
        print(f"[CLI] Dry run: {len(records)} records generated", file=sys.stderr)
        # Print sample
        for r in records[:5]:
            print(r, file=sys.stderr)
    else:
        inserted = generator.insert_into_db(
            args.db_host, args.db_name, args.db_user, args.db_password)
        print(f"[CLI] Inserted {inserted} records", file=sys.stderr)


if __name__ == '__main__':
    main()

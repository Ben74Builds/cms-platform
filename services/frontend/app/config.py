import os

SERVICE = 'paris'
# Redis channels
REDIS_CHANNEL = SERVICE + '_gps_status'

DEFAULT_LANGUAGE = 'en_US'

# ============================================================================
# City / Deployment Area Configuration
# ============================================================================

# Hardcoded fallback (used if DB is unavailable)
_FALLBACK_CITIES = {
    "paris": {
        "name": "Paris / Ile-de-France",
        "description": "Metropolitan Paris emergency services coverage area",
        "center": [2.333333, 48.866667],
        "zoom": 12,
        "building_tiles": "paris_buildings",
        "road_tiles": "paris_roads",
        "building_source_layer": "buildings",
        "road_source_layer": "roads",
        "service": "paris",
        "service_id": 1,
        "unit_id_offset": 1000,
    },
    "andorra": {
        "name": "Andorra",
        "description": "Principality of Andorra coverage area",
        "center": [1.5218, 42.5063],
        "zoom": 13,
        "building_tiles": "andorra_buildings",
        "road_tiles": "andorra_roads",
        "building_source_layer": "buildings",
        "road_source_layer": "roads",
        "service": "andorra",
        "service_id": 2,
        "unit_id_offset": 100,
    },
    "vaduz": {
        "name": "Vaduz",
        "description": "Principality of Liechtenstein coverage area",
        "center": [9.5215, 47.1410],
        "zoom": 14,
        "building_tiles": "vaduz_buildings",
        "road_tiles": "vaduz_roads",
        "building_source_layer": "buildings",
        "road_source_layer": "roads",
        "service": "vaduz",
        "service_id": 11,
        "unit_id_offset": 1100,
    },
    "san-marino": {
        "name": "San Marino",
        "description": "Republic of San Marino coverage area",
        "center": [12.4578, 43.9424],
        "zoom": 14,
        "building_tiles": "san-marino_buildings",
        "road_tiles": "san-marino_roads",
        "building_source_layer": "buildings",
        "road_source_layer": "roads",
        "service": "san-marino",
        "service_id": 12,
        "unit_id_offset": 1200,
    },
    "annecy": {
        "name": "Annecy",
        "description": "Annecy metropolitan area coverage",
        "center": [6.1294, 45.8992],
        "zoom": 13,
        "building_tiles": "annecy_buildings",
        "road_tiles": "annecy_roads",
        "building_source_layer": "buildings",
        "road_source_layer": "roads",
        "service": "annecy",
        "service_id": 13,
        "unit_id_offset": 1300,
    },
}


def _get_db_connection():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", os.getenv("POSTGRES_HOST", "postgres")),
        database=os.getenv("DB_NAME", os.getenv("POSTGRES_DB", "ems")),
        user=os.getenv("DB_USER", os.getenv("POSTGRES_USER", "postgres")),
        password=os.getenv("DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "postgres")),
    )


def load_cities_from_db(status_filter="ready"):
    """Load cities from PostgreSQL, fallback to hardcoded config."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        if status_filter:
            cur.execute("SELECT * FROM cities WHERE status = %s", (status_filter,))
        else:
            cur.execute("SELECT * FROM cities")
        columns = [desc[0] for desc in cur.description]
        cities = {}
        for row in cur.fetchall():
            r = dict(zip(columns, row))
            cities[r['slug']] = {
                'name': r['name'],
                'description': r.get('description', ''),
                'center': [float(r['center_lon']), float(r['center_lat'])],
                'zoom': r.get('zoom', 13),
                'building_tiles': r.get('building_tiles', r['slug'] + '_buildings'),
                'road_tiles': r.get('road_tiles', r['slug'] + '_roads'),
                'building_source_layer': r.get('building_source_layer', 'buildings'),
                'road_source_layer': r.get('road_source_layer', 'roads'),
                'service': r.get('service', r['slug']),
                'service_id': r.get('service_id', 1),
                'coverage_threshold_sec': r.get('coverage_threshold_sec', 600),
                'unit_id_offset': r.get('unit_id_offset', 100),
                'status': r.get('status', 'ready'),
                'country_code': r.get('country_code', ''),
            }
        cur.close()
        conn.close()
        if cities:
            return cities
    except Exception as e:
        print(f"[config] Could not load cities from DB: {e}, using fallback")
    return dict(_FALLBACK_CITIES)


def load_all_cities_from_db():
    """Load ALL cities (including pending/processing) from DB."""
    return load_cities_from_db(status_filter=None)


def reload_cities():
    """Reload CITIES dict from database (mutate in-place so all importers see the update)."""
    new = load_cities_from_db()
    CITIES.clear()
    CITIES.update(new)
    print(f"[config] Reloaded {len(CITIES)} cities from DB")
    return CITIES


# Load cities at import time
CITIES = load_cities_from_db()

DEFAULT_CITY = "paris"

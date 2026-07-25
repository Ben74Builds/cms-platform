-- ============================================================================
-- City Management Tables
-- ============================================================================

-- World cities reference (populated from GeoNames cities500)
CREATE TABLE IF NOT EXISTS world_cities (
    geonameid    INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    asciiname    TEXT NOT NULL,
    country_code CHAR(2),
    latitude     NUMERIC(9,6),
    longitude    NUMERIC(10,6),
    population   INTEGER DEFAULT 0,
    timezone     TEXT
);

CREATE INDEX IF NOT EXISTS idx_wc_asciiname ON world_cities (asciiname text_pattern_ops);
CREATE INDEX IF NOT EXISTS idx_wc_name ON world_cities (name text_pattern_ops);
CREATE INDEX IF NOT EXISTS idx_wc_population ON world_cities (population DESC);

-- Deployed cities (dynamic config, replaces hardcoded CITIES dict)
CREATE TABLE IF NOT EXISTS cities (
    slug              TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    description       TEXT,
    center_lat        NUMERIC(9,6),
    center_lon        NUMERIC(10,6),
    zoom              INTEGER DEFAULT 13,
    building_tiles    TEXT,
    road_tiles        TEXT,
    building_source_layer TEXT DEFAULT 'buildings',
    road_source_layer TEXT DEFAULT 'roads',
    service           TEXT,
    service_id        INTEGER DEFAULT 1,
    coverage_threshold_sec INTEGER DEFAULT 600,
    unit_id_offset    INTEGER DEFAULT 100,
    status            TEXT DEFAULT 'pending',
    country_code      CHAR(2),
    created_at        TIMESTAMP DEFAULT NOW()
);

-- Seed existing cities
INSERT INTO cities (slug, name, description, center_lat, center_lon, zoom, building_tiles, road_tiles, building_source_layer, road_source_layer, service, service_id, unit_id_offset, status, country_code)
VALUES
    ('paris', 'Paris / Ile-de-France', 'Metropolitan Paris emergency services coverage area', 48.866667, 2.333333, 12, 'paris_buildings', 'paris_roads', 'buildings', 'roads', 'paris', 1, 1000, 'ready', 'FR'),
    ('andorra', 'Andorra', 'Principality of Andorra coverage area', 42.5063, 1.5218, 13, 'andorra_buildings', 'andorra_roads', 'buildings', 'roads', 'andorra', 2, 100, 'ready', 'AD'),
    ('vaduz', 'Vaduz', 'Principality of Liechtenstein coverage area', 47.1410, 9.5215, 14, 'vaduz_buildings', 'vaduz_roads', 'buildings', 'roads', 'vaduz', 11, 1100, 'ready', 'LI'),
    ('san-marino', 'San Marino', 'Republic of San Marino coverage area', 43.9424, 12.4578, 14, 'san-marino_buildings', 'san-marino_roads', 'buildings', 'roads', 'san-marino', 12, 1200, 'ready', 'SM'),
    ('annecy', 'Annecy', 'Annecy metropolitan area coverage', 45.8992, 6.1294, 13, 'annecy_buildings', 'annecy_roads', 'buildings', 'roads', 'annecy', 13, 1300, 'ready', 'FR')
ON CONFLICT (slug) DO NOTHING;

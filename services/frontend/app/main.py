"""
FastAPI application for Service Coverage Monitoring
Migrated from Flask with async support and SSE streaming
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import redis.asyncio as redis
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.gzip import GZipMiddleware
from aiokafka import AIOKafkaConsumer

from config import SERVICE, REDIS_CHANNEL, DEFAULT_LANGUAGE, CITIES, DEFAULT_CITY, load_all_cities_from_db, reload_cities, _get_db_connection
import time


# ============================================================================
# Environment Configuration
# ============================================================================

DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() in ("true", "1", "yes")
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() in ("true", "1", "yes")


# ============================================================================
# Simple Prometheus-style Metrics (no external dependency)
# ============================================================================

class SimpleMetrics:
    """Thread-safe metrics collection for Prometheus exposition"""

    def __init__(self):
        self.counters = {}
        self.histograms = {}
        self.gauges = {}

    def inc_counter(self, name: str, labels: dict = None, value: int = 1):
        key = self._make_key(name, labels)
        self.counters[key] = self.counters.get(key, 0) + value

    def observe_histogram(self, name: str, value: float, labels: dict = None):
        key = self._make_key(name, labels)
        if key not in self.histograms:
            self.histograms[key] = {"count": 0, "sum": 0.0, "buckets": {}}
        self.histograms[key]["count"] += 1
        self.histograms[key]["sum"] += value
        # Standard Prometheus histogram buckets
        for bucket in [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]:
            bucket_key = str(bucket)
            if value <= bucket:
                self.histograms[key]["buckets"][bucket_key] = \
                    self.histograms[key]["buckets"].get(bucket_key, 0) + 1

    def set_gauge(self, name: str, value: float, labels: dict = None):
        key = self._make_key(name, labels)
        self.gauges[key] = value

    def inc_gauge(self, name: str, labels: dict = None, value: float = 1.0):
        key = self._make_key(name, labels)
        self.gauges[key] = self.gauges.get(key, 0.0) + value

    def _make_key(self, name: str, labels: dict = None) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def export(self) -> str:
        """Export metrics in Prometheus text exposition format"""
        lines = []

        # Counters
        for key, value in sorted(self.counters.items()):
            lines.append(f"{key} {value}")

        # Gauges
        for key, value in sorted(self.gauges.items()):
            lines.append(f"{key} {value}")

        # Histograms
        for key, data in sorted(self.histograms.items()):
            base_name = key.split("{")[0] if "{" in key else key
            label_part = "{" + key.split("{")[1] if "{" in key else ""

            for bucket_val in sorted(data["buckets"].keys(), key=float):
                count = data["buckets"][bucket_val]
                if label_part:
                    lines.append(f'{base_name}_bucket{{le="{bucket_val}",{label_part[1:]} {count}')
                else:
                    lines.append(f'{base_name}_bucket{{le="{bucket_val}"}} {count}')

            if label_part:
                lines.append(f'{base_name}_count{label_part} {data["count"]}')
                lines.append(f'{base_name}_sum{label_part} {data["sum"]:.6f}')
            else:
                lines.append(f'{base_name}_count {data["count"]}')
                lines.append(f'{base_name}_sum {data["sum"]:.6f}')

        return "\n".join(lines)


metrics = SimpleMetrics()


# ============================================================================
# Configuration
# ============================================================================

APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"
LANGUAGES_DIR = STATIC_DIR / "data" / "languages"
TILES_DIR = STATIC_DIR / "data" / "tiles"

SUPPORTED_LANGUAGES = ["en_US", "fr_FR"]
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BROKER", "kafka:29092")

# Empty PBF tile (minimal valid protobuf - empty tile)
EMPTY_PBF_TILE = bytes([0x1a, 0x00])


# ============================================================================
# i18n / Translations
# ============================================================================

translations: dict[str, dict] = {}


def load_translations():
    """Load all translation files at startup"""
    global translations
    for lang_code in SUPPORTED_LANGUAGES:
        lang_file = LANGUAGES_DIR / f"{lang_code}.json"
        if lang_file.exists():
            with open(lang_file, "r", encoding="utf-8") as f:
                translations[lang_code] = json.load(f)
        else:
            translations[lang_code] = {}


def get_translation(lang: str, key: str, default: str = "") -> str:
    """Get a translation for a given language and key"""
    return translations.get(lang, {}).get(key, default or key)


def t(lang: str):
    """Return a translation function for use in templates"""
    def translate(key: str, default: str = "") -> str:
        return get_translation(lang, key, default)
    return translate


# ============================================================================
# Redis Connection
# ============================================================================

redis_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global redis_client
    if redis_client is None:
        redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    return redis_client


# ============================================================================
# Lifespan (startup/shutdown)
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    # Startup
    load_translations()
    print(f"Loaded translations for: {list(translations.keys())}")

    load_all_cities()

    yield

    # Shutdown
    global redis_client
    if redis_client:
        await redis_client.close()


# ============================================================================
# Per-City Data (building-segment mappings + road graphs)
# ============================================================================

# Per-city data stores
city_data: dict[str, dict] = {}
_osm_station_cache: dict[str, dict] = {}


def _load_city_mapping(city_slug: str):
    """Load building_segment_mapping.json for a city"""
    candidates = [
        # Docker per-city mount
        Path(f"/app/data/cities/{city_slug}/building_segment_mapping.json"),
        Path(f"/app/data/{city_slug}/building_segment_mapping.json"),
        # Local development
        Path(__file__).parent.parent.parent.parent / "preprocessing" / "output" / city_slug / "building_segment_mapping.json",
    ]
    if city_slug == DEFAULT_CITY:
        # Legacy flat paths for default city
        candidates.extend([
            Path("/app/data/building_segment_mapping.json"),
            Path(__file__).parent.parent.parent.parent / "preprocessing" / "output" / "building_segment_mapping.json",
        ])

    mapping_path = None
    for p in candidates:
        if p.exists():
            mapping_path = p
            break

    if not mapping_path.exists():
        print(f"[{city_slug}] building_segment_mapping.json not found, skipping")
        return

    with open(mapping_path, "r") as f:
        segment_mapping = json.load(f)

    # Build reverse index
    building_to_segs: dict[int, list[str]] = {}
    all_building_ids = set()
    for seg_id, building_ids in segment_mapping.items():
        for bid in building_ids:
            all_building_ids.add(bid)
            building_to_segs.setdefault(bid, []).append(seg_id)

    stats = {
        "total_segments": len(segment_mapping),
        "total_buildings_in_mapping": len(all_building_ids),
        "avg_buildings_per_segment": round(
            sum(len(v) for v in segment_mapping.values()) / max(len(segment_mapping), 1), 2
        ),
        "avg_segments_per_building": round(
            sum(len(v) for v in building_to_segs.values()) / max(len(building_to_segs), 1), 2
        ),
    }

    city_data[city_slug]["segment_mapping"] = segment_mapping
    city_data[city_slug]["building_to_segments"] = building_to_segs
    city_data[city_slug]["stats"] = stats

    print(f"[{city_slug}] Loaded mapping: {stats['total_segments']} segments, "
          f"{stats['total_buildings_in_mapping']} buildings")


def _load_city_road_graph(city_slug: str):
    """Load road CSVs for a city"""
    candidates = [
        Path(f"/app/data/cities/{city_slug}/roads"),
        Path(f"/app/data/{city_slug}/roads"),
        Path(__file__).parent.parent.parent.parent / "preprocessing" / "output" / city_slug / "roads",
    ]
    if city_slug == DEFAULT_CITY:
        candidates.extend([
            Path("/app/data/roads"),
            Path(__file__).parent.parent.parent.parent / "preprocessing" / "output" / "roads",
        ])

    roads_dir = None
    for p in candidates:
        if p.exists():
            roads_dir = p
            break

    if not roads_dir:
        print(f"[{city_slug}] roads/ not found, skipping")
        return

    def read_csv_ints(filename):
        with open(roads_dir / filename) as f:
            return [int(line.strip()) for line in f if line.strip()]

    def read_csv_floats(filename):
        with open(roads_dir / filename) as f:
            return [float(line.strip()) for line in f if line.strip()]

    way_osmid = read_csv_ints("way_osmid.csv")
    way = read_csv_ints("way.csv")
    head = read_csv_ints("head.csv")
    tail = read_csv_ints("tail.csv")
    lat = read_csv_floats("latitude.csv")
    lon = read_csv_floats("longitude.csv")

    seg_geoms: dict[int, list] = {}
    for i in range(len(way)):
        osm_id = way_osmid[way[i]]
        h, t_idx = head[i], tail[i]
        if osm_id not in seg_geoms:
            seg_geoms[osm_id] = []
        seg_geoms[osm_id].append([
            [lon[t_idx], lat[t_idx]],
            [lon[h], lat[h]]
        ])

    city_data[city_slug]["segment_geometries"] = seg_geoms
    # Store raw graph arrays for simulation generator
    city_data[city_slug]["raw_graph"] = {
        "roads_dir": str(roads_dir),
        "n_nodes": len(lat),
        "n_edges": len(way),
    }
    print(f"[{city_slug}] Loaded road graph: {len(seg_geoms)} ways, {len(way)} edges")


def load_all_cities():
    """Load data for all configured cities"""
    for city_slug in CITIES:
        city_data[city_slug] = {
            "segment_mapping": {},
            "building_to_segments": {},
            "segment_geometries": {},
            "stats": {},
        }
        _load_city_mapping(city_slug)
        _load_city_road_graph(city_slug)


# Backward-compatible accessors (for default city)
def _get_city(city_slug: str) -> dict:
    if city_slug not in city_data or not city_data[city_slug].get("raw_graph"):
        # Lazy-load city data if not yet loaded in this worker
        if city_slug in CITIES:
            city_data[city_slug] = {
                "segment_mapping": {},
                "building_to_segments": {},
                "segment_geometries": {},
                "stats": {},
            }
            _load_city_mapping(city_slug)
            _load_city_road_graph(city_slug)
    return city_data.get(city_slug, city_data.get(DEFAULT_CITY, {}))


def _get_city_population(city_slug: str) -> int:
    """Get population from world_cities table, matching by city name."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        city_name = CITIES.get(city_slug, {}).get("name", city_slug)
        cur.execute("SELECT population FROM world_cities WHERE name = %s ORDER BY population DESC LIMIT 1", (city_name,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row[0] if row else 50000  # default if unknown
    except Exception:
        return 50000


def _compute_station_fleets(population: int, stations: list) -> None:
    """Assign density-aware fleet to each station based on Paris operational profiles.

    Uses station type (CSP/CS/CPI) and name patterns to classify density tier,
    then applies the matching Paris tier's fleet composition.
    """
    from density_profiles import compute_fleet_for_stations, get_simulation_params
    compute_fleet_for_stations(stations, population)
    sim = get_simulation_params(stations, population)

    # Add simulation summary to first station (hack for API response enrichment)
    if stations:
        stations[0]["_sim_summary"] = sim


# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(
    title="Service Coverage Monitoring",
    description="Real-time service coverage visualization",
    version="2.0.0",
    lifespan=lifespan
)

# Enable GZip compression for responses > 500 bytes (60-80% smaller payloads)
app.add_middleware(GZipMiddleware, minimum_size=500)


# ============================================================================
# Metrics Middleware
# ============================================================================

from starlette.middleware.base import BaseHTTPMiddleware

class MetricsMiddleware(BaseHTTPMiddleware):
    """Track HTTP request metrics (skips tile requests for performance)"""

    async def dispatch(self, request, call_next):
        path = request.url.path

        # Skip metrics for tile requests — high volume, low value
        if path.startswith("/static/data/tiles/"):
            return await call_next(request)

        start_time = time.time()
        method = request.method

        response = await call_next(request)

        # Record metrics
        if METRICS_ENABLED:
            duration = time.time() - start_time
            status = str(response.status_code)

            metrics.inc_counter(
                "http_requests_total",
                {"method": method, "path": path, "status": status}
            )

            metrics.observe_histogram(
                "http_request_duration_seconds",
                duration,
                {"method": method, "path": path}
            )

        return response


app.add_middleware(MetricsMiddleware)

# ============================================================================
# Tile serving with fallback to empty tile
# ============================================================================

# Immutable tiles: cache for 1 year (tiles are pre-generated and never change)
_TILE_CACHE_HEADERS = {
    "Cache-Control": "public, max-age=31536000, immutable",
    "Access-Control-Allow-Origin": "*",
}


@app.get("/static/data/tiles/{tileset}/{z}/{x}/{y}.pbf")
async def serve_tile(tileset: str, z: int, x: int, y: int):
    """Serve PBF tiles using zero-copy sendfile, with empty tile fallback"""
    tile_path = TILES_DIR / tileset / str(z) / str(x) / f"{y}.pbf"

    if tile_path.exists():
        return FileResponse(
            path=tile_path,
            media_type="application/x-protobuf",
            headers=_TILE_CACHE_HEADERS,
        )
    else:
        return Response(
            content=EMPTY_PBF_TILE,
            media_type="application/x-protobuf",
            headers=_TILE_CACHE_HEADERS,
        )


# Mount static files (after tile route to allow override)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ============================================================================
# Vite Integration (automatic cache-busting with content hashes)
# ============================================================================

from vite_integration import register_vite_helpers, is_vite_dev_mode

# Register Vite helpers: vite_asset(), vite_dev_mode(), vite_hmr_client()
register_vite_helpers(templates)


def static_url(filename: str) -> str:
    """
    Fallback for non-bundled static files (libraries, data files).
    Uses file modification time for cache busting.
    """
    file_path = STATIC_DIR / filename
    if file_path.exists():
        mtime = int(file_path.stat().st_mtime)
        return f"/static/{filename}?v={mtime}"
    return f"/static/{filename}"


templates.env.globals["static_url"] = static_url


# ============================================================================
# Routes
# ============================================================================

@app.get("/favicon.ico", response_class=RedirectResponse)
async def favicon():
    """Redirect favicon.ico to logo.png"""
    return RedirectResponse(url="/static/img/logo.png", status_code=301)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page with navigation to available views"""
    all_cities = load_all_cities_from_db()
    ready = {s: c for s, c in all_cities.items() if c.get('status') == 'ready'}
    pending = {s: c for s, c in all_cities.items() if c.get('status') in ('pending', 'processing')}

    # Check which cities have simulation data
    cities_with_simulation = set()
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "postgres"),
            database=os.getenv("DB_NAME", "ems"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres"),
        )
        cur = conn.cursor()
        for slug, cfg in ready.items():
            center_lon, center_lat = cfg.get("center", [0, 0])
            cur.execute("""
                SELECT 1 FROM data_id
                WHERE latitude1 BETWEEN %s AND %s
                  AND longitude1 BETWEEN %s AND %s
                LIMIT 1
            """, (center_lat - 1, center_lat + 1,
                  center_lon - 1, center_lon + 1))
            if cur.fetchone():
                cities_with_simulation.add(slug)
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[home] Could not check simulation data: {e}")

    return templates.TemplateResponse("home.html", {
        "request": request,
        "cities": ready,
        "pending_cities": pending,
        "default_city": DEFAULT_CITY,
        "cities_with_simulation": cities_with_simulation,
    })


@app.get("/admin/linkage", response_class=RedirectResponse)
async def linkage_inspector_redirect():
    """Redirect to default city linkage inspector"""
    return RedirectResponse(url=f"/area/{DEFAULT_CITY}/admin/linkage", status_code=302)


@app.get("/area/{city}/admin/linkage", response_class=HTMLResponse)
async def linkage_inspector(request: Request, city: str):
    """Admin page for inspecting building-to-road-segment linkages"""
    if city not in CITIES:
        reload_cities()
    if city not in CITIES:
        raise HTTPException(status_code=404, detail=f"City '{city}' not found")
    city_config = CITIES[city]
    context = {
        "request": request,
        "lang": DEFAULT_LANGUAGE,
        "PAGE_TITLE": f"Linkage Inspector - {city_config['name']}",
        "city": city,
        "city_config": city_config,
    }
    return templates.TemplateResponse("admin_linkage.html", context)


@app.get("/area/{city}/admin/simulation", response_class=HTMLResponse)
async def simulation_admin(request: Request, city: str):
    """Admin page for configuring and generating simulation data"""
    if city not in CITIES:
        reload_cities()
    if city not in CITIES:
        raise HTTPException(status_code=404, detail=f"City '{city}' not found")
    city_config = CITIES[city]
    return templates.TemplateResponse("admin_simulation.html", {
        "request": request,
        "lang": DEFAULT_LANGUAGE,
        "PAGE_TITLE": f"Simulation - {city_config['name']}",
        "city": city,
        "city_config": city_config,
    })


@app.get("/area/{city}/map", response_class=HTMLResponse)
@app.get("/area/{city}/{lang}/map", response_class=HTMLResponse)
async def city_map_view(request: Request, city: str, lang: str = None):
    """City-specific map view"""
    if city not in CITIES:
        reload_cities()
    if city not in CITIES:
        raise HTTPException(status_code=404, detail=f"City '{city}' not found")
    if lang is None or lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE

    city_config = CITIES[city]
    context = {
        "request": request,
        "lang": lang,
        "lang_data": translations.get(lang, {}),
        "t": t(lang),
        "service_coverage": get_translation(lang, "service_coverage", "Service Coverage"),
        "PAGE_URL": str(request.url),
        "PAGE_TITLE": f"{city_config['name']} - Live Coverage",
        "debug_mode": DEBUG_MODE,
        "city": city,
        "city_config": city_config,
    }

    return templates.TemplateResponse("index.html", context)


@app.get("/{lang}/map", response_class=HTMLResponse)
async def map_view(request: Request, lang: str):
    """Main map view with language support (legacy, default city)"""
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE
    return RedirectResponse(url=f"/area/{DEFAULT_CITY}/{lang}/map", status_code=302)


@app.get("/map", response_class=RedirectResponse)
async def map_redirect():
    """Redirect /map to default city"""
    return RedirectResponse(url=f"/area/{DEFAULT_CITY}/map", status_code=302)


# ============================================================================
# Server-Sent Events (SSE) for Kafka
# ============================================================================

async def kafka_event_generator(topic_name: str) -> AsyncGenerator[str, None]:
    """Generate SSE events from Kafka topic"""
    print(f"[SSE] Connecting to Kafka topic: {topic_name}")
    consumer = AIOKafkaConsumer(
        topic_name,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset="latest",
        enable_auto_commit=False,
        group_id=None  # No consumer group - each SSE connection is independent
    )

    msg_count = 0
    try:
        await consumer.start()
        print(f"[SSE] Connected to {topic_name}, streaming...")
        async for message in consumer:
            if message.value:
                data = message.value.decode("utf-8")
                msg_count += 1
                if msg_count <= 3 or msg_count % 100 == 0:
                    print(f"[SSE] {topic_name}: msg #{msg_count}, {len(data)} bytes")
                yield f"data:{data}\n\n"
    except asyncio.CancelledError:
        print(f"[SSE] {topic_name}: client disconnected after {msg_count} msgs")
    except Exception as e:
        print(f"[SSE] {topic_name}: error: {e}")
    finally:
        await consumer.stop()


@app.get("/topic/{topic_name}")
async def stream_topic(topic_name: str):
    """SSE endpoint for Kafka topic streaming"""
    return StreamingResponse(
        kafka_event_generator(topic_name),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ============================================================================
# Redis SSE (alternative to Kafka)
# ============================================================================

async def redis_event_generator(channel: str) -> AsyncGenerator[str, None]:
    """Generate SSE events from Redis pub/sub"""
    client = await get_redis()
    pubsub = client.pubsub()

    try:
        await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            if message["type"] == "message":
                yield f"data:{message['data']}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()


@app.get("/stream")
async def stream_redis():
    """SSE endpoint for Redis channel streaming"""
    return StreamingResponse(
        redis_event_generator(REDIS_CHANNEL),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )


# ============================================================================
# API endpoints
# ============================================================================

@app.get("/api/languages")
async def get_languages():
    """Get list of supported languages"""
    return {
        "supported": SUPPORTED_LANGUAGES,
        "default": DEFAULT_LANGUAGE
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": SERVICE}


@app.get("/api/density-profiles")
async def get_density_profiles():
    """Return all Paris density tier profiles for the simulation wizard."""
    from density_profiles import get_all_profiles
    return get_all_profiles()


@app.post("/api/{city}/stop")
async def stop_city_simulation(city: str):
    """
    Stop a city's simulation: flush Redis coverage data and clear backend state.
    The signals container keeps running but coverage/route state is reset.
    """
    if city not in CITIES:
        reload_cities()
    if city not in CITIES:
        raise HTTPException(status_code=404, detail=f"City '{city}' not found")

    city_config = CITIES[city]
    service_name = city_config.get("service", city)

    try:
        client = redis.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            decode_responses=True
        )

        # Flush coverage snapshot
        snapshot_key = f"coverage:snapshot:{service_name}"
        await client.delete(snapshot_key)

        # Flush all per-unit coverage keys for this service (pattern: "SERVICE_ID:*:coverage")
        service_id = city_config.get("service_id", 1)
        cursor = 0
        deleted_keys = 0
        while True:
            cursor, keys = await client.scan(cursor, match=f"{service_id}:*:coverage", count=500)
            if keys:
                await client.delete(*keys)
                deleted_keys += len(keys)
            if cursor == 0:
                break

        # Flush unit position/status keys
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor, match=f"{service_name}:*", count=500)
            if keys:
                await client.delete(*keys)
                deleted_keys += len(keys)
            if cursor == 0:
                break

        await client.close()

        return {
            "status": "stopped",
            "city": city,
            "service": service_name,
            "redis_keys_flushed": deleted_keys,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop: {str(e)}")


@app.get("/api/coverage/snapshot")
async def get_coverage_snapshot(service: str = "paris"):
    """
    Get current coverage snapshot for instant page load.
    Returns aggregated building coverage from Redis, filtered by service.
    """
    try:
        client = redis.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            decode_responses=True
        )
        # Each service has its own snapshot key
        # Try service name first, then service ID, then legacy key
        snapshot_key = f"coverage:snapshot:{service}"
        snapshot = await client.get(snapshot_key)
        await client.close()

        if snapshot:
            return Response(
                content=snapshot,
                media_type="application/json",
                headers={"Cache-Control": "no-cache"}
            )
        else:
            return Response(
                content="{}",
                media_type="application/json",
                headers={"Cache-Control": "no-cache"}
            )
    except Exception as e:
        return Response(
            content=f'{{"error": "{str(e)}"}}',
            media_type="application/json",
            status_code=500
        )


@app.get("/api/{city}/coverage/compute")
async def compute_city_coverage(city: str):
    """Compute coverage for all current units using Python Dijkstra.

    Fallback for cities where the C++ backend doesn't produce coverage.
    Returns aggregated building coverage counts keyed by building ID.
    """
    if city not in CITIES:
        raise HTTPException(status_code=404, detail=f"City '{city}' not found")

    cd = _get_city(city)
    raw = cd.get("raw_graph")
    if not raw:
        return {"agg": {}}

    from simulation_generator import RoadGraph

    graph = RoadGraph(raw["roads_dir"])

    # Load building mapping
    mapping = cd.get("segment_mapping", {})

    # Get current unit positions from Redis
    import redis as _redis
    r = _redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        decode_responses=True,
    )

    # Find city's units
    cfg = CITIES[city]
    service_id = cfg.get("service_id", 1)
    snapshot = _build_snapshot_from_redis(service_id)
    import json as _json
    body = snapshot.body if hasattr(snapshot, 'body') else b"[]"
    data = _json.loads(body)

    units = data[0]["data"] if data and data[0].get("data") else []

    # Coverage threshold from city config (Paris=600s/10min, rural=1200s/20min)
    threshold_sec = cfg.get("coverage_threshold_sec", 600)

    # Compute coverage per unit
    agg = {}  # building_id -> coverage_count
    per_unit = []
    for u in units:
        gp = u.get("gp1")
        if not gp:
            continue
        unit_id = u["uni"][0]
        node = graph.nearest_node(gp[0], gp[1])
        bids = graph.reachable_buildings(node, threshold_sec, mapping)
        for bid in bids:
            agg[str(bid)] = agg.get(str(bid), 0) + 1
        per_unit.append({"uni": unit_id, "bld": [str(b) for b in bids]})

    return {"agg": agg, "data": per_unit, "units": len(units),
            "threshold_sec": threshold_sec}


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint"""
    if not METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="Metrics disabled")
    return Response(
        content=metrics.export(),
        media_type="text/plain; version=0.0.4; charset=utf-8"
    )


@app.get("/api/gp_and_status/{service_id}")
async def proxy_gp_and_status(service_id: int):
    """Proxy to backend API for GPS and status data.

    Tries the C++ backend first.  If it returns an empty array (e.g. topic
    not consumed yet), fall back to reading current unit state from Redis
    (populated by the signals service).
    """
    import httpx

    # Try C++ backend first (it only handles service 1 / paris currently)
    backend_url = os.getenv("BACKEND_API_URL", "http://localhost:9080")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{backend_url}/get_gp_and_status/{service_id}")
            body = response.text.strip()
            if body.startswith("[{") and len(body) > 4:
                return Response(content=response.content, status_code=response.status_code,
                                media_type="application/json")
    except Exception:
        pass

    # Fallback: build snapshot from Redis (customer_side:mma:* written by signals)
    # Find city slug for this service_id to get its UNIT_FILTER
    return _build_snapshot_from_redis(service_id)


def _build_snapshot_from_redis(service_id: int):
    """Read current unit positions from signals-written Redis hashes.

    Discovers which unit IDs belong to this service by querying the DB
    for distinct units in the data_id table matching the signals config.
    """
    import redis as _redis

    r = _redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        decode_responses=True,
    )

    # Find the city config for this service_id
    city_cfg = None
    for slug, cfg in CITIES.items():
        if cfg.get("service_id") == service_id:
            city_cfg = cfg
            break

    if city_cfg is None:
        return Response(content="[]", media_type="application/json")

    # Get known unit IDs for this city from DB
    # Use lat/lon proximity to city center to filter simulation units
    offset = city_cfg.get("unit_id_offset", 0)
    center_lon, center_lat = city_cfg.get("center", [0, 0])
    known_units = set()
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "postgres"),
            database=os.getenv("DB_NAME", "ems"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres"),
        )
        cur = conn.cursor()
        # Find units that have positions near the city center (within ~1 degree)
        cur.execute("""
            SELECT DISTINCT unit FROM data_id
            WHERE unit >= %s AND unit < %s
              AND latitude1 BETWEEN %s AND %s
              AND longitude1 BETWEEN %s AND %s
        """, (offset, offset + 100,
              center_lat - 1, center_lat + 1,
              center_lon - 1, center_lon + 1))
        known_units = {row[0] for row in cur.fetchall()}
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[gp_and_status] DB lookup failed: {e}")

    if not known_units:
        return Response(content="[]", media_type="application/json")

    # Read known units directly from Redis
    units_data = []
    for unit_id in known_units:
        key = f"customer_side:mma:{unit_id}"
        h = r.hgetall(key)
        if not h.get("latitude1") or not h.get("longitude1"):
            continue

        entry = {"uni": [unit_id]}
        if h.get("unit type"):
            entry["uni"].append(int(h["unit type"]))
        else:
            entry["uni"].append(None)
        if h.get("unit lso"):
            entry["uni"].append(int(h["unit lso"]))
        else:
            entry["uni"].append(None)
        if h.get("competences"):
            entry["uni"].append([int(c) for c in h["competences"].split(",") if c])

        entry["sta"] = [
            int(h["status"]) if h.get("status") else 1,
            int(h["availability"]) if h.get("availability") else 1,
        ]
        entry["gp1"] = [float(h["latitude1"]), float(h["longitude1"])]

        units_data.append(entry)

    if not units_data:
        return Response(content="[]", media_type="application/json")

    from datetime import datetime as _dt
    snapshot = [{
        "date": _dt.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "serv": service_id,
        "data": units_data,
    }]
    return Response(content=json.dumps(snapshot), media_type="application/json")


@app.post("/api/errors")
async def receive_frontend_errors(request: Request):
    """Receive and log frontend errors"""
    import logging

    try:
        data = await request.json()
        errors = data.get("errors", [])
        meta = data.get("meta", {})

        # Log errors in structured JSON format
        for error in errors:
            logging.error(json.dumps({
                "type": "frontend_error",
                "session_id": meta.get("sessionId"),
                "error_type": error.get("type"),
                "message": error.get("message"),
                "source": error.get("source"),
                "line": error.get("lineno"),
                "column": error.get("colno"),
                "url": error.get("url"),
                "timestamp": error.get("timestamp"),
                "user_agent": error.get("userAgent"),
                "stack": error.get("stack")
            }))

        # Track in metrics
        if METRICS_ENABLED:
            for error in errors:
                metrics.inc_counter(
                    "frontend_errors_total",
                    {"type": error.get("type", "unknown")}
                )

        return {"status": "received", "count": len(errors)}

    except Exception as e:
        logging.error(f"Failed to process frontend errors: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/{city}/admin/segment/{osm_id}/buildings")
async def get_segment_buildings(city: str, osm_id: str):
    """Get all building IDs linked to a road segment"""
    cd = _get_city(city)
    buildings = cd.get("segment_mapping", {}).get(osm_id, [])
    return {"osm_id": osm_id, "building_ids": buildings, "count": len(buildings)}


@app.get("/api/{city}/admin/building/{building_id}/segments")
async def get_building_segments(city: str, building_id: int):
    """Get all road segment IDs linked to a building"""
    cd = _get_city(city)
    segments = cd.get("building_to_segments", {}).get(building_id, [])
    return {"building_id": building_id, "segment_osm_ids": segments, "count": len(segments)}


@app.get("/api/{city}/admin/stats")
async def get_linkage_stats(city: str):
    """Get global linkage statistics"""
    cd = _get_city(city)
    return cd.get("stats", {})


@app.get("/api/{city}/admin/segment/{osm_id}/geometry")
async def get_segment_geometry(city: str, osm_id: int):
    """Get road segment geometry as GeoJSON for map rendering"""
    cd = _get_city(city)
    edges = cd.get("segment_geometries", {}).get(osm_id, [])
    if not edges:
        return {"type": "FeatureCollection", "features": []}

    return {
        "type": "Feature",
        "properties": {"osm_id": osm_id, "edge_count": len(edges)},
        "geometry": {
            "type": "MultiLineString",
            "coordinates": edges
        }
    }


@app.get("/api/{city}/admin/building/{building_id}/geometry")
async def get_building_segments_geometry(city: str, building_id: int):
    """Get all road segment geometries linked to a building"""
    cd = _get_city(city)
    seg_ids = cd.get("building_to_segments", {}).get(building_id, [])
    features = []
    for sid in seg_ids:
        osm_id = int(sid)
        edges = cd.get("segment_geometries", {}).get(osm_id, [])
        if edges:
            features.append({
                "type": "Feature",
                "properties": {"osm_id": osm_id, "edge_count": len(edges)},
                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": edges
                }
            })
    return {"type": "FeatureCollection", "features": features}


# ============================================================================
# Simulation API
# ============================================================================

# Use Redis for simulation task tracking (works across uvicorn workers)
def _get_sync_redis():
    _redis_pkg = __import__('redis')
    return _redis_pkg.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        decode_responses=True
    )

def _set_task(task_id, data):
    r = _get_sync_redis()
    r.setex(f"sim_task:{task_id}", 600, json.dumps(data))  # TTL 10 min
    r.close()

def _get_task(task_id):
    r = _get_sync_redis()
    val = r.get(f"sim_task:{task_id}")
    r.close()
    if val:
        return json.loads(val)
    return None


@app.get("/api/{city}/admin/simulation/propose-stations")
async def propose_stations(city: str, count: int = 3):
    """Auto-propose station locations using k-means on road graph nodes"""
    if city not in CITIES:
        raise HTTPException(status_code=404, detail=f"City '{city}' not found")
    cd = _get_city(city)
    raw = cd.get("raw_graph")
    if not raw:
        raise HTTPException(status_code=404, detail=f"No road graph for '{city}'")

    from simulation_generator import RoadGraph, Paris_FLEET_RATIO, Paris_UNITS_PER_STATION

    graph = RoadGraph(raw["roads_dir"])
    stations = graph.propose_stations(count)

    # Add Paris-based fleet defaults
    total = round(Paris_UNITS_PER_STATION)
    for s in stations:
        s['fleet'] = {
            '2': round(total * Paris_FLEET_RATIO[2]),
            '3': round(total * Paris_FLEET_RATIO[3]),
        }

    return {"stations": stations, "count": len(stations)}


@app.get("/api/{city}/admin/simulation/snap-to-node")
async def snap_to_node(city: str, lat: float, lon: float):
    """Snap a lat/lon to the nearest road graph node"""
    if city not in CITIES:
        raise HTTPException(status_code=404, detail=f"City '{city}' not found")
    cd = _get_city(city)
    raw = cd.get("raw_graph")
    if not raw:
        raise HTTPException(status_code=404, detail=f"No road graph for '{city}'")

    from simulation_generator import RoadGraph

    graph = RoadGraph(raw["roads_dir"])
    node = graph.nearest_node(lat, lon)
    return {"node_id": node, "lat": graph.lat[node], "lon": graph.lon[node]}


# ---- Fire-station markers (used by the map view) --------------------------

_station_cache: dict = {}

@app.get("/api/{city}/stations")
async def get_city_stations(city: str):
    """Return fire/ambulance stations for a city.

    For cities with preprocessed station CSVs (e.g. Paris/paris) the CSV is
    served directly.  For every other city the Overpass API is queried and the
    result is cached in-memory.
    """
    if city not in CITIES:
        raise HTTPException(status_code=404, detail=f"City '{city}' not found")

    # Check in-memory cache first
    if city in _station_cache:
        return _station_cache[city]

    # Try city-specific CSV file first
    csv_candidates = [
        Path(f"/app/data/cities/{city}/stations.csv"),
        Path(__file__).parent / "static" / "data" / "reference" / f"{city}_stations.csv",
    ]
    # Fallback: default stations.csv for the default/legacy city
    if city == DEFAULT_CITY:
        csv_candidates.append(
            Path(__file__).parent / "static" / "data" / "reference" / "stations.csv"
        )

    for csv_path in csv_candidates:
        if csv_path.exists():
            import csv as _csv
            rows = []
            with open(csv_path) as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    rows.append({
                        "name": row.get("name") or row.get("code", "Station"),
                        "lat": float(row["lat"]),
                        "lon": float(row["lon"]),
                        "type": "fire_station",
                    })
            result = {"stations": rows, "source": "csv"}
            _station_cache[city] = result
            return result

    # Fall back to Overpass / OSM query using city center + radius
    import math
    import httpx

    city_config = CITIES[city]
    center_lon, center_lat = city_config["center"]
    # Use ~15km radius to find stations (covers most city areas)
    radius_km = 15.0
    lat_offset = radius_km / 111.0
    lon_offset = radius_km / (111.0 * math.cos(math.radians(center_lat)))
    min_lat = center_lat - lat_offset
    max_lat = center_lat + lat_offset
    min_lon = center_lon - lon_offset
    max_lon = center_lon + lon_offset

    bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    query = f"""[out:json][timeout:30];
    (
      node["amenity"="fire_station"]({bbox});
      way["amenity"="fire_station"]({bbox});
      node["amenity"="ambulance_station"]({bbox});
      way["amenity"="ambulance_station"]({bbox});
    );
    out center;"""

    overpass_urls = [
        "https://overpass-api.de/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]

    osm_result = None
    async with httpx.AsyncClient(timeout=20) as client:
        for url in overpass_urls:
            try:
                resp = await client.post(url, data={"data": query})
                if resp.status_code == 200:
                    osm_result = resp.json()
                    print(f"[stations] {city}: got {len(osm_result.get('elements', []))} elements from {url}")
                    break
                else:
                    print(f"[stations] {url} returned {resp.status_code}")
            except Exception as e:
                print(f"[stations] {url} failed: {e}")
                continue

    stations_list = []
    seen_coords = set()
    if osm_result:
        for el in osm_result.get("elements", []):
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lon = el.get("lon") or el.get("center", {}).get("lon")
            if lat is None or lon is None:
                continue
            # Deduplicate: round to ~100m grid to catch node+way duplicates
            coord_key = (round(lat, 3), round(lon, 3))
            if coord_key in seen_coords:
                continue
            seen_coords.add(coord_key)
            tags = el.get("tags", {})
            stations_list.append({
                "name": tags.get("name", tags.get("amenity", "Station")),
                "lat": lat,
                "lon": lon,
                "type": tags.get("amenity", "fire_station"),
            })

    result = {"stations": stations_list, "source": "openstreetmap"}
    # Only cache non-empty results to allow retry on transient failures
    if stations_list:
        _station_cache[city] = result
    return result


@app.get("/api/{city}/admin/simulation/osm-stations")
async def get_osm_stations(city: str):
    """Fetch real emergency station locations from OpenStreetMap Overpass API.
    Prefers verified CSV data when available, falls back to OSM Overpass with deduplication."""
    if city not in CITIES:
        raise HTTPException(status_code=404, detail=f"City '{city}' not found")

    # Prefer verified CSV stations when available (e.g. annecy_stations.csv)
    csv_result = await get_city_stations(city)
    if csv_result.get("source") == "csv" and csv_result.get("stations"):
        import copy
        csv_stations = copy.deepcopy(csv_result["stations"])
        # Add node_id field by snapping to road graph if available
        cd = _get_city(city)
        raw = cd.get("raw_graph")
        if raw:
            from simulation_generator import RoadGraph
            graph = RoadGraph(raw["roads_dir"])
            for s in csv_stations:
                node = graph.nearest_node(s["lat"], s["lon"])
                s["node_id"] = node
                s["osm_lat"] = s["lat"]
                s["osm_lon"] = s["lon"]
                s["lat"] = round(graph.lat[node], 7)
                s["lon"] = round(graph.lon[node], 7)
        population = _get_city_population(city)
        _compute_station_fleets(population, csv_stations)
        return {"stations": csv_stations, "count": len(csv_stations),
                "source": "csv (verified)", "population": population}

    cd = _get_city(city)
    raw = cd.get("raw_graph")
    if not raw:
        raise HTTPException(status_code=404, detail=f"No road graph for '{city}'")

    # Get bounding box from road graph node coordinates
    from simulation_generator import RoadGraph
    graph = RoadGraph(raw["roads_dir"])
    min_lat = min(graph.lat)
    max_lat = max(graph.lat)
    min_lon = min(graph.lon)
    max_lon = max(graph.lon)

    # Query Overpass for fire stations within bounding box
    import httpx
    bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    query = f"""[out:json][timeout:30];
    (
      node["amenity"="fire_station"]({bbox});
      way["amenity"="fire_station"]({bbox});
      node["amenity"="ambulance_station"]({bbox});
      way["amenity"="ambulance_station"]({bbox});
    );
    out center;"""

    # Check cache first
    cache_key = f"osm_stations_{city}"
    cached = _osm_station_cache.get(cache_key)
    if cached:
        return cached

    overpass_urls = [
        "https://overpass-api.de/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]

    result = None
    async with httpx.AsyncClient(timeout=20) as client:
        for url in overpass_urls:
            try:
                resp = await client.post(url, data={"data": query})
                if resp.status_code == 200:
                    result = resp.json()
                    break
                else:
                    print(f"[osm-stations] {url} returned {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                print(f"[osm-stations] {url} failed: {type(e).__name__}: {e}")
                continue

    if not result:
        raise HTTPException(status_code=502, detail="Could not reach Overpass API")

    stations = []
    seen_nodes = set()
    for el in result.get("elements", []):
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags", {})
        name = tags.get("name", tags.get("amenity", "Station"))
        amenity = tags.get("amenity", "fire_station")

        # Snap to nearest road node
        node = graph.nearest_node(lat, lon)

        # Deduplicate: OSM often has both a node and way for the same station
        # Skip if we already have a station snapped to the same road node
        if node in seen_nodes:
            print(f"[osm-stations] {city}: skipping duplicate '{name}' (same road node {node})")
            continue
        seen_nodes.add(node)

        stations.append({
            "name": name,
            "lat": round(graph.lat[node], 7),
            "lon": round(graph.lon[node], 7),
            "node_id": node,
            "osm_lat": lat,
            "osm_lon": lon,
            "type": amenity,
        })

    # Assign realistic fleet based on population and station type
    population = _get_city_population(city)
    _compute_station_fleets(population, stations)

    response = {"stations": stations, "count": len(stations), "source": "openstreetmap",
                "population": population}
    _osm_station_cache[cache_key] = response
    return response


@app.post("/api/{city}/admin/simulation/generate")
async def generate_simulation(city: str, request: Request):
    """Launch simulation data generation in background"""
    if city not in CITIES:
        raise HTTPException(status_code=404, detail=f"City '{city}' not found")
    cd = _get_city(city)
    raw = cd.get("raw_graph")
    if not raw:
        raise HTTPException(status_code=404, detail=f"No road graph for '{city}'")

    body = await request.json()
    task_id = str(__import__('uuid').uuid4())[:8]

    _set_task(task_id, {
        "status": "running", "progress": 0,
        "message": "Starting...", "record_count": 0,
    })

    async def run_generation():
        from simulation_generator import RoadGraph, SimulationConfig, SimulationGenerator

        def progress_cb(pct, msg):
            _set_task(task_id, {
                "status": "running", "progress": pct,
                "message": msg, "record_count": 0,
            })

        try:
            graph = RoadGraph(raw["roads_dir"])

            city_config = CITIES[city]
            config = SimulationConfig(
                city=city,
                stations=body.get('stations', []),
                duration_days=body.get('duration_days', 7),
                speed_kmh=body.get('speed_kmh', 40.0),
                hourly_scale=body.get('hourly_scale', 1.0),
                unit_id_offset=city_config.get('unit_id_offset', 100),
                start_date=body.get('start_date', '2025-01-01 00:00:00'),
            )

            generator = SimulationGenerator(graph, config, progress_callback=progress_cb)

            def blocking_work():
                generator.generate()
                return generator.insert_into_db(
                    db_host=os.getenv("DB_HOST", os.getenv("POSTGRES_HOST", "postgres")),
                    db_name=os.getenv("DB_NAME", os.getenv("POSTGRES_DB", "ems")),
                    db_user=os.getenv("DB_USER", os.getenv("POSTGRES_USER", "postgres")),
                    db_password=os.getenv("DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "postgres")),
                )

            count = await asyncio.to_thread(blocking_work)

            # Update coverage_threshold_sec in DB if provided
            cov_threshold = body.get('coverage_threshold_sec')
            if cov_threshold:
                try:
                    import psycopg2
                    conn = psycopg2.connect(
                        host=os.getenv("DB_HOST", "postgres"),
                        database=os.getenv("DB_NAME", "ems"),
                        user=os.getenv("DB_USER", "postgres"),
                        password=os.getenv("DB_PASSWORD", "postgres"),
                    )
                    cur = conn.cursor()
                    cur.execute("UPDATE cities SET coverage_threshold_sec = %s WHERE slug = %s",
                                (int(cov_threshold), city))
                    conn.commit()
                    cur.close()
                    conn.close()
                    # Update in-memory config
                    if city in CITIES:
                        CITIES[city]['coverage_threshold_sec'] = int(cov_threshold)
                except Exception as e:
                    print(f"[gen] Failed to update coverage threshold: {e}")

            _set_task(task_id, {
                "status": "complete", "progress": 100,
                "message": f"Done! {count} records inserted",
                "record_count": count,
            })
        except Exception as e:
            _set_task(task_id, {
                "status": "error", "progress": 0,
                "message": str(e), "record_count": 0,
            })
            import traceback
            traceback.print_exc()

    asyncio.create_task(run_generation())
    return {"task_id": task_id}


@app.get("/api/{city}/admin/simulation/progress/{task_id}")
async def get_simulation_progress(city: str, task_id: str):
    """Get progress of a running simulation generation task"""
    task = _get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return task


@app.post("/api/{city}/admin/simulation/start-streaming")
async def start_streaming(city: str):
    """Create signals config and start streaming for a city."""
    if city not in CITIES:
        reload_cities()
    if city not in CITIES:
        raise HTTPException(status_code=404, detail=f"City '{city}' not found")

    city_config = CITIES[city]
    offset = city_config.get("unit_id_offset", 100)

    # Get vehicle unit IDs (contiguous range from offset+1, skip intervention IDs)
    def get_units():
        conn = _get_db_connection()
        cur = conn.cursor()
        # Vehicle units are contiguous from offset+1; find the max contiguous ID
        cur.execute(
            "SELECT DISTINCT unit FROM data_id WHERE unit >= %s AND unit < %s ORDER BY unit",
            (offset + 1, offset + 100)
        )
        all_units = [r[0] for r in cur.fetchall()]
        # Keep only the contiguous block starting at offset+1
        units = []
        for u in all_units:
            if u == offset + 1 + len(units):
                units.append(u)
            else:
                break
        cur.close()
        conn.close()
        return units

    units = await asyncio.to_thread(get_units)
    if not units:
        raise HTTPException(status_code=400, detail="No simulation data found. Generate data first.")

    unit_filter = "(" + ", ".join(str(u) for u in units) + ")"

    # Write signals config file
    import os
    config_path = f"/app/preprocessing/config_{city}.py"
    service_id = offset // 100  # derive a unique service ID
    config_content = f"""import os

# App setup
SERVICE = {service_id}  # {city_config['name']}
SPEED_UP_N_TIMES = 100
DEFAULT_DATETIME = '2025-01-01 00:00:00'
PRINT_MESSAGES = True
PRINT_MESSAGES_FULL = True

# Units
UNIT_FILTER = '{unit_filter}'

# Database
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME', 'ems')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_USER_PW = os.getenv('DB_PASSWORD', '')

# Kafka
KAFKA_HOSTS = os.getenv('KAFKA_HOSTS', 'localhost:9092')
KAFKA_TOPIC_MAIN_STREAM = '{city}_gps_status'
KAFKA_TOPIC_ROUTE_REQUEST = '{city}_route_request'
KAFKA_TOPIC_COVERAGE_REQUEST = '{city}_coverage_request'
KAFKA_CONSUMER_GROUP = '{city}_group'

# Redis
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
REDIS_CHANNEL = '{city}_gps_status'
"""
    # Also write to signals directory for docker-compose
    signals_config = os.path.join("/app/preprocessing", "..", "signals", f"config_{city}.py")
    # Write to preprocessing output (mounted rw)
    with open(config_path, "w") as f:
        f.write(config_content)

    return {"status": "ok", "city": city, "units": len(units),
            "message": f"Config created for {len(units)} units. "
                       f"Streaming will begin when signals-{city} service starts."}


# ============================================================================
# City Management API
# ============================================================================

@app.get("/api/admin/cities/pbf-cache")
async def check_pbf_cache(country_code: str = ""):
    """Check if a country PBF is already cached."""
    from setup_city import get_country_cache_info
    info = get_country_cache_info(country_code)
    if info is None:
        return {"supported": False}
    info["supported"] = True
    return info


@app.get("/api/admin/cities/search")
async def search_cities(q: str = "", limit: int = 10):
    """Search world cities for autocomplete"""
    if len(q) < 2:
        return []

    def query():
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT geonameid, name, country_code, latitude, longitude, population
            FROM world_cities
            WHERE asciiname ILIKE %s
            ORDER BY population DESC
            LIMIT %s
        """, (q + '%', limit))
        columns = [d[0] for d in cur.description]
        results = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return results

    results = await asyncio.to_thread(query)
    return results


@app.post("/api/admin/cities/add")
async def add_city(request: Request):
    """Add a new city and start preprocessing pipeline"""
    body = await request.json()
    name = body['name']
    latitude = float(body['latitude'])
    longitude = float(body['longitude'])
    country_code = body.get('country_code', '')
    force_download = body.get('force_download', False)

    # Generate slug
    import re
    import unicodedata
    ascii_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    slug = re.sub(r'[^a-z0-9]+', '-', ascii_name.lower()).strip('-')

    def db_insert():
        conn = _get_db_connection()
        cur = conn.cursor()

        # Check if slug already exists
        cur.execute("SELECT slug, status FROM cities WHERE slug = %s", (slug,))
        existing = cur.fetchone()
        if existing:
            status = existing[1]
            cur.close()
            conn.close()
            return None, {"status": status}

        # Auto-compute unit_id_offset
        cur.execute("SELECT COALESCE(MAX(unit_id_offset), 0) + 100 FROM cities")
        offset = cur.fetchone()[0]

        # Compute zoom based on typical city size
        zoom = 13

        cur.execute("""
            INSERT INTO cities (slug, name, description, center_lat, center_lon, zoom,
                building_tiles, road_tiles, service, unit_id_offset, status, country_code)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'processing', %s)
        """, (
            slug, name, f"{name} emergency services coverage area",
            latitude, longitude, zoom,
            slug + '_buildings', slug + '_roads',
            slug, offset, country_code,
        ))
        conn.commit()
        cur.close()
        conn.close()
        return slug, offset

    result = await asyncio.to_thread(db_insert)
    if result[0] is None:
        info = result[1]
        raise HTTPException(status_code=409, detail={"slug": slug, "status": info["status"]})

    slug, offset = result
    task_id = str(__import__('uuid').uuid4())[:8]

    _set_task(f"city_{task_id}", {
        "status": "running", "progress": 0,
        "message": "Starting city setup...", "slug": slug,
    })

    async def run_setup():
        try:
            import subprocess
            import sys

            # Docker: /app/preprocessing (mounted), Local dev: relative path
            preprocessing_dir = "/app/preprocessing" if Path("/app/preprocessing").exists() else str(Path(__file__).parent.parent.parent.parent / "preprocessing")

            def blocking_setup():
                from setup_city import setup_city as run_pipeline
                return run_pipeline(
                    slug=slug,
                    lat=latitude,
                    lon=longitude,
                    preprocessing_dir=preprocessing_dir,
                    tiles_dir=str(Path(__file__).parent / "static" / "data" / "tiles"),
                    db_host=os.getenv("DB_HOST", os.getenv("POSTGRES_HOST", "postgres")),
                    db_name=os.getenv("DB_NAME", os.getenv("POSTGRES_DB", "ems")),
                    db_user=os.getenv("DB_USER", os.getenv("POSTGRES_USER", "postgres")),
                    db_password=os.getenv("DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "postgres")),
                    progress_callback=lambda pct, msg: _set_task(f"city_{task_id}", {
                        "status": "running", "progress": pct, "message": msg, "slug": slug,
                    }),
                    country_code=country_code,
                    force_download=force_download,
                )

            await asyncio.to_thread(blocking_setup)

            # Reload CITIES config
            reload_cities()
            # Also reload city data
            load_all_cities()

            _set_task(f"city_{task_id}", {
                "status": "complete", "progress": 100,
                "message": f"{name} is ready!", "slug": slug,
            })
        except Exception as e:
            # Update DB status to error
            try:
                conn = _get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE cities SET status = 'error' WHERE slug = %s", (slug,))
                conn.commit()
                cur.close()
                conn.close()
            except Exception:
                pass

            _set_task(f"city_{task_id}", {
                "status": "error", "progress": 0,
                "message": str(e), "slug": slug,
            })
            import traceback
            traceback.print_exc()

    asyncio.create_task(run_setup())
    return {"slug": slug, "task_id": task_id, "status": "processing"}


@app.get("/api/admin/cities/setup-progress/{task_id}")
async def get_city_setup_progress(task_id: str):
    """Get progress of city setup pipeline"""
    task = _get_task(f"city_{task_id}")
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return task


@app.delete("/api/admin/cities/{slug}")
async def delete_city(slug: str):
    """Remove a city"""
    if slug in ('paris',):  # Protect default city
        raise HTTPException(status_code=400, detail="Cannot delete default city")

    def db_delete():
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM cities WHERE slug = %s", (slug,))
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return deleted

    deleted = await asyncio.to_thread(db_delete)
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"City '{slug}' not found")

    reload_cities()
    return {"ok": True, "slug": slug}


# Legacy API endpoints (default city)
@app.get("/api/admin/segment/{osm_id}/buildings")
async def get_segment_buildings_legacy(osm_id: str):
    return await get_segment_buildings(DEFAULT_CITY, osm_id)

@app.get("/api/admin/building/{building_id}/segments")
async def get_building_segments_legacy(building_id: int):
    return await get_building_segments(DEFAULT_CITY, building_id)

@app.get("/api/admin/stats")
async def get_linkage_stats_legacy():
    return await get_linkage_stats(DEFAULT_CITY)

@app.get("/api/admin/segment/{osm_id}/geometry")
async def get_segment_geometry_legacy(osm_id: int):
    return await get_segment_geometry(DEFAULT_CITY, osm_id)

@app.get("/api/admin/building/{building_id}/geometry")
async def get_building_segments_geometry_legacy(building_id: int):
    return await get_building_segments_geometry(DEFAULT_CITY, building_id)


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5001,
        reload=True,
        log_level="info"
    )

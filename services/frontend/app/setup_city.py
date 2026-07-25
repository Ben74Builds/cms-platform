#!/usr/bin/env python3
"""
Automated city setup pipeline.

Downloads OSM data, extracts buildings and roads, generates tiles,
and updates the database. Runs as a background task from FastAPI.
"""

import os
import subprocess
import sys
import shutil
from pathlib import Path

import psycopg2


def setup_city(slug, lat, lon, preprocessing_dir, tiles_dir,
               db_host, db_name, db_user, db_password,
               bbox_radius_km=5.0, progress_callback=None,
               country_code=None, force_download=False):
    """
    Run the full preprocessing pipeline for a new city.

    Args:
        slug: City slug (e.g., 'lyon')
        lat, lon: City center coordinates
        preprocessing_dir: Path to services/preprocessing/
        tiles_dir: Path to frontend/app/static/data/tiles/
        bbox_radius_km: Bounding box radius in km
        progress_callback: function(progress_pct, message)
    """
    def report(pct, msg):
        print(f"[setup_city:{slug}] {pct}% - {msg}", file=sys.stderr)
        if progress_callback:
            progress_callback(pct, msg)

    preprocessing_dir = Path(preprocessing_dir)
    tiles_dir = Path(tiles_dir)
    output_dir = preprocessing_dir / "output" / slug
    output_dir.mkdir(parents=True, exist_ok=True)
    roads_dir = output_dir / "roads"
    roads_dir.mkdir(parents=True, exist_ok=True)

    # Compute bounding box
    # 1 degree latitude ~ 111 km, 1 degree longitude ~ 111 * cos(lat) km
    import math
    lat_offset = bbox_radius_km / 111.0
    lon_offset = bbox_radius_km / (111.0 * math.cos(math.radians(lat)))
    bbox = {
        'min_lat': lat - lat_offset,
        'max_lat': lat + lat_offset,
        'min_lon': lon - lon_offset,
        'max_lon': lon + lon_offset,
    }

    report(0, "Starting city setup...")

    # =========================================================================
    # Step 1: Download OSM PBF
    # =========================================================================
    report(2, "Downloading OSM data...")
    pbf_path = output_dir / f"{slug}.osm.pbf"

    if not pbf_path.exists() or not _pbf_has_buildings(pbf_path):
        if pbf_path.exists():
            pbf_path.unlink()  # Remove bad PBF

        extracted = False

        # Strategy 1: Try Geofabrik country download + osmium extract
        report(3, "Downloading country PBF from Geofabrik...")
        extracted = _download_geofabrik_and_extract(
            country_code, bbox, pbf_path, report,
            force_download=force_download)

        # Strategy 2: Extract from existing local PBFs
        if not extracted:
            existing_pbfs = list((preprocessing_dir.parent / "backend" / "data" / "pbf").glob("*.osm.pbf"))
            osmium_path = shutil.which("osmium")
            if osmium_path and existing_pbfs:
                for region_pbf in existing_pbfs:
                    report(3, f"Extracting from {region_pbf.name}...")
                    try:
                        bbox_str = f"{bbox['min_lon']},{bbox['min_lat']},{bbox['max_lon']},{bbox['max_lat']}"
                        result = subprocess.run(
                            [osmium_path, "extract", "-b", bbox_str,
                             "-s", "complete_ways",
                             str(region_pbf), "-o", str(pbf_path), "--overwrite"],
                            capture_output=True, text=True, timeout=300
                        )
                        if result.returncode == 0 and pbf_path.exists() and _pbf_has_buildings(pbf_path):
                            extracted = True
                            report(5, f"Extracted from {region_pbf.name}")
                            break
                        elif pbf_path.exists():
                            pbf_path.unlink()  # Remove if no buildings found
                    except (subprocess.TimeoutExpired, Exception) as e:
                        print(f"[setup_city:{slug}] osmium extract failed: {e}", file=sys.stderr)

        # Strategy 3: BBBike / Overpass fallback
        if not extracted:
            report(3, "Downloading from BBBike/Overpass...")
            downloaded = _download_pbf(slug, lat, lon, bbox, pbf_path)
            if not downloaded:
                _update_city_status(slug, "error", db_host, db_name, db_user, db_password)
                raise RuntimeError(f"Could not obtain PBF data for {slug}")

    report(8, "OSM data ready")

    # =========================================================================
    # Step 2: Extract buildings
    # =========================================================================
    report(10, "Extracting buildings...")
    buildings_geojson = output_dir / "buildings.geojson"
    _run_script(preprocessing_dir / "extract_buildings.py",
                [str(pbf_path), str(buildings_geojson)],
                report=report, base_pct=10, end_pct=25)
    report(25, "Buildings extracted")

    # =========================================================================
    # Step 3: Extract roads
    # =========================================================================
    report(28, "Extracting roads...")
    _run_script(preprocessing_dir / "extract_roads.py",
                [str(pbf_path), str(roads_dir)],
                report=report, base_pct=28, end_pct=40)
    report(40, "Roads extracted")

    # =========================================================================
    # Step 4: Link buildings to road segments
    # =========================================================================
    report(42, "Linking buildings to road segments...")
    mapping_json = output_dir / "building_segment_mapping.json"
    _run_script(preprocessing_dir / "link_buildings_to_segments.py",
                [str(buildings_geojson), str(roads_dir), str(mapping_json),
                 "--max-distance", "25"],
                report=report, base_pct=42, end_pct=55)
    report(55, "Buildings linked to segments")

    # =========================================================================
    # Step 5: Generate building tile GeoJSON
    # =========================================================================
    report(58, "Generating building tile data...")
    buildings_with_segments = output_dir / "buildings_with_segments.geojson"
    _run_script(preprocessing_dir / "generate_building_tiles.py",
                [str(buildings_geojson), str(mapping_json), str(buildings_with_segments)],
                report=report, base_pct=58, end_pct=65)
    report(65, "Building tile GeoJSON ready")

    # =========================================================================
    # Step 6: Generate road tile GeoJSON
    # =========================================================================
    report(68, "Generating road tile data...")
    roads_geojson = output_dir / "roads.geojson"
    _run_script(preprocessing_dir / "generate_road_tiles.py",
                [str(roads_dir), str(roads_geojson)],
                report=report, base_pct=68, end_pct=75)
    report(75, "Road tile GeoJSON ready")

    # =========================================================================
    # Step 7: Generate vector tiles with tippecanoe
    # =========================================================================
    tippecanoe = shutil.which("tippecanoe")
    if not tippecanoe:
        # Try common locations
        for path in ["/home/benjamin/.local/bin/tippecanoe", "/usr/local/bin/tippecanoe"]:
            if os.path.isfile(path):
                tippecanoe = path
                break

    if tippecanoe:
        # Building tiles
        report(78, "Generating building vector tiles...")
        building_tiles_dir = tiles_dir / f"{slug}_buildings"
        if building_tiles_dir.exists():
            shutil.rmtree(building_tiles_dir)
        subprocess.run([
            tippecanoe, "-e", str(building_tiles_dir),
            "-Z12", "-z17", "--no-tile-compression",
            "--no-feature-limit", "--no-tile-size-limit",
            "--no-line-simplification", "--no-tiny-polygon-reduction",
            "--layer=buildings", "--force",
            str(buildings_with_segments)
        ], capture_output=True, text=True, timeout=600)
        report(88, "Building tiles generated")

        # Road tiles
        report(89, "Generating road vector tiles...")
        road_tiles_dir = tiles_dir / f"{slug}_roads"
        if road_tiles_dir.exists():
            shutil.rmtree(road_tiles_dir)
        subprocess.run([
            tippecanoe, "-e", str(road_tiles_dir),
            "-Z12", "-z17", "--no-tile-compression",
            "--layer=roads", "--force",
            str(roads_geojson)
        ], capture_output=True, text=True, timeout=600)
        report(95, "Road tiles generated")
    else:
        report(95, "Tippecanoe not found — skipping tile generation")

    # =========================================================================
    # Step 8: Update database
    # =========================================================================
    report(97, "Updating database...")
    _update_city_status(slug, "ready", db_host, db_name, db_user, db_password)
    report(100, f"{slug} is ready!")

    return True


def _run_script(script_path, args, report=None, base_pct=0, end_pct=0):
    """Run a Python preprocessing script with live progress output."""
    cmd = [sys.executable, "-u", str(script_path)] + args
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )
    last_line = ""
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            last_line = line
            print(f"[setup_city] {script_path.name}: {line}", file=sys.stderr)
            if report and base_pct and end_pct:
                report(base_pct, f"{script_path.stem}: {line}")
    proc.wait()
    if proc.returncode != 0:
        print(f"[setup_city] Script failed: {script_path.name}", file=sys.stderr)
        raise RuntimeError(f"{script_path.name} failed: {last_line}")
    return last_line


def _pbf_has_buildings(pbf_path, min_buildings=10):
    """Check if a PBF file contains building data with resolvable nodes."""
    try:
        import osmium

        class BuildingChecker(osmium.SimpleHandler):
            def __init__(self):
                super().__init__()
                self.nodes = set()
                self.building_ways = 0
                self.resolved = 0

            def node(self, n):
                self.nodes.add(n.id)

            def way(self, w):
                if 'building' in w.tags:
                    self.building_ways += 1
                    refs = [n.ref for n in w.nodes]
                    if all(r in self.nodes for r in refs):
                        self.resolved += 1

        checker = BuildingChecker()
        checker.apply_file(str(pbf_path))
        return checker.resolved >= min_buildings
    except Exception:
        return False


# Geofabrik country code to URL path mapping
_GEOFABRIK_PATHS = {
    "AD": "europe/andorra", "AL": "europe/albania", "AT": "europe/austria",
    "BA": "europe/bosnia-herzegovina", "BE": "europe/belgium", "BG": "europe/bulgaria",
    "CH": "europe/switzerland", "CY": "europe/cyprus", "CZ": "europe/czech-republic",
    "DE": "europe/germany", "DK": "europe/denmark", "EE": "europe/estonia",
    "ES": "europe/spain", "FI": "europe/finland", "FR": "europe/france",
    "GB": "europe/great-britain", "GR": "europe/greece", "HR": "europe/croatia",
    "HU": "europe/hungary", "IE": "europe/ireland-and-northern-ireland",
    "IS": "europe/iceland", "IT": "europe/italy", "LI": "europe/liechtenstein",
    "LT": "europe/lithuania", "LU": "europe/luxembourg", "LV": "europe/latvia",
    "MC": "europe/monaco", "MD": "europe/moldova", "ME": "europe/montenegro",
    "MK": "europe/macedonia", "MT": "europe/malta", "NL": "europe/netherlands",
    "NO": "europe/norway", "PL": "europe/poland", "PT": "europe/portugal",
    "RO": "europe/romania", "RS": "europe/serbia", "SE": "europe/sweden",
    "SI": "europe/slovenia", "SK": "europe/slovakia", "UA": "europe/ukraine",
    "XK": "europe/kosovo",
    "US": "north-america/us", "CA": "north-america/canada", "MX": "north-america/mexico",
    "BR": "south-america/brazil", "AR": "south-america/argentina",
    "AU": "australia-oceania/australia", "NZ": "australia-oceania/new-zealand",
    "JP": "asia/japan", "KR": "asia/south-korea", "SG": "asia/singapore",
    "IL": "asia/israel-and-palestine", "AE": "asia/gcc-states",
    "ZA": "africa/south-africa", "MA": "africa/morocco", "TN": "africa/tunisia",
}


def _get_pbf_cache_dir():
    """Return the persistent PBF cache directory."""
    cache_dir = Path(os.environ.get("PBF_CACHE_DIR", "/app/data/pbf_cache"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _country_pbf_cache_path(country_code):
    """Return the cache file path for a country PBF."""
    geofabrik_path = _GEOFABRIK_PATHS.get(country_code, "")
    if not geofabrik_path:
        return None
    # e.g. europe_france-latest.osm.pbf
    filename = geofabrik_path.replace("/", "_") + "-latest.osm.pbf"
    return _get_pbf_cache_dir() / filename


def get_country_cache_info(country_code):
    """Check if a cached country PBF exists and return its metadata."""
    if not country_code or country_code not in _GEOFABRIK_PATHS:
        return None
    cached_path = _country_pbf_cache_path(country_code)
    if cached_path and cached_path.exists():
        import time
        stat = cached_path.stat()
        age_seconds = time.time() - stat.st_mtime
        return {
            "exists": True,
            "path": str(cached_path),
            "size_mb": stat.st_size // (1024 * 1024),
            "age_hours": round(age_seconds / 3600, 1),
            "age_days": round(age_seconds / 86400, 1),
            "geofabrik_path": _GEOFABRIK_PATHS[country_code],
        }
    return {"exists": False, "geofabrik_path": _GEOFABRIK_PATHS.get(country_code, "")}


def _download_geofabrik_and_extract(country_code, bbox, output_path, report,
                                     force_download=False):
    """Download country PBF from Geofabrik (with persistent cache) and extract the city area."""
    if not country_code or country_code not in _GEOFABRIK_PATHS:
        return False

    import httpx
    geofabrik_path = _GEOFABRIK_PATHS[country_code]
    url = f"https://download.geofabrik.de/{geofabrik_path}-latest.osm.pbf"
    country_pbf = _country_pbf_cache_path(country_code)

    try:
        if force_download and country_pbf.exists():
            report(3, f"Removing cached {geofabrik_path} (re-download requested)...")
            country_pbf.unlink()

        if not country_pbf.exists():
            report(4, f"Downloading {geofabrik_path}...")
            print(f"[setup_city] Downloading {url}", file=sys.stderr)
            # Download to a temp file first to avoid partial cache files
            tmp_pbf = country_pbf.with_suffix('.osm.pbf.tmp')
            with httpx.Client(timeout=300, follow_redirects=True) as client:
                with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        print(f"[setup_city] Geofabrik returned {resp.status_code}", file=sys.stderr)
                        return False
                    total = int(resp.headers.get("content-length", 0))
                    downloaded = 0
                    with open(str(tmp_pbf), "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=1024*1024):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                dl_pct = downloaded * 100 // total
                                dl_mb = downloaded // (1024 * 1024)
                                total_mb = total // (1024 * 1024)
                                report(4, f"Downloading {geofabrik_path}... {dl_mb}/{total_mb} MB ({dl_pct}%)")
                            else:
                                dl_mb = downloaded // (1024 * 1024)
                                report(4, f"Downloading {geofabrik_path}... {dl_mb} MB")
            # Rename to final path only after complete download
            tmp_pbf.rename(country_pbf)
            report(5, f"Downloaded {geofabrik_path} (cached for future use)")
        else:
            import time
            age_hours = round((time.time() - country_pbf.stat().st_mtime) / 3600, 1)
            size_mb = country_pbf.stat().st_size // (1024 * 1024)
            report(5, f"Using cached {geofabrik_path} ({size_mb} MB, {age_hours}h old)")

        # Extract city area with complete_ways
        osmium_path = shutil.which("osmium")
        if not osmium_path:
            import shutil as sh
            sh.copy2(str(country_pbf), str(output_path))
            return True

        bbox_str = f"{bbox['min_lon']},{bbox['min_lat']},{bbox['max_lon']},{bbox['max_lat']}"
        report(6, "Extracting city area...")
        result = subprocess.run(
            [osmium_path, "extract", "-b", bbox_str,
             "-s", "complete_ways",
             str(country_pbf), "-o", str(output_path), "--overwrite"],
            capture_output=True, text=True, timeout=300
        )
        # NOTE: Country PBF is kept in cache for reuse by other cities

        if result.returncode == 0 and output_path.exists() and _pbf_has_buildings(output_path):
            report(7, "City PBF ready")
            return True
        else:
            print(f"[setup_city] Geofabrik extract has no buildings", file=sys.stderr)
            output_path.unlink(missing_ok=True)
            return False

    except Exception as e:
        print(f"[setup_city] Geofabrik download failed: {e}", file=sys.stderr)
        # Only clean up the temp file, not the cache
        tmp_pbf = country_pbf.with_suffix('.osm.pbf.tmp')
        tmp_pbf.unlink(missing_ok=True)
        return False


def _download_pbf(slug, lat, lon, bbox, output_path):
    """Download OSM PBF for a city area."""
    import httpx

    # Try BBBike pre-made extract
    bbbike_url = f"https://download.bbbike.org/osm/bbbike/{slug.title()}/{slug.title()}.osm.pbf"
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            resp = client.head(bbbike_url)
            if resp.status_code == 200:
                print(f"[setup_city] Downloading from BBBike: {bbbike_url}", file=sys.stderr)
                resp = client.get(bbbike_url)
                if resp.status_code == 200:
                    output_path.write_bytes(resp.content)
                    return True
    except Exception as e:
        print(f"[setup_city] BBBike download failed: {e}", file=sys.stderr)

    # Fallback: use Overpass API to get OSM XML, then convert
    # This works for small/medium cities but has size limits
    bbox_str = f"{bbox['min_lat']},{bbox['min_lon']},{bbox['max_lat']},{bbox['max_lon']}"
    overpass_query = f"""
    [out:xml][timeout:180][bbox:{bbox_str}];
    (
      way["building"];
      way["highway"];
      node(w);
    );
    out body;
    """

    overpass_urls = [
        "https://overpass-api.de/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]

    osm_xml_path = output_path.with_suffix('.osm')
    for url in overpass_urls:
        try:
            print(f"[setup_city] Downloading via Overpass: {url}", file=sys.stderr)
            with httpx.Client(timeout=200) as client:
                resp = client.post(url, data={"data": overpass_query})
                if resp.status_code == 200 and len(resp.content) > 1000:
                    osm_xml_path.write_bytes(resp.content)
                    # Convert to PBF if osmium available
                    osmium = shutil.which("osmium")
                    if osmium:
                        subprocess.run(
                            [osmium, "cat", str(osm_xml_path), "-o", str(output_path), "--overwrite"],
                            capture_output=True, timeout=120
                        )
                        osm_xml_path.unlink(missing_ok=True)
                    else:
                        # Use XML directly — rename
                        output_path = osm_xml_path
                    return True
        except Exception as e:
            print(f"[setup_city] Overpass failed ({url}): {e}", file=sys.stderr)

    return False


def _update_city_status(slug, status, db_host, db_name, db_user, db_password):
    """Update city status in database."""
    conn = psycopg2.connect(
        host=db_host, database=db_name,
        user=db_user, password=db_password
    )
    cur = conn.cursor()
    cur.execute("UPDATE cities SET status = %s WHERE slug = %s", (status, slug))
    conn.commit()
    cur.close()
    conn.close()

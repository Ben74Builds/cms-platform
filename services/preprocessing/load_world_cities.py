#!/usr/bin/env python3
"""
Load GeoNames cities500 data into PostgreSQL world_cities table.

Downloads cities500.zip from GeoNames (~10MB, ~185K cities with pop > 500),
parses the TSV, and bulk-inserts into the world_cities table.

Usage:
    python load_world_cities.py [--db-host HOST] [--db-name NAME] [--db-user USER] [--db-password PW]
"""

import argparse
import io
import os
import sys
import zipfile
from urllib.request import urlopen

import psycopg2

GEONAMES_URL = "https://download.geonames.org/export/dump/cities500.zip"

# GeoNames cities500.txt TSV columns (19 total)
# 0: geonameid, 1: name, 2: asciiname, 3: alternatenames,
# 4: latitude, 5: longitude, 6: feature_class, 7: feature_code,
# 8: country_code, 9: cc2, 10: admin1_code, 11: admin2_code,
# 12: admin3_code, 13: admin4_code, 14: population, 15: elevation,
# 16: dem, 17: timezone, 18: modification_date


def download_cities500():
    """Download and extract cities500.txt from GeoNames."""
    print(f"Downloading {GEONAMES_URL}...", file=sys.stderr)
    response = urlopen(GEONAMES_URL)
    data = response.read()
    print(f"  Downloaded {len(data) / 1024 / 1024:.1f} MB", file=sys.stderr)

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        with zf.open("cities500.txt") as f:
            content = f.read().decode("utf-8")

    lines = content.strip().split("\n")
    print(f"  Parsed {len(lines)} cities", file=sys.stderr)
    return lines


def load_into_db(lines, db_host, db_name, db_user, db_password):
    """Bulk insert cities into world_cities table."""
    conn = psycopg2.connect(
        host=db_host, database=db_name,
        user=db_user, password=db_password
    )
    cur = conn.cursor()

    # Check if table exists and has data
    cur.execute("SELECT COUNT(*) FROM world_cities")
    existing = cur.fetchone()[0]
    if existing > 0:
        print(f"  world_cities already has {existing} rows, clearing...", file=sys.stderr)
        cur.execute("TRUNCATE world_cities")
        conn.commit()

    # Use COPY for fast bulk insert
    buf = io.StringIO()
    for line in lines:
        cols = line.split("\t")
        if len(cols) < 19:
            continue
        geonameid = cols[0]
        name = cols[1].replace("\t", " ").replace("\\", "\\\\")
        asciiname = cols[2].replace("\t", " ").replace("\\", "\\\\")
        country_code = cols[8][:2] if cols[8] else ""
        latitude = cols[4]
        longitude = cols[5]
        population = cols[14] if cols[14] else "0"
        timezone = cols[17]

        buf.write(f"{geonameid}\t{name}\t{asciiname}\t{country_code}\t{latitude}\t{longitude}\t{population}\t{timezone}\n")

    buf.seek(0)
    cur.copy_from(buf, "world_cities", columns=(
        "geonameid", "name", "asciiname", "country_code",
        "latitude", "longitude", "population", "timezone"
    ))
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM world_cities")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()

    print(f"  Loaded {total} cities into world_cities", file=sys.stderr)
    return total


def main():
    parser = argparse.ArgumentParser(description="Load GeoNames cities500 into PostgreSQL")
    parser.add_argument("--db-host", default=os.getenv("DB_HOST", "localhost"))
    parser.add_argument("--db-name", default=os.getenv("DB_NAME", "ems"))
    parser.add_argument("--db-user", default=os.getenv("DB_USER", "postgres"))
    parser.add_argument("--db-password", default=os.getenv("DB_PASSWORD", "postgres"))
    args = parser.parse_args()

    lines = download_cities500()
    total = load_into_db(lines, args.db_host, args.db_name, args.db_user, args.db_password)
    print(f"Done! {total} world cities loaded.", file=sys.stderr)


if __name__ == "__main__":
    main()

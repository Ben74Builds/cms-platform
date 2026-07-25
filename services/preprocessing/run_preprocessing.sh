#!/bin/bash
# Building Coverage Preprocessing Pipeline
#
# This script runs the complete preprocessing pipeline:
# 1. Extract buildings from OSM PBF
# 2. Link buildings to road segments
# 3. Generate GeoJSON with segment IDs
# 4. Generate vector tiles with tippecanoe
#
# Prerequisites:
#   - Python 3 with packages: osmium, shapely, rtree, geopandas, numpy
#   - tippecanoe installed
#
# Usage:
#   ./run_preprocessing.sh [pbf_file]
#   Default pbf_file: ../backend/data/pbf/paris-latest.osm.pbf

set -e  # Exit on error

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PBF_FILE="${1:-$SCRIPT_DIR/../backend/data/pbf/paris-latest.osm.pbf}"
# Graph data directory - CSV files may be in data/ with 'backup' prefix or in data/backup/paris/
GRAPH_DATA_DIR="$SCRIPT_DIR/../backend/data"
OUTPUT_DIR="$SCRIPT_DIR/output"
TILES_DIR="$SCRIPT_DIR/../frontend/app/static/data/tiles/buildings"
BACKEND_DATA_DIR="$SCRIPT_DIR/../backend/data/backup/paris"

# Output files
BUILDINGS_GEOJSON="$OUTPUT_DIR/buildings.geojson"
MAPPING_JSON="$OUTPUT_DIR/building_segment_mapping.json"
BUILDINGS_WITH_SEGMENTS="$OUTPUT_DIR/buildings_with_segments.geojson"

echo "=== Building Coverage Preprocessing Pipeline ==="
echo ""
echo "Configuration:"
echo "  PBF file: $PBF_FILE"
echo "  Graph data: $GRAPH_DATA_DIR"
echo "  Output dir: $OUTPUT_DIR"
echo "  Tiles dir: $TILES_DIR"
echo ""

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Check if tippecanoe is available
TIPPECANOE_CMD=""
if command -v tippecanoe &> /dev/null; then
    TIPPECANOE_CMD="tippecanoe"
elif [ -x "$SCRIPT_DIR/../frontend/lib/tippecanoe/tippecanoe" ]; then
    TIPPECANOE_CMD="$SCRIPT_DIR/../frontend/lib/tippecanoe/tippecanoe"
else
    echo "Warning: tippecanoe not found. Tiles will not be generated."
    echo "You can build tippecanoe from: $SCRIPT_DIR/../frontend/lib/tippecanoe"
fi

# Step 1: Extract buildings from OSM PBF
echo "=== Step 1: Extract buildings from OSM PBF ==="
python3 "$SCRIPT_DIR/extract_buildings.py" "$PBF_FILE" "$BUILDINGS_GEOJSON"
echo ""

# Step 2: Link buildings to road segments
echo "=== Step 2: Link buildings to road segments ==="
python3 "$SCRIPT_DIR/link_buildings_to_segments.py" \
    "$BUILDINGS_GEOJSON" \
    "$GRAPH_DATA_DIR" \
    "$MAPPING_JSON"
echo ""

# Step 3: Generate GeoJSON with segment IDs
echo "=== Step 3: Generate GeoJSON with segment IDs ==="
python3 "$SCRIPT_DIR/generate_building_tiles.py" \
    "$BUILDINGS_GEOJSON" \
    "$MAPPING_JSON" \
    "$BUILDINGS_WITH_SEGMENTS"
echo ""

# Step 4: Copy mapping to backend data directory
echo "=== Step 4: Copy mapping to backend ==="
cp "$MAPPING_JSON" "$BACKEND_DATA_DIR/building_segment_mapping.json"
echo "Copied to: $BACKEND_DATA_DIR/building_segment_mapping.json"
echo ""

# Step 5: Generate vector tiles
echo "=== Step 5: Generate vector tiles ==="
if [ -n "$TIPPECANOE_CMD" ]; then
    rm -rf "$TILES_DIR"
    "$TIPPECANOE_CMD" \
        -e "$TILES_DIR" \
        -Z12 -z17 \
        --no-tile-compression \
        --layer=buildings \
        "$BUILDINGS_WITH_SEGMENTS"
    echo "Tiles generated at: $TILES_DIR"
else
    echo "Skipping tile generation (tippecanoe not available)"
    echo "Run manually:"
    echo "  tippecanoe -e $TILES_DIR -Z12 -z17 \\"
    echo "      --no-tile-compression --layer=buildings \\"
    echo "      $BUILDINGS_WITH_SEGMENTS"
fi
echo ""

echo "=== Pipeline Complete ==="
echo ""
echo "Output files:"
echo "  Buildings GeoJSON: $BUILDINGS_GEOJSON"
echo "  Segment mapping: $MAPPING_JSON"
echo "  Buildings with segments: $BUILDINGS_WITH_SEGMENTS"
echo "  Backend mapping: $BACKEND_DATA_DIR/building_segment_mapping.json"
if [ -n "$TIPPECANOE_CMD" ]; then
    echo "  Vector tiles: $TILES_DIR"
fi

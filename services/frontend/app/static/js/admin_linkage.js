/**
 * Admin Linkage Inspector
 * Lightweight map for debugging building-to-road-segment linkages.
 * Road segments are first-class: always visible, clickable.
 * Click a segment → see all linked buildings highlighted.
 * Click a building → see its linked segment(s) highlighted.
 */

// ============================================================================
// Constants
// ============================================================================

// City-aware tile URLs and center (CITY_CONFIG and CITY_SLUG injected by template)
const _city = typeof CITY_CONFIG !== 'undefined' ? CITY_CONFIG : {};
const _citySlug = typeof CITY_SLUG !== 'undefined' ? CITY_SLUG : 'paris';
const BUILDING_TILE_URL = location.origin + '/static/data/tiles/' + (_city.building_tiles || 'buildings') + '/{z}/{x}/{y}.pbf';
const ROAD_TILE_URL = location.origin + '/static/data/tiles/' + (_city.road_tiles || 'roads') + '/{z}/{x}/{y}.pbf';
const MAP_STYLE_URL = '/static/styles/maplibre_styles.json';
const PARIS_CENTER = _city.center || [2.333333, 48.866667];
const INITIAL_ZOOM = (_city.zoom || 12) + 3;
const API_PREFIX = '/api/' + _citySlug;

const COLORS = {
    // Buildings
    buildingLinked: '#2196F3',      // blue
    buildingUnlinked: '#FF5722',    // red-orange
    buildingSelected: '#FFD600',    // yellow
    buildingHighlighted: '#00E676', // green (linked to selected segment)
    // Roads
    road: '#b0b0b0',                 // light grey, visible over buildings
    roadSelected: '#FF6D00',        // orange (selected segment)
    roadHighlighted: '#FF6D00',     // orange (linked to selected building)
};

// ============================================================================
// Helpers
// ============================================================================

function hasSegment(segId) {
    return segId && segId !== 0 && segId !== '0';
}

// ============================================================================
// State
// ============================================================================

let map = null;
let selectedBuildingId = null;
let selectedSegmentOsmId = null;
let selectionMode = null; // 'building' or 'segment'
let statsDebounceTimer = null;
let bufferEnabled = true;
let bufferDistanceMeters = 50;

// ============================================================================
// Map Initialization
// ============================================================================

async function initMap() {
    const resp = await fetch(MAP_STYLE_URL);
    const style = await resp.json();

    // Configure building tile source
    style.sources.composite.tiles = [BUILDING_TILE_URL];
    style.sources.composite.minzoom = 12;
    style.sources.composite.maxzoom = 17;

    // Brighten the base map
    const osmLayer = style.layers.find(l => l.id === 'osm-base');
    if (osmLayer) {
        osmLayer.paint['raster-brightness-max'] = 0.85;
        osmLayer.paint['raster-brightness-min'] = 0.15;
        osmLayer.paint['raster-saturation'] = -0.6;
    }

    map = new maplibregl.Map({
        container: 'map',
        style: style,
        center: PARIS_CENTER,
        zoom: INITIAL_ZOOM,
        minZoom: 12,
        maxZoom: 18,
    });

    map.addControl(new maplibregl.NavigationControl(), 'bottom-right');

    map.on('load', () => {
        // Add road tile source after map is loaded
        map.addSource('roads', {
            type: 'vector',
            tiles: [ROAD_TILE_URL],
            minzoom: 12,
            maxzoom: 17,
        });
        console.log('[Admin] Map loaded. Sources:', Object.keys(map.getStyle().sources));
        addBuildingLayers();    // bottom: building polygons
        addBufferLayers();      // buffer zone (below roads, above buildings)
        addRoadLayers();        // middle: road segments on top of buildings
        addSelectionLayers();   // top: highlights and selections
        setupClickHandlers();
        setupHover();
        setupBufferControls();
        updateViewportStats();
        loadGlobalStats();
        console.log('[Admin] Layers:', map.getStyle().layers.map(l => l.id));
    });

    map.on('moveend', () => {
        debounceUpdateStats();
    });

    map.on('sourcedata', (e) => {
        if ((e.sourceId === 'composite' || e.sourceId === 'roads') && e.isSourceLoaded) {
            debounceUpdateStats();
        }
    });
}

// ============================================================================
// Road Layers (vector tiles — always visible)
// ============================================================================

function addRoadLayers() {
    // Road casing (dark outline for visibility)
    map.addLayer({
        id: 'roads-casing',
        type: 'line',
        source: 'roads',
        'source-layer': 'roads',
        paint: {
            'line-color': '#000',
            'line-width': ['interpolate', ['linear'], ['zoom'], 12, 2.5, 17, 6],
            'line-opacity': 0.3,
        },
    });

    // Base road segments — always visible
    map.addLayer({
        id: 'roads-base',
        type: 'line',
        source: 'roads',
        'source-layer': 'roads',
        paint: {
            'line-color': COLORS.road,
            'line-width': ['interpolate', ['linear'], ['zoom'], 12, 1.5, 17, 4],
            'line-opacity': 0.85,
        },
    });

    // Highlighted roads (linked to selected building)
    map.addLayer({
        id: 'roads-highlighted',
        type: 'line',
        source: 'roads',
        'source-layer': 'roads',
        paint: {
            'line-color': COLORS.roadHighlighted,
            'line-width': ['interpolate', ['linear'], ['zoom'], 12, 3, 17, 6],
            'line-opacity': 0.9,
        },
        filter: ['==', 'osm_id', -999], // matches nothing initially
    });

    // Selected road (clicked segment)
    map.addLayer({
        id: 'roads-selected',
        type: 'line',
        source: 'roads',
        'source-layer': 'roads',
        paint: {
            'line-color': COLORS.roadSelected,
            'line-width': ['interpolate', ['linear'], ['zoom'], 12, 4, 17, 8],
            'line-opacity': 1,
        },
        filter: ['==', 'osm_id', -999],
    });
}

// ============================================================================
// Building Layers
// ============================================================================

function addBuildingLayers() {
    // Main fill: colored by linkage status
    map.addLayer({
        id: 'buildings-fill',
        type: 'fill',
        source: 'composite',
        'source-layer': 'buildings',
        paint: {
            'fill-color': [
                'case',
                ['all', ['has', 'segment_osm_id'], ['!=', ['get', 'segment_osm_id'], 0]],
                COLORS.buildingLinked,
                COLORS.buildingUnlinked
            ],
            'fill-opacity': 0.4,
        },
        filter: ['==', '$type', 'Polygon'],
    });

    // Outlines
    map.addLayer({
        id: 'buildings-outline',
        type: 'line',
        source: 'composite',
        'source-layer': 'buildings',
        paint: {
            'line-color': '#555',
            'line-width': 0.5,
        },
        filter: ['==', '$type', 'Polygon'],
    });
}

// ============================================================================
// Selection/Highlight Layers (on top of everything)
// ============================================================================

function addSelectionLayers() {
    // Highlighted buildings (linked to selected segment)
    map.addLayer({
        id: 'buildings-highlighted',
        type: 'fill',
        source: 'composite',
        'source-layer': 'buildings',
        paint: {
            'fill-color': COLORS.buildingHighlighted,
            'fill-opacity': 0.75,
        },
        filter: ['==', 'segment_osm_id', -999],
    });

    // Highlighted building outlines
    map.addLayer({
        id: 'buildings-highlighted-outline',
        type: 'line',
        source: 'composite',
        'source-layer': 'buildings',
        paint: {
            'line-color': '#004400',
            'line-width': 2,
        },
        filter: ['==', 'segment_osm_id', -999],
    });

    // Selected building
    map.addLayer({
        id: 'buildings-selected',
        type: 'fill',
        source: 'composite',
        'source-layer': 'buildings',
        paint: {
            'fill-color': COLORS.buildingSelected,
            'fill-opacity': 0.85,
        },
        filter: ['==', 'building_id', -999],
    });

    // Selected building outline
    map.addLayer({
        id: 'buildings-selected-outline',
        type: 'line',
        source: 'composite',
        'source-layer': 'buildings',
        paint: {
            'line-color': '#333',
            'line-width': 2.5,
        },
        filter: ['==', 'building_id', -999],
    });
}

// ============================================================================
// Buffer Zone (linkage radius visualization)
// ============================================================================

const EMPTY_GEOJSON = { type: 'FeatureCollection', features: [] };

function addBufferLayers() {
    map.addSource('buffer-zone', {
        type: 'geojson',
        data: EMPTY_GEOJSON,
    });

    // Buffer fill
    map.addLayer({
        id: 'buffer-fill',
        type: 'fill',
        source: 'buffer-zone',
        paint: {
            'fill-color': '#FF6D00',
            'fill-opacity': 0.08,
        },
    });

    // Buffer outline (dashed)
    map.addLayer({
        id: 'buffer-outline',
        type: 'line',
        source: 'buffer-zone',
        paint: {
            'line-color': '#FF6D00',
            'line-width': 2,
            'line-opacity': 0.5,
            'line-dasharray': [4, 4],
        },
    });
}

function updateBuffer(segmentGeometry) {
    if (!bufferEnabled || !segmentGeometry) {
        map.getSource('buffer-zone').setData(EMPTY_GEOJSON);
        return;
    }

    const distKm = bufferDistanceMeters / 1000;
    const buffered = turf.buffer(segmentGeometry, distKm, { units: 'kilometers' });
    map.getSource('buffer-zone').setData(buffered);
}

function clearBuffer() {
    if (map.getSource('buffer-zone')) {
        map.getSource('buffer-zone').setData(EMPTY_GEOJSON);
    }
}

function setupBufferControls() {
    const toggle = document.getElementById('buffer-toggle');
    const slider = document.getElementById('buffer-distance');
    const valueLabel = document.getElementById('buffer-distance-value');

    toggle.addEventListener('change', () => {
        bufferEnabled = toggle.checked;
        if (!bufferEnabled) {
            clearBuffer();
        } else if (selectionMode === 'segment' && lastSelectedSegmentGeometry) {
            updateBuffer(lastSelectedSegmentGeometry);
        } else if (selectionMode === 'building' && lastSelectedBuildingSegmentGeometries) {
            updateBuffer(lastSelectedBuildingSegmentGeometries);
        }
    });

    slider.addEventListener('input', () => {
        bufferDistanceMeters = parseInt(slider.value);
        valueLabel.textContent = bufferDistanceMeters + 'm';
        if (bufferEnabled) {
            if (selectionMode === 'segment' && lastSelectedSegmentGeometry) {
                updateBuffer(lastSelectedSegmentGeometry);
            } else if (selectionMode === 'building' && lastSelectedBuildingSegmentGeometries) {
                updateBuffer(lastSelectedBuildingSegmentGeometries);
            }
        }
    });
}

// Store geometry of selected segment(s) so buffer can be redrawn on slider change
let lastSelectedSegmentGeometry = null;
let lastSelectedBuildingSegmentGeometries = null;

function getSegmentGeometryFromTiles(osmId) {
    // Collect all line features for this segment from rendered tiles
    const features = map.queryRenderedFeatures({ layers: ['roads-base'] });
    const lines = [];
    for (const f of features) {
        if (f.properties.osm_id === osmId) {
            lines.push(f);
        }
    }
    if (lines.length === 0) return null;
    if (lines.length === 1) return lines[0].geometry;
    // Merge into a MultiLineString
    return {
        type: 'MultiLineString',
        coordinates: lines.map(f =>
            f.geometry.type === 'MultiLineString'
                ? f.geometry.coordinates
                : [f.geometry.coordinates]
        ).flat()
    };
}

function getMultiSegmentGeometry(osmIds) {
    const allCoords = [];
    const features = map.queryRenderedFeatures({ layers: ['roads-base'] });
    const idSet = new Set(osmIds);
    for (const f of features) {
        if (idSet.has(f.properties.osm_id)) {
            if (f.geometry.type === 'MultiLineString') {
                allCoords.push(...f.geometry.coordinates);
            } else {
                allCoords.push(f.geometry.coordinates);
            }
        }
    }
    if (allCoords.length === 0) return null;
    return { type: 'MultiLineString', coordinates: allCoords };
}

// ============================================================================
// Click Handlers
// ============================================================================

function setupClickHandlers() {
    // Click on a road segment
    map.on('click', 'roads-base', (e) => {
        if (!e.features || e.features.length === 0) return;
        e.preventDefault();

        const feature = e.features[0];
        const osmId = feature.properties.osm_id;
        selectSegment(osmId, feature.properties);
    });

    // Click on a building
    map.on('click', 'buildings-fill', (e) => {
        if (e.defaultPrevented) return; // road click took priority
        if (!e.features || e.features.length === 0) return;

        const feature = e.features[0];
        const props = feature.properties;
        selectBuilding(props.building_id, props.segment_osm_id, props);
    });

    // Click on empty area to clear
    map.on('click', (e) => {
        if (e.defaultPrevented) return;
        const roadHit = map.queryRenderedFeatures(e.point, { layers: ['roads-base'] });
        const buildingHit = map.queryRenderedFeatures(e.point, { layers: ['buildings-fill'] });
        if (roadHit.length === 0 && buildingHit.length === 0) {
            clearSelection();
        }
    });

    // Escape to clear
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') clearSelection();
    });

    // Close button on info panel
    document.getElementById('info-close').addEventListener('click', clearSelection);

    // Search
    document.getElementById('search-btn').addEventListener('click', doSearch);
    document.getElementById('search-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') doSearch();
    });
}

// ============================================================================
// Selection: Segment → Buildings
// ============================================================================

function selectSegment(osmId, roadProps) {
    console.log('[Admin] selectSegment called, osmId=', osmId, typeof osmId);
    selectionMode = 'segment';
    selectedSegmentOsmId = osmId;
    selectedBuildingId = null;

    // Highlight the selected road segment
    map.setFilter('roads-selected', ['==', 'osm_id', osmId]);
    map.setFilter('roads-highlighted', ['==', 'osm_id', -999]);

    // Clear building highlights until API responds
    map.setFilter('buildings-highlighted', ['==', 'building_id', -999]);
    map.setFilter('buildings-highlighted-outline', ['==', 'building_id', -999]);
    map.setFilter('buildings-selected', ['==', 'building_id', -999]);
    map.setFilter('buildings-selected-outline', ['==', 'building_id', -999]);

    // Show buffer zone around segment
    lastSelectedBuildingSegmentGeometries = null;
    lastSelectedSegmentGeometry = getSegmentGeometryFromTiles(osmId);
    updateBuffer(lastSelectedSegmentGeometry);

    // Update info panel with placeholder count
    updateSegmentInfoPanel(osmId, roadProps, '...');

    // Fetch full building list from API and use building_id filter
    fetch(`${API_PREFIX}/admin/segment/${osmId}/buildings`)
        .then(r => r.json())
        .then(data => {
            const buildingIds = (data.building_ids || []).map(Number);
            console.log('[Admin] API returned buildingIds:', buildingIds.length, buildingIds.slice(0, 5));

            // Highlight by building_id so we catch all linked buildings
            if (buildingIds.length > 0) {
                const filter = ['in', 'building_id', ...buildingIds];
                console.log('[Admin] Setting buildings-highlighted filter:', JSON.stringify(filter).slice(0, 200));
                map.setFilter('buildings-highlighted', filter);
                map.setFilter('buildings-highlighted-outline', filter);
            }

            // Debug: check what tiles have these building_ids
            const rendered = map.queryRenderedFeatures({ layers: ['buildings-fill'] });
            const idSet = new Set(buildingIds);
            const visible = new Set();
            const missingIds = [];
            for (const f of rendered) {
                if (idSet.has(f.properties.building_id)) {
                    visible.add(f.properties.building_id);
                }
            }
            for (const bid of buildingIds) {
                if (!visible.has(bid)) missingIds.push(bid);
            }
            console.log('[Admin] Visible in viewport:', visible.size, '/', buildingIds.length);
            console.log('[Admin] Missing from viewport:', missingIds.length, missingIds.slice(0, 10));

            // Sample a rendered feature to check property types
            if (rendered.length > 0) {
                const sample = rendered[0].properties;
                console.log('[Admin] Sample tile feature — building_id:', sample.building_id, typeof sample.building_id,
                    'segment_osm_id:', sample.segment_osm_id, typeof sample.segment_osm_id);
            }

            updateSegmentInfoPanel(osmId, roadProps, visible.size);
            updateSegmentApiDetails(data);
        })
        .catch(err => { console.error('[Admin] selectSegment API error:', err); });
}

// ============================================================================
// Selection: Building → Segments
// ============================================================================

function selectBuilding(buildingId, segmentId, props) {
    console.log('[Admin] selectBuilding called, buildingId=', buildingId, typeof buildingId,
        'segmentId=', segmentId, typeof segmentId);
    selectionMode = 'building';
    selectedBuildingId = buildingId;
    selectedSegmentOsmId = segmentId;

    // Highlight selected building
    map.setFilter('buildings-selected', ['==', 'building_id', buildingId]);
    map.setFilter('buildings-selected-outline', ['==', 'building_id', buildingId]);

    // Immediately highlight the tile's segment (fast, before API returns)
    if (hasSegment(segmentId)) {
        map.setFilter('roads-highlighted', ['==', 'osm_id', segmentId]);
    } else {
        map.setFilter('roads-highlighted', ['==', 'osm_id', -999]);
    }
    map.setFilter('roads-selected', ['==', 'osm_id', -999]);
    map.setFilter('buildings-highlighted', ['==', 'segment_osm_id', -999]);
    map.setFilter('buildings-highlighted-outline', ['==', 'segment_osm_id', -999]);

    // Clear buffer until we know all segments
    lastSelectedSegmentGeometry = null;
    lastSelectedBuildingSegmentGeometries = null;
    clearBuffer();

    // Update info panel immediately with tile data
    updateBuildingInfoPanel(props, 0);

    // Fetch ALL segments for this building from API (the tile only stores one)
    fetch(`${API_PREFIX}/admin/building/${buildingId}/segments`)
        .then(r => r.json())
        .then(data => {
            const segIds = data.segment_osm_ids.map(Number);

            // Highlight ALL linked road segments
            if (segIds.length > 0) {
                map.setFilter('roads-highlighted', ['in', 'osm_id', ...segIds]);
            }

            // Show buffer around all linked segments
            lastSelectedBuildingSegmentGeometries = getMultiSegmentGeometry(segIds);
            updateBuffer(lastSelectedBuildingSegmentGeometries);

            // Re-update info panel with full data
            updateBuildingInfoPanelFull(props, segIds);
        })
        .catch(() => {});
}

// ============================================================================
// Clear
// ============================================================================

function clearSelection() {
    selectionMode = null;
    selectedBuildingId = null;
    selectedSegmentOsmId = null;
    lastSelectedSegmentGeometry = null;
    lastSelectedBuildingSegmentGeometries = null;

    map.setFilter('roads-selected', ['==', 'osm_id', -999]);
    map.setFilter('roads-highlighted', ['==', 'osm_id', -999]);
    map.setFilter('buildings-selected', ['==', 'building_id', -999]);
    map.setFilter('buildings-selected-outline', ['==', 'building_id', -999]);
    map.setFilter('buildings-highlighted', ['==', 'segment_osm_id', -999]);
    map.setFilter('buildings-highlighted-outline', ['==', 'segment_osm_id', -999]);

    clearBuffer();
    document.getElementById('info-panel').classList.remove('visible');
}

// ============================================================================
// Info Panel: Segment selected
// ============================================================================

function updateSegmentInfoPanel(osmId, roadProps, viewportBuildingCount) {
    const panel = document.getElementById('info-panel');
    const content = document.getElementById('info-content');

    let html = '<div class="info-section-title" style="color:#FF6D00">Road Segment</div>';
    html += infoRow('OSM ID', osmId);
    html += infoRow('Edges', roadProps.edge_count || '-');
    html += infoRow('Buildings (viewport)', viewportBuildingCount);
    html += '<div id="api-segment-details"></div>';

    content.innerHTML = html;
    panel.classList.add('visible');
}

function updateSegmentApiDetails(data) {
    const el = document.getElementById('api-segment-details');
    if (!el) return;

    let html = infoRow('Buildings (global)', data.count);
    if (data.building_ids && data.building_ids.length > 0) {
        html += '<div class="building-list">';
        html += data.building_ids.slice(0, 100).join(', ');
        if (data.building_ids.length > 100) {
            html += `<br>... and ${data.building_ids.length - 100} more`;
        }
        html += '</div>';
    }
    el.innerHTML = html;
}

// ============================================================================
// Info Panel: Building selected
// ============================================================================

function updateBuildingInfoPanel(props, siblingCount) {
    const panel = document.getElementById('info-panel');
    const content = document.getElementById('info-content');

    let html = '<div class="info-section-title" style="color:#2196F3">Building</div>';
    html += infoRow('Building ID', props.building_id);
    html += infoRow('Type', props.building_type || '-');
    html += infoRow('Name', props.name || '-');
    html += infoRow('Street', props.street || '-');
    html += infoRow('House #', props.housenumber || '-');
    html += '<div class="info-section"><div class="info-section-title">Segment Linkage</div>';
    html += '<div id="building-segments-detail">Loading...</div>';
    html += '</div>';

    content.innerHTML = html;
    panel.classList.add('visible');
}

function updateBuildingInfoPanelFull(props, segIds) {
    const el = document.getElementById('building-segments-detail');
    if (!el) return;

    if (segIds.length === 0) {
        el.innerHTML = infoRow('Status', '<span class="unlinked">NO SEGMENT LINKED</span>');
        return;
    }

    let html = infoRow('Linked segments', `<span class="linked">${segIds.length}</span>`);

    // List each segment with its own detail
    html += '<div style="margin-top:8px">';
    for (const sid of segIds) {
        html += `<div style="padding:4px 0; border-bottom:1px solid #eee; display:flex; justify-content:space-between; align-items:center;">`;
        html += `<span style="font-size:12px; color:#1976D2; font-weight:500;">${sid}</span>`;
        html += `<span class="seg-count" id="seg-count-${sid}" style="font-size:11px; color:#888;">...</span>`;
        html += `</div>`;

        // Fetch building count for each segment
        fetch(`${API_PREFIX}/admin/segment/${sid}/buildings`)
            .then(r => r.json())
            .then(data => {
                const countEl = document.getElementById(`seg-count-${data.osm_id}`);
                if (countEl) countEl.textContent = `${data.count} buildings`;
            })
            .catch(() => {});
    }
    html += '</div>';

    el.innerHTML = html;
}

function infoRow(label, value) {
    return `<div class="info-row"><span class="info-label">${label}</span><span class="info-value">${value}</span></div>`;
}

// ============================================================================
// Viewport Statistics
// ============================================================================

function debounceUpdateStats() {
    if (statsDebounceTimer) clearTimeout(statsDebounceTimer);
    statsDebounceTimer = setTimeout(updateViewportStats, 300);
}

function updateViewportStats() {
    // Building stats
    const bFeatures = map.queryRenderedFeatures({ layers: ['buildings-fill'] });
    const uniqueBuildings = new Map();
    for (const f of bFeatures) {
        const bid = f.properties.building_id;
        if (!uniqueBuildings.has(bid)) {
            uniqueBuildings.set(bid, f.properties);
        }
    }

    let linked = 0, unlinked = 0;
    const buildingSegments = new Set();
    uniqueBuildings.forEach(props => {
        if (hasSegment(props.segment_osm_id)) {
            linked++;
            buildingSegments.add(props.segment_osm_id);
        } else {
            unlinked++;
        }
    });

    // Road stats
    const rFeatures = map.queryRenderedFeatures({ layers: ['roads-base'] });
    const uniqueRoads = new Set();
    for (const f of rFeatures) {
        uniqueRoads.add(f.properties.osm_id);
    }

    const totalBuildings = uniqueBuildings.size;
    const ratio = totalBuildings > 0 ? (linked / totalBuildings * 100).toFixed(1) + '%' : '-';

    document.getElementById('stat-total').textContent = totalBuildings.toLocaleString();
    document.getElementById('stat-linked').textContent = linked.toLocaleString();
    document.getElementById('stat-unlinked').textContent = unlinked.toLocaleString();
    document.getElementById('stat-ratio').textContent = ratio;
    document.getElementById('stat-segments').textContent = uniqueRoads.size.toLocaleString();
}

async function loadGlobalStats() {
    try {
        const resp = await fetch(`${API_PREFIX}/admin/stats`);
        const stats = await resp.json();
        document.getElementById('stat-global-segments').textContent =
            (stats.total_segments || 0).toLocaleString();
        document.getElementById('stat-global-buildings').textContent =
            (stats.total_buildings_in_mapping || 0).toLocaleString();
        document.getElementById('stat-avg-bps').textContent =
            stats.avg_buildings_per_segment || '-';
        document.getElementById('stat-avg-spb').textContent =
            stats.avg_segments_per_building || '-';
    } catch (e) {
        console.warn('[Admin] Could not load global stats:', e);
    }
}

// ============================================================================
// Hover
// ============================================================================

function setupHover() {
    map.on('mouseenter', 'roads-base', () => {
        map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', 'roads-base', () => {
        map.getCanvas().style.cursor = '';
    });
    map.on('mouseenter', 'buildings-fill', () => {
        map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', 'buildings-fill', () => {
        map.getCanvas().style.cursor = '';
    });
}

// ============================================================================
// Search
// ============================================================================

async function doSearch() {
    const input = document.getElementById('search-input').value.trim();
    const resultEl = document.getElementById('search-result');

    if (!input) {
        resultEl.textContent = '';
        return;
    }

    const id = parseInt(input);
    if (isNaN(id)) {
        resultEl.textContent = 'Enter a numeric ID';
        return;
    }

    resultEl.textContent = 'Searching...';

    // Try as segment in viewport
    const roadFeatures = map.queryRenderedFeatures({ layers: ['roads-base'] });
    const roadHit = roadFeatures.find(f => f.properties.osm_id === id);
    if (roadHit) {
        resultEl.textContent = `Found segment ${id} in viewport`;
        selectSegment(id, roadHit.properties);
        return;
    }

    // Try as building in viewport
    const buildingFeatures = map.queryRenderedFeatures({ layers: ['buildings-fill'] });
    const buildingHit = buildingFeatures.find(f => f.properties.building_id === id);
    if (buildingHit) {
        resultEl.textContent = `Found building ${id} in viewport`;
        const coords = getCentroid(buildingHit.geometry);
        if (coords) map.flyTo({ center: coords, zoom: Math.max(map.getZoom(), 16) });
        selectBuilding(buildingHit.properties.building_id, buildingHit.properties.segment_osm_id, buildingHit.properties);
        return;
    }

    // Try as segment via API
    try {
        const resp = await fetch(`${API_PREFIX}/admin/segment/${id}/buildings`);
        const data = await resp.json();
        if (data.count > 0) {
            resultEl.textContent = `Segment ${id}: ${data.count} buildings. Pan to find it.`;
            selectSegment(id, { osm_id: id });
            return;
        }
    } catch (e) { /* ignore */ }

    // Try as building via API
    try {
        const resp = await fetch(`${API_PREFIX}/admin/building/${id}/segments`);
        const data = await resp.json();
        if (data.count > 0) {
            resultEl.textContent = `Building ${id}: segments ${data.segment_osm_ids.join(', ')}. Not in viewport.`;
            return;
        }
    } catch (e) { /* ignore */ }

    resultEl.textContent = `ID ${id} not found`;
}

function getCentroid(geometry) {
    if (!geometry || !geometry.coordinates) return null;
    const coords = geometry.type === 'MultiPolygon'
        ? geometry.coordinates[0][0]
        : geometry.coordinates[0];
    if (!coords || coords.length === 0) return null;

    let sumLon = 0, sumLat = 0;
    for (const c of coords) {
        sumLon += c[0];
        sumLat += c[1];
    }
    return [sumLon / coords.length, sumLat / coords.length];
}

// ============================================================================
// Init
// ============================================================================

initMap();

/**
 * Simulation Admin
 * Configure stations, fleet, and generate simulation data for a city.
 */

// ============================================================================
// Constants
// ============================================================================

const _city = typeof CITY_CONFIG !== 'undefined' ? CITY_CONFIG : {};
const _citySlug = typeof CITY_SLUG !== 'undefined' ? CITY_SLUG : 'paris';
const BUILDING_TILE_URL = location.origin + '/static/data/tiles/' + (_city.building_tiles || 'buildings') + '/{z}/{x}/{y}.pbf';
const ROAD_TILE_URL = location.origin + '/static/data/tiles/' + (_city.road_tiles || 'roads') + '/{z}/{x}/{y}.pbf';
const MAP_STYLE_URL = '/static/styles/maplibre_styles.json';
const MAP_CENTER = _city.center || [2.333333, 48.866667];
const INITIAL_ZOOM = (_city.zoom || 12) + 2;
const API_PREFIX = '/api/' + _citySlug;

// ============================================================================
// State
// ============================================================================

let map = null;
let stations = [];
let currentStep = 1;
let addStationMode = true;

// ============================================================================
// Map
// ============================================================================

async function initMap() {
    const resp = await fetch(MAP_STYLE_URL);
    const style = await resp.json();

    // Configure building tile source
    style.sources.composite.tiles = [BUILDING_TILE_URL];
    style.sources.composite.minzoom = 12;
    style.sources.composite.maxzoom = 17;

    // Add glyphs for text labels
    style.glyphs = 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf';

    // Brighten base map
    const osmLayer = style.layers.find(l => l.id === 'osm-base');
    if (osmLayer) {
        osmLayer.paint['raster-brightness-max'] = 0.85;
        osmLayer.paint['raster-brightness-min'] = 0.15;
        osmLayer.paint['raster-saturation'] = -0.6;
    }

    map = new maplibregl.Map({
        container: 'map',
        style: style,
        center: MAP_CENTER,
        zoom: INITIAL_ZOOM,
        minZoom: 8,
        maxZoom: 18,
    });

    map.addControl(new maplibregl.NavigationControl(), 'bottom-right');

    map.on('load', () => {
        // Road tiles for context
        map.addSource('roads', {
            type: 'vector',
            tiles: [ROAD_TILE_URL],
            minzoom: 10,
            maxzoom: 17,
        });

        map.addLayer({
            id: 'roads-base',
            type: 'line',
            source: 'roads',
            'source-layer': 'roads',
            paint: {
                'line-color': '#999',
                'line-width': ['interpolate', ['linear'], ['zoom'], 10, 0.5, 17, 3],
                'line-opacity': 0.6,
            },
        });

        // Building fill (from composite source)
        map.addLayer({
            id: 'buildings-fill',
            type: 'fill',
            source: 'composite',
            'source-layer': 'buildings',
            paint: {
                'fill-color': '#2196F3',
                'fill-opacity': 0.25,
            },
            filter: ['==', '$type', 'Polygon'],
        });

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

        // Station markers source
        map.addSource('stations', {
            type: 'geojson',
            data: stationsToGeoJSON(),
        });

        // Station circles
        map.addLayer({
            id: 'station-circles',
            type: 'circle',
            source: 'stations',
            paint: {
                'circle-radius': 10,
                'circle-color': '#FF6D00',
                'circle-stroke-color': '#fff',
                'circle-stroke-width': 2.5,
            },
        });

        // Station labels
        map.addLayer({
            id: 'station-labels',
            type: 'symbol',
            source: 'stations',
            layout: {
                'text-field': ['get', 'index'],
                'text-size': 11,
                'text-font': ['Open Sans Semibold'],
                'text-allow-overlap': true,
            },
            paint: {
                'text-color': '#fff',
            },
        });

        // Station name labels (offset below)
        map.addLayer({
            id: 'station-name-labels',
            type: 'symbol',
            source: 'stations',
            layout: {
                'text-field': ['get', 'name'],
                'text-size': 11,
                'text-font': ['Open Sans Semibold'],
                'text-offset': [0, 1.8],
                'text-allow-overlap': true,
            },
            paint: {
                'text-color': '#333',
                'text-halo-color': '#fff',
                'text-halo-width': 1.5,
            },
        });

        // Click to add station
        map.on('click', (e) => {
            if (!addStationMode || currentStep !== 1) return;
            // Don't add if clicking on existing station
            const hits = map.queryRenderedFeatures(e.point, { layers: ['station-circles'] });
            if (hits.length > 0) return;

            addStationAt(e.lngLat.lat, e.lngLat.lng);
        });

        map.getCanvas().style.cursor = 'crosshair';

        console.log('[Simulation] Map loaded');
    });
}

// ============================================================================
// Station Management
// ============================================================================

function stationsToGeoJSON() {
    return {
        type: 'FeatureCollection',
        features: stations.map((s, i) => ({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
            properties: { index: i + 1, name: s.name },
        })),
    };
}

function updateStationSource() {
    if (map && map.getSource('stations')) {
        map.getSource('stations').setData(stationsToGeoJSON());
    }
}

function updateStationButtons() {
    const btn = document.getElementById('next-fleet-btn');
    if (btn) btn.disabled = stations.length === 0;
}

function renderStationList() {
    const container = document.getElementById('station-list');
    updateStationButtons();
    if (stations.length === 0) {
        container.innerHTML = '<div class="hint">No stations yet. Click the map or use auto-propose.</div>';
        return;
    }
    container.innerHTML = stations.map((s, i) => `
        <div class="station-item">
            <div class="station-info">
                <div class="station-name">${i + 1}. ${s.name}</div>
                <div class="station-coords">${s.lat.toFixed(5)}, ${s.lon.toFixed(5)}</div>
            </div>
            <button class="remove-btn" onclick="removeStation(${i})" title="Remove">&times;</button>
        </div>
    `).join('');
}

async function importFromOSM() {
    const btn = document.getElementById('osm-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Fetching from OpenStreetMap...';

    try {
        const resp = await fetch(`${API_PREFIX}/admin/simulation/osm-stations`);
        const data = await resp.json();

        if (!resp.ok) {
            throw new Error(data.detail || 'Failed to fetch stations');
        }

        if (!data.stations || data.count === 0) {
            btn.innerHTML = 'No stations found in OSM';
            setTimeout(() => {
                btn.disabled = false;
                btn.innerHTML = 'Import real stations from OpenStreetMap';
            }, 3000);
            return;
        }

        stations = data.stations;
        stations.forEach(s => {
            s.tier = s.tier || classifyStation(s.name, s.type);
            if (!s.fleet) s.fleet = defaultFleet(s.name, s.type);
        });
        updateStationSource();
        renderStationList();

        // Fit map to stations
        if (stations.length > 1) {
            const bounds = new maplibregl.LngLatBounds();
            stations.forEach(s => bounds.extend([s.lon, s.lat]));
            map.fitBounds(bounds, { padding: 80 });
        }

        btn.innerHTML = `Imported ${data.count} stations from OSM`;
        btn.disabled = false;
    } catch (err) {
        btn.disabled = false;
        btn.innerHTML = 'Import real stations from OpenStreetMap';
        alert('Error fetching OSM data: ' + err.message);
    }
}

async function autoPropose() {
    const count = parseInt(document.getElementById('station-count').value) || 3;
    const resp = await fetch(`${API_PREFIX}/admin/simulation/propose-stations?count=${count}`);
    const data = await resp.json();
    stations = data.stations;
    updateStationSource();
    renderStationList();

    // Fit map to stations
    if (stations.length > 1) {
        const bounds = new maplibregl.LngLatBounds();
        stations.forEach(s => bounds.extend([s.lon, s.lat]));
        map.fitBounds(bounds, { padding: 80 });
    }
}

async function addStationAt(lat, lon) {
    // Snap to nearest road node
    const resp = await fetch(`${API_PREFIX}/admin/simulation/snap-to-node?lat=${lat}&lon=${lon}`);
    const data = await resp.json();
    stations.push({
        name: `Station ${stations.length + 1}`,
        lat: data.lat,
        lon: data.lon,
        node_id: data.node_id,
        fleet: defaultFleet('Station', 'cs'),
    });
    updateStationSource();
    renderStationList();
}

function removeStation(index) {
    stations.splice(index, 1);
    // Rename remaining
    stations.forEach((s, i) => { s.name = `Station ${i + 1}`; });
    updateStationSource();
    renderStationList();
}

// ============================================================================
// Fleet Configuration
// ============================================================================

const VEHICLE_TYPES = [
    { key: '2', code: 'VSAV', label: 'Rescue', icon: '🚑', defaultCount: 2 },
    { key: '3', code: 'EP',   label: 'Engine', icon: '🚒', defaultCount: 2 },
    { key: '5', code: 'MEA',  label: 'Ladder', icon: '🪜', defaultCount: 1 },
];

// Density tier profiles — illustrative calibration (see density_profiles.py)
const DENSITY_PROFILES = {
    dense_urban: { label: 'Dense Urban', fleet: {'2': 3, '3': 3, '5': 2}, speed: 19.6, mobil: 150, color: '#dc2626' },
    urban:       { label: 'Urban',       fleet: {'2': 2, '3': 2, '5': 1}, speed: 23.7, mobil: 144, color: '#f59e0b' },
    suburban:    { label: 'Suburban',     fleet: {'2': 1, '3': 1, '5': 1}, speed: 26.2, mobil: 147, color: '#10b981' },
    rural:       { label: 'Rural',       fleet: {'2': 1, '3': 1, '5': 0}, speed: 17.5, mobil: 132, color: '#6366f1' },
};

function classifyStation(name, type) {
    const n = (name || '').toLowerCase();
    const t = (type || '').toLowerCase();
    // CSP = Centre de Secours Principal → dense_urban or urban
    if (t === 'csp' || n.includes('csp ') || n.includes('principal'))
        return 'urban';
    // CPI = Centre de Première Intervention → rural
    if (t === 'cpi' || n.includes('cpi ') || n.includes('première intervention'))
        return 'rural';
    // Corporate/industrial
    if (n.includes('betriebs') || n.includes('corporate') || n.includes('industrial'))
        return 'rural';
    // CS = Centre de Secours → suburban
    if (t === 'cs' || n.includes('cs '))
        return 'suburban';
    // Default
    return 'suburban';
}

function defaultFleet(name, type) {
    const tier = classifyStation(name, type);
    return Object.assign({}, DENSITY_PROFILES[tier].fleet);
}

function renderFleetConfig() {
    const container = document.getElementById('fleet-config');
    if (stations.length === 0) {
        container.innerHTML = '<div class="hint">Add stations first (Step 1)</div>';
        document.getElementById('fleet-summary').innerHTML = '';
        return;
    }

    const thCols = VEHICLE_TYPES.map(v =>
        `<th title="${v.code}">${v.icon} ${v.label}</th>`).join('');

    let html = `<table class="fleet-table">
        <thead><tr>
            <th>Station</th>
            ${thCols}
            <th>Total</th>
        </tr></thead><tbody>`;

    const totals = {};
    VEHICLE_TYPES.forEach(v => totals[v.key] = 0);

    stations.forEach((s, i) => {
        if (!s.fleet) s.fleet = defaultFleet(s.name, s.type);
        const tier = s.tier || classifyStation(s.name, s.type);
        const tierInfo = DENSITY_PROFILES[tier] || DENSITY_PROFILES.suburban;
        let rowTotal = 0;
        const cells = VEHICLE_TYPES.map(v => {
            const count = parseInt(s.fleet[v.key]) || 0;
            totals[v.key] += count;
            rowTotal += count;
            return `<td><input type="number" value="${count}" min="0" max="50"
                onchange="updateFleet(${i}, '${v.key}', this.value)"></td>`;
        }).join('');

        html += `<tr>
            <td style="font-weight:500">${s.name}
                <div style="font-size:10px;color:${tierInfo.color};margin-top:2px">
                    ${tierInfo.label} · ${tierInfo.speed} km/h · mob ${tierInfo.mobil}s
                </div>
            </td>
            ${cells}
            <td style="font-weight:600">${rowTotal}</td>
        </tr>`;
    });

    let grandTotal = 0;
    const totalCells = VEHICLE_TYPES.map(v => {
        grandTotal += totals[v.key];
        return `<td>${totals[v.key]}</td>`;
    }).join('');

    html += `<tr class="total-row">
        <td>Total</td>
        ${totalCells}
        <td>${grandTotal}</td>
    </tr></tbody></table>`;

    container.innerHTML = html;

    // Auto-compute weighted average speed from density profiles
    let totalUnits = 0, weightedSpeed = 0;
    stations.forEach(s => {
        const tier = s.tier || classifyStation(s.name, s.type);
        const profile = DENSITY_PROFILES[tier] || DENSITY_PROFILES.suburban;
        const units = Object.values(s.fleet || {}).reduce((a, b) => a + parseInt(b || 0), 0);
        totalUnits += units;
        weightedSpeed += profile.speed * units;
    });
    const speedField = document.getElementById('gen-speed');
    if (speedField && totalUnits > 0) {
        speedField.value = Math.round(weightedSpeed / totalUnits);
    }

    const offset = (_city.unit_id_offset || 100);
    document.getElementById('fleet-summary').innerHTML =
        `<div class="hint">Unit IDs: ${offset + 1} - ${offset + grandTotal}</div>`;
}

function updateFleet(stationIdx, type, value) {
    stations[stationIdx].fleet[type] = parseInt(value) || 0;
    renderFleetConfig();
}

function applyDensityDefaults() {
    stations.forEach(s => {
        const tier = classifyStation(s.name, s.type);
        s.tier = tier;
        s.fleet = Object.assign({}, DENSITY_PROFILES[tier].fleet);
    });
    renderFleetConfig();

    // Update speed field with weighted average
    let totalUnits = 0, weightedSpeed = 0;
    stations.forEach(s => {
        const tier = s.tier || 'suburban';
        const profile = DENSITY_PROFILES[tier];
        const units = Object.values(s.fleet).reduce((a, b) => a + b, 0);
        totalUnits += units;
        weightedSpeed += profile.speed * units;
    });
    if (totalUnits > 0) {
        document.getElementById('gen-speed').value = Math.round(weightedSpeed / totalUnits);
    }
}

// ============================================================================
// Generation
// ============================================================================

function updateGenSummary() {
    const days = parseInt(document.getElementById('gen-days').value) || 7;
    const totalVehicles = stations.reduce((sum, s) => {
        const f = s.fleet || {};
        return sum + VEHICLE_TYPES.reduce((vs, v) => vs + (parseInt(f[v.key]) || 0), 0);
    }, 0);

    document.getElementById('gen-summary').innerHTML =
        `<strong>${stations.length}</strong> stations, ` +
        `<strong>${totalVehicles}</strong> vehicles, ` +
        `<strong>${days}</strong> days of simulation`;
}

async function startGeneration() {
    if (stations.length === 0) {
        alert('Add at least one station first');
        return;
    }

    const btn = document.getElementById('gen-btn');
    btn.disabled = true;
    btn.textContent = 'Generating...';

    document.getElementById('gen-progress').style.display = 'block';
    document.getElementById('gen-result').classList.remove('visible');

    const body = {
        stations: stations.map(s => ({
            name: s.name,
            lat: s.lat,
            lon: s.lon,
            fleet: s.fleet || defaultFleet(s.name, s.type),
            tier: s.tier || classifyStation(s.name, s.type),
        })),
        duration_days: parseInt(document.getElementById('gen-days').value) || 7,
        speed_kmh: parseFloat(document.getElementById('gen-speed').value) || 40,
        hourly_scale: parseFloat(document.getElementById('gen-scale').value) || 1.0,
        coverage_threshold_sec: parseInt(document.getElementById('gen-coverage-threshold').value) || 600,
    };

    try {
        const resp = await fetch(`${API_PREFIX}/admin/simulation/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json();
        pollProgress(data.task_id);
    } catch (err) {
        btn.disabled = false;
        btn.textContent = 'Generate Simulation Data';
        alert('Error starting generation: ' + err.message);
    }
}

function pollProgress(taskId) {
    const interval = setInterval(async () => {
        try {
            const resp = await fetch(`${API_PREFIX}/admin/simulation/progress/${taskId}`);
            const data = await resp.json();

            document.getElementById('progress-fill').style.width = data.progress + '%';
            document.getElementById('progress-msg').textContent = data.message;

            if (data.status === 'complete') {
                clearInterval(interval);
                onGenerationComplete(data);
            } else if (data.status === 'error') {
                clearInterval(interval);
                onGenerationError(data);
            }
        } catch (err) {
            console.error('[Simulation] Poll error:', err);
        }
    }, 1000);
}

function onGenerationComplete(data) {
    const btn = document.getElementById('gen-btn');
    btn.disabled = false;
    btn.textContent = 'Generate Simulation Data';

    document.getElementById('gen-result').classList.add('visible');
    document.getElementById('result-detail').innerHTML =
        `<strong>${(data.record_count || 0).toLocaleString()}</strong> records inserted.`;
}

async function startStreaming() {
    const btn = document.getElementById('start-stream-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Starting streaming...';

    try {
        const resp = await fetch(`${API_PREFIX}/admin/simulation/start-streaming`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Failed to start streaming');
        // Redirect to the map
        window.location.href = `/area/${_citySlug}/map`;
    } catch (err) {
        btn.disabled = false;
        btn.innerHTML = 'Start Streaming &rarr; Open Map';
        alert('Error: ' + err.message);
    }
}

function onGenerationError(data) {
    const btn = document.getElementById('gen-btn');
    btn.disabled = false;
    btn.textContent = 'Generate Simulation Data';
    document.getElementById('progress-msg').textContent = 'Error: ' + data.message;
    document.getElementById('progress-msg').style.color = '#e53935';
}

// ============================================================================
// Step Navigation
// ============================================================================

function goToStep(step) {
    currentStep = step;

    // Update nav buttons
    document.querySelectorAll('.step-btn').forEach(btn => {
        const s = parseInt(btn.dataset.step);
        btn.classList.remove('active', 'done');
        if (s === step) btn.classList.add('active');
        else if (s < step) btn.classList.add('done');
    });

    // Show/hide content
    document.querySelectorAll('.step-content').forEach(el => el.classList.remove('active'));
    document.getElementById(`step-${step}`).classList.add('active');

    // Update cursor
    if (map) {
        map.getCanvas().style.cursor = step === 1 ? 'crosshair' : '';
    }

    // Render step-specific content
    if (step === 2) renderFleetConfig();
    if (step === 3) updateGenSummary();
}

// ============================================================================
// Init
// ============================================================================

initMap();
renderStationList();

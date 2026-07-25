/**
 * Reference Data Loader Callbacks
 * Converted from jQuery to vanilla JavaScript
 */

// Unit competences loaded
function callback_unit_competences_loaded() {
    // Usage my_dataframe[column][index]
}

// Unit categories loaded
function callback_unit_categories_loaded() {
    // Usage my_dataframe[column][index]
}

// Station markers rendered via MapLibre
var _stationMarkers = [];

async function callback_stations_loaded() {
    // Fetch stations from the city-aware API
    const citySlug = (typeof __CITY_SLUG !== 'undefined') ? __CITY_SLUG : 'paris';
    console.log(`[stations] Loading stations for city: ${citySlug}`);
    try {
        const resp = await fetch(`/api/${citySlug}/stations`);
        if (!resp.ok) {
            console.warn(`[stations] API returned ${resp.status}`);
            return;
        }
        const data = await resp.json();
        const stationList = data.stations || [];
        console.log(`[stations] Got ${stationList.length} stations (source: ${data.source})`);

        stationList.forEach((st, i) => {
            const el = document.createElement('div');
            el.className = 'station-marker';
            el.title = st.name || 'Station';

            const marker = new maplibregl.Marker({ element: el })
                .setLngLat([st.lon, st.lat])
                .setPopup(new maplibregl.Popup({ offset: 12 }).setText(st.name || 'Station'))
                .addTo(map);
            _stationMarkers.push(marker);
            if (i < 3) console.log(`[stations] Added: ${st.name} at [${st.lon}, ${st.lat}]`);
        });
        console.log(`[stations] ${_stationMarkers.length} markers added to map`);
    } catch (e) {
        console.warn('[stations] Failed to load stations:', e);
    }

    // Toggle visibility
    const stationsToggle = document.getElementById('togBtnStations');
    if (stationsToggle) {
        stationsToggle.addEventListener('change', function() {
            const visible = this.checked;
            this.value = visible ? 'true' : 'false';
            _stationMarkers.forEach(m => {
                m.getElement().style.display = visible ? '' : 'none';
            });
        });
    }
}

// Types of points of interest loaded
async function callback_pois_types_loaded() {
    // Currently unused
}

// Hospital markers rendered via MapLibre
var _hospitalMarkers = [];

async function callback_pois_loaded() {
    // Hospitals from CSV are Paris-only; for now render whatever pois were loaded
    if (typeof pois !== 'undefined' && pois['lat']) {
        const keys = Object.keys(pois['lat'] || {});
        keys.forEach(k => {
            const lat = parseFloat(pois['lat'][k]);
            const lon = parseFloat(pois['lon'][k]);
            if (isNaN(lat) || isNaN(lon)) return;
            const name = (pois['health facility'] && pois['health facility'][k]) || 'Hospital';

            const el = document.createElement('div');
            el.className = 'hospital-marker';
            el.title = name;
            el.style.display = 'none'; // hidden by default

            const marker = new maplibregl.Marker({ element: el })
                .setLngLat([lon, lat])
                .setPopup(new maplibregl.Popup({ offset: 12 }).setText(name))
                .addTo(map);
            _hospitalMarkers.push(marker);
        });
    }

    // Toggle visibility
    const hospitalsToggle = document.getElementById('togBtnHospitals');
    if (hospitalsToggle) {
        hospitalsToggle.addEventListener('change', function() {
            const visible = this.checked;
            this.value = visible ? 'true' : 'false';
            _hospitalMarkers.forEach(m => {
                m.getElement().style.display = visible ? '' : 'none';
            });
        });
    }
}

// Status loaded
function callback_status_loaded() {
    // No-op - status data ready for use
}
/*
// Global master data loader
function dataref_loader(){
    csv_to_dataframe_like_array("../../../static/data/config/unit_categories.csv", "id", unit_categories, callback_unit_categories_loaded);
    csv_to_dataframe_like_array("../../../static/data/config/stations.csv", "id", stations, callback_stations_loaded);
    csv_to_dataframe_like_array("../../../static/data/config/status.csv", "id",STATUS, callback_status_loaded);
}
*/
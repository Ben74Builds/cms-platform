/***
 * Map Architecture (Pure MapLibre):
 *  - map: MapLibre map handling base tiles (OSM raster), coverage, routes, and markers
 *  - donutCluster: Supercluster-based clustering with SVG donut charts
 */

// URL Parameters support
const urlParams = new URLSearchParams(window.location.search);
const URL_ZOOM = parseFloat(urlParams.get('zoom')) || INITIAL_ZOOM;
const URL_LAT = parseFloat(urlParams.get('lat')) || INITIAL_CENTER_LAT;
const URL_LON = parseFloat(urlParams.get('lon')) || INITIAL_CENTER_LON;
const URL_LANG = urlParams.get('lang') || 'fr';

// Filter state from URL (new)
const URL_FILTER_TYPE = urlParams.get('filter') || 'all';
const URL_FILTER_VALUE = urlParams.get('filter_value') ? parseInt(urlParams.get('filter_value')) : null;

// Update URL when map moves (debounced)
let urlUpdateTimeout = null;
function updateUrlParams() {
    if (urlUpdateTimeout) clearTimeout(urlUpdateTimeout);
    urlUpdateTimeout = setTimeout(() => {
        const center = map.getCenter();
        const zoom = map.getZoom().toFixed(2);

        // Build URL with all state
        const params = new URLSearchParams();
        params.set('zoom', zoom);
        params.set('lat', center.lat.toFixed(6));
        params.set('lon', center.lng.toFixed(6));
        params.set('lang', URL_LANG);

        // Include filter state
        if (selection_type && selection_type !== 'all') {
            params.set('filter', selection_type);
            if (sub_selection_type !== null) {
                params.set('filter_value', sub_selection_type);
            }
        }

        const newUrl = `${window.location.pathname}?${params.toString()}`;
        window.history.replaceState({}, '', newUrl);
    }, 500);
}

// Restore filter state from URL
function restoreFilterStateFromUrl() {
    if (URL_FILTER_TYPE === 'category' && URL_FILTER_VALUE !== null) {
        selection_type = 'category';
        sub_selection_type = URL_FILTER_VALUE;
        // Set dropdown after it's populated (handled in rebuildCategoriesDropdown)
    } else if (URL_FILTER_TYPE === 'competence' && URL_FILTER_VALUE !== null) {
        selection_type = 'competence';
        sub_selection_type = URL_FILTER_VALUE;
        // Set dropdown after it's populated (handled in rebuildCompetencesDropdown)
    }
}

// ============================================================================
// Loading Progress System
// ============================================================================

const loadingProgress = {
    steps: [
        { id: 'status', label: 'Loading status data' },
        { id: 'map', label: 'Initializing map' },
        { id: 'worker', label: 'Starting background workers' },
        { id: 'cluster', label: 'Setting up clustering' },
        { id: 'reference', label: 'Loading reference data' },
        { id: 'positions', label: 'Loading unit positions' },
        { id: 'streams', label: 'Connecting to live streams' }
    ],
    currentStep: 0,
    overlay: null,
    progressBar: null,
    stepLabel: null,
    stepsList: null,

    init() {
        this.overlay = document.getElementById('loading_overlay');
        this.progressBar = document.getElementById('loading_progress_bar');
        this.stepLabel = document.getElementById('loading_step');
        this.stepsList = document.getElementById('loading_steps_list');

        if (this.stepsList) {
            this.stepsList.innerHTML = this.steps.map((step, i) =>
                `<div class="loading-step-item pending" id="step_${step.id}">
                    <span class="step-icon"></span>
                    <span>${step.label}</span>
                </div>`
            ).join('');
        }
    },

    update(stepId) {
        const stepIndex = this.steps.findIndex(s => s.id === stepId);
        if (stepIndex === -1) return;

        // Mark previous steps as completed
        for (let i = 0; i < stepIndex; i++) {
            const el = document.getElementById(`step_${this.steps[i].id}`);
            if (el) {
                el.classList.remove('pending', 'active');
                el.classList.add('completed');
            }
        }

        // Mark current step as active
        const currentEl = document.getElementById(`step_${stepId}`);
        if (currentEl) {
            currentEl.classList.remove('pending', 'completed');
            currentEl.classList.add('active');
        }

        // Update progress bar
        const progress = ((stepIndex + 1) / this.steps.length) * 100;
        if (this.progressBar) {
            this.progressBar.style.width = `${progress}%`;
        }

        // Update step label
        const step = this.steps[stepIndex];
        if (this.stepLabel && step) {
            this.stepLabel.textContent = step.label + '...';
        }

        this.currentStep = stepIndex;
    },

    complete() {
        // Mark all steps as completed
        this.steps.forEach(step => {
            const el = document.getElementById(`step_${step.id}`);
            if (el) {
                el.classList.remove('pending', 'active');
                el.classList.add('completed');
            }
        });

        if (this.progressBar) {
            this.progressBar.style.width = '100%';
        }

        if (this.stepLabel) {
            this.stepLabel.textContent = 'Ready!';
        }

        // Hide overlay after a short delay
        setTimeout(() => {
            if (this.overlay) {
                this.overlay.classList.add('hidden');
            }
        }, 500);
    }
};

// ============================================================================
// Unit Index Management (O(1) lookups)
// ============================================================================

/**
 * Add a unit to the category and competence indexes
 * @param {string|number} unitId
 * @param {number} category
 * @param {Array<number>} competences
 */
function addUnitToIndexes(unitId, category, competences) {
    // Ensure unitId is stored as string for consistent lookups
    const unitIdStr = String(unitId);

    // Add to category index
    if (category !== undefined && category !== null) {
        if (!unitsByCategory.has(category)) {
            unitsByCategory.set(category, new Set());
        }
        unitsByCategory.get(category).add(unitIdStr);
    }

    // Add to competence indexes
    if (competences && Array.isArray(competences)) {
        for (const comp of competences) {
            if (!unitsByCompetence.has(comp)) {
                unitsByCompetence.set(comp, new Set());
            }
            unitsByCompetence.get(comp).add(unitIdStr);
        }
    }
}

/**
 * Remove a unit from indexes (called before updating unit data)
 * @param {string|number} unitId
 */
function removeUnitFromIndexes(unitId) {
    const unitIdStr = String(unitId);
    const unit = units[unitId];
    if (!unit) return;

    // Remove from old category index
    if (unit.cat !== undefined && unitsByCategory.has(unit.cat)) {
        unitsByCategory.get(unit.cat).delete(unitIdStr);
    }

    // Remove from old competence indexes
    if (unit.competences && Array.isArray(unit.competences)) {
        for (const comp of unit.competences) {
            if (unitsByCompetence.has(comp)) {
                unitsByCompetence.get(comp).delete(unitIdStr);
            }
        }
    }
}

/**
 * Get units matching the current filter (O(1) lookup)
 * @returns {Set<string>|null} Set of unit IDs, or null for "all"
 */
function getFilteredUnitIds() {
    if (selection_type === 'all') {
        return null; // All units
    } else if (selection_type === 'category' && sub_selection_type !== null) {
        return unitsByCategory.get(sub_selection_type) || new Set();
    } else if (selection_type === 'competence' && sub_selection_type !== null) {
        return unitsByCompetence.get(sub_selection_type) || new Set();
    }
    return null;
}

/**
 * Load the main MapLibre map with OSM raster base and coverage layers
 */
async function load_maplibre_layer() {
    const response = await fetch(MAPLIBRE_LAYER_BASE_STYLE_FILE);
    maplibre_layer_base_style = await response.json();

    // Set the tile source URL for coverage
    maplibre_layer_base_style.sources.composite.tiles = [TILESOURCE_URL];

    // Configure promoteId for feature-state support (CRITICAL for performance)
    // This maps the building_id/osm_id property to the feature ID
    const idProperty = COVERAGE_MODE === "buildings" ? "building_id" : "osm_id";
    maplibre_layer_base_style.sources.composite.promoteId = { [SOURCE_LAYER]: idProperty };

    map = new maplibregl.Map({
        container: 'map',
        style: maplibre_layer_base_style,
        center: [URL_LON, URL_LAT],
        minZoom: MIN_ZOOM,
        zoom: URL_ZOOM,
        maxZoom: MAX_ZOOM,
        attributionControl: true
    });

    map.addControl(new maplibregl.NavigationControl(), 'top-left');
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 200, unit: 'metric' }), 'bottom-left');

    // Wait for map to load, then initialize coverage layers
    return new Promise((resolve) => {
        map.on('load', () => {
            console.log('Map loaded, initializing coverage layers...');
            initCoverageLayers();
            resolve();
        });

        // Update URL on map move
        map.on('moveend', updateUrlParams);

        // Update visible features coverage when viewport settles
        map.on('moveend', scheduleViewportUpdate);
        // sourcedata: only needed for MapLibre path (setFeatureState on new tiles)
        if (!USE_DECKGL_COVERAGE) {
            map.on('sourcedata', (e) => {
                if (e.sourceId === 'composite' && e.isSourceLoaded) {
                    scheduleViewportUpdate();
                }
            });
        }
    });
}

/**
 * Initialize the MapLibre Donut Cluster
 */
function initDonutCluster() {
    // Main cluster for all units
    donutCluster = new MapLibreDonutCluster(map, {
        clusterRadius: MAX_CLUSTER_RADIUS,
        clusterMaxZoom: 16,
        statusKey: 'status',
        colorDict: STATUS["color"] || {},
        markerSize: 20,
        clusterSizeBase: 30,
        clusterSizeScale: 0.5
    });

    // Handle unit click events
    map.getContainer().addEventListener('unitclick', (e) => {
        const { unitId, status, coordinates, properties } = e.detail;
        showUnitPopup(unitId, coordinates);
    });
}

/**
 * Show popup for a unit
 */
function showUnitPopup(unitId, coordinates) {
    const unit = units[unitId];
    if (!unit) return;

    const content = `
        <strong>${unit_categories["code"][unit.cat] || ''} ${unitId}</strong><br>
        ${stations["code"][unit.station] || ''}<br>
        ${STATUS["label"][unit.status] || ''}<br>
        Update: ${unit.date || ''}
    `;

    new maplibregl.Popup()
        .setLngLat(coordinates)
        .setHTML(content)
        .addTo(map);
}

/**
 * Setup filter handlers for categories and competences
 */
function setupFilterHandlers() {
    // Display all handler
    document.getElementById("display_all").addEventListener('click', function(event) {
        event.preventDefault();
        selection_type = "all";
        sub_selection_type = null;
        document.getElementById('categories_dropdownlist').selectedIndex = 0;
        document.getElementById('competences_dropdownlist').selectedIndex = 0;

        // Show all units in cluster
        if (donutCluster) {
            donutCluster.setVisible(true);
        }

        // Show all routes
        for (let unitId in units) {
            if (units[unitId].routeLayerId) {
                setRouteVisibility(unitId, true);
            }
        }

        // Update coverage rendering
        update_coverage_rendering();

        // Show all intervention markers
        for (let intervention in interventions) {
            if (interventionMarkers[intervention]) {
                interventionMarkers[intervention].getElement().style.display = '';
            }
        }

        // Update URL with filter state
        updateUrlParams();
    });

    // Category dropdown handler
    document.getElementById('categories_dropdownlist').addEventListener('change', function(event) {
        const selectedCategory = parseInt(this.value);
        selection_type = "category";
        sub_selection_type = selectedCategory;

        document.getElementById('competences_dropdownlist').selectedIndex = 0;

        // Update route visibility
        for (let unitId in units) {
            if (units[unitId].routeLayerId) {
                setRouteVisibility(unitId, units[unitId].cat === selectedCategory);
            }
        }

        // Update coverage rendering
        update_coverage_rendering();

        // Update URL with filter state
        updateUrlParams();
    });

    // Competence dropdown handler
    document.getElementById('competences_dropdownlist').addEventListener('change', function(event) {
        const selectedCompetence = parseInt(this.value);
        selection_type = "competence";
        sub_selection_type = selectedCompetence;

        document.getElementById('categories_dropdownlist').selectedIndex = 0;

        // Update route visibility
        for (let unitId in units) {
            if (units[unitId].routeLayerId) {
                const hasCompetence = units[unitId].competences &&
                                      units[unitId].competences.includes(selectedCompetence);
                setRouteVisibility(unitId, hasCompetence);
            }
        }

        // Update coverage rendering
        update_coverage_rendering();

        // Update URL with filter state
        updateUrlParams();
    });

    // Restore filter state from URL on setup
    restoreFilterStateFromUrl();
}

// ============================================================================
// Deck.gl Coverage Layer (GPU-accelerated)
// ============================================================================

let deckOverlay = null;
let deckCoverageLayer = null;

/**
 * Initialize Deck.gl coverage layer (GPU-accelerated alternative to MapLibre)
 * Uses MVTLayer for direct GPU rendering without setFeatureState overhead
 */
function initDeckGLCoverage() {
    if (!USE_DECKGL_COVERAGE) return;
    if (!window.deckglCreateCoverageLayer || !window.deckglCreateOverlay) {
        console.error('[Deck.gl] Module not loaded, falling back to MapLibre');
        return false;
    }

    const idProperty = COVERAGE_MODE === "buildings" ? "building_id" : "osm_id";
    debugLog.log(`Init Deck.gl: mode=${COVERAGE_MODE}, idProperty=${idProperty}`, 'info');

    try {
        // Create the MVT coverage layer
        deckCoverageLayer = window.deckglCreateCoverageLayer(
            TILESOURCE_URL,
            SOURCE_LAYER,
            idProperty
        );

        if (!deckCoverageLayer) {
            console.error('[Deck.gl] Failed to create coverage layer');
            return false;
        }

        // Create the overlay and add to map
        deckOverlay = window.deckglCreateOverlay([deckCoverageLayer]);

        if (!deckOverlay) {
            console.error('[Deck.gl] Failed to create overlay');
            return false;
        }

        map.addControl(deckOverlay);

        debugLog.log('Deck.gl coverage layer initialized', 'info');
        return true;
    } catch (e) {
        console.error('[Deck.gl] Init error:', e);
        debugLog.log(`Deck.gl init error: ${e.message}`, 'error');
        return false;
    }
}

/**
 * Update Deck.gl layer to trigger re-render with new coverage state
 */
function updateDeckGLLayer() {
    if (!deckOverlay || !deckCoverageLayer) return;

    const idProperty = COVERAGE_MODE === "buildings" ? "building_id" : "osm_id";

    // Clone layer with new updateTriggers to force re-render
    deckCoverageLayer = deckCoverageLayer.clone({
        updateTriggers: {
            getFillColor: [window.deckglGetStateVersion()],
            getLineColor: [window.deckglGetStateVersion()]
        }
    });

    deckOverlay.setProps({ layers: [deckCoverageLayer] });
}

// Web Worker for coverage calculations (offloads heavy computation from main thread)
let coverageWorker = null;
let coverageUpdatePending = false;
let coverageUpdateTimeout = null;

/**
 * Initialize the coverage Web Worker
 */
function initCoverageWorker() {
    if (window.Worker) {
        coverageWorker = new Worker('/static/js/coverage-worker.js');

        coverageWorker.onmessage = function(e) {
            const { type, global_coverage: newCoverage, totalCovered, computeTime } = e.data;

            if (type === 'coverage') {
                // Update global coverage from worker result
                global_coverage = newCoverage;
                debugLog.log(`Worker: ${totalCovered} IDs in ${computeTime.toFixed(1)}ms`, 'data');

                // Trigger viewport update
                scheduleViewportUpdate();
            }
        };

        coverageWorker.onerror = function(e) {
            console.error('Coverage worker error:', e);
            debugLog.log(`Worker error: ${e.message}`, 'error');
        };

        debugLog.log('Coverage worker initialized', 'info');
    } else {
        debugLog.log('Web Workers not supported, using main thread', 'warn');
    }
}

/**
 * Update coverage rendering - uses main thread (worker was adding complexity)
 * Optimized: Only builds the lookup, viewport update handles rendering
 *
 * For Deck.gl: Rebuilds coverage state and triggers layer update
 * For MapLibre: Builds lookup and schedules viewport update
 */
function update_coverage_rendering() {
    coverageUpdatePending = true;

    if (coverageUpdateTimeout) return;

    coverageUpdateTimeout = setTimeout(() => {
        coverageUpdateTimeout = null;
        if (!coverageUpdatePending) return;
        coverageUpdatePending = false;

        // Compute on main thread - it's fast enough with optimized data structures
        _doUpdateCoverageRenderingSync();
    }, 100);
}

/**
 * Synchronous coverage calculation - optimized for speed using O(1) indexes
 * Handles both Deck.gl and MapLibre rendering paths
 */
function _doUpdateCoverageRenderingSync() {
    const startTime = performance.now();

    // Use a fresh object for coverage
    const newCoverage = {};
    let totalIds = 0;

    // Get filtered units using O(1) index lookup instead of O(n) iteration
    const filteredUnitIds = getFilteredUnitIds();

    const unitsArray = Object.keys(units_for_coverage);
    for (let i = 0; i < unitsArray.length; i++) {
        const unit = unitsArray[i];
        const coverage = units_for_coverage[unit];

        if (!coverage) continue;

        // Handle Set
        const size = coverage.size !== undefined ? coverage.size : Object.keys(coverage).length;
        if (size === 0) continue;

        // O(1) check: either all units (null), or check if unit is in filtered set
        const shouldCount = filteredUnitIds === null || filteredUnitIds.has(unit);

        if (shouldCount) {
            // Iterate Set or Object keys
            const iterator = coverage instanceof Set ? coverage : Object.keys(coverage);
            for (const way of iterator) {
                const id = typeof way === 'string' ? parseInt(way, 10) : way;
                newCoverage[id] = (newCoverage[id] || 0) + 1;
                totalIds++;
            }
        }
    }

    // Update global coverage
    global_coverage = newCoverage;

    const coveredCount = Object.keys(global_coverage).length;
    const elapsed = performance.now() - startTime;

    // Update display
    debugLog.updateStatus('covered_ids_count', coveredCount.toString());
    debugLog.log(`Coverage: ${coveredCount} unique IDs (${totalIds} total) in ${elapsed.toFixed(0)}ms`, 'info');

    // =========================================================================
    // Deck.gl path: Clear and rebuild coverage state, then update layer
    // =========================================================================
    if (USE_DECKGL_COVERAGE && window.deckglClearCoverageState && window.deckglApplyCoverageDeltas) {
        // Clear existing state
        window.deckglClearCoverageState();

        // Apply new coverage as deltas
        window.deckglApplyCoverageDeltas(newCoverage);

        // Update the Deck.gl layer
        updateDeckGLLayer();

        debugLog.log(`Deck.gl coverage rebuilt: ${coveredCount} buildings`, 'info');
        return;
    }

    // =========================================================================
    // MapLibre path: Trigger viewport update for setFeatureState
    // =========================================================================
    scheduleViewportUpdate();
}


// Track page state for SSE connection management
var isPageUnloading = false;
var isPageReady = false;
var kafka_handler_coverage_stream = null;
var kafka_handler_route_response = null;
var kafka_handler_main_stream = null;

// ============================================================================
// SSE Connection Manager - Robust reconnection with exponential backoff
// ============================================================================

class SSEConnectionManager {
    constructor(options = {}) {
        this.url = options.url;
        this.name = options.name || 'SSE';
        this.onMessage = options.onMessage || (() => {});
        this.onConnect = options.onConnect || (() => {});
        this.onError = options.onError || (() => {});

        // Reconnection configuration
        this.baseDelay = options.baseDelay || 1000;      // 1 second initial delay
        this.maxDelay = options.maxDelay || 30000;       // 30 seconds max delay
        this.maxRetries = options.maxRetries || 10;      // Max retries before giving up
        this.jitterFactor = options.jitterFactor || 0.3; // 30% jitter

        // State
        this.connection = null;
        this.retryCount = 0;
        this.currentDelay = this.baseDelay;
        this.reconnectTimeout = null;
        this.isConnecting = false;
        this.isClosed = false;
    }

    /**
     * Calculate delay with exponential backoff and jitter
     */
    calculateDelay() {
        // Exponential backoff: delay * 2^retryCount
        let delay = this.baseDelay * Math.pow(2, this.retryCount);
        delay = Math.min(delay, this.maxDelay);

        // Add jitter to prevent thundering herd
        const jitter = delay * this.jitterFactor * (Math.random() * 2 - 1);
        return Math.max(0, delay + jitter);
    }

    /**
     * Start the connection
     */
    connect() {
        if (this.isClosed || isPageUnloading || !isPageReady) return;
        if (this.isConnecting) return;

        this.isConnecting = true;
        debugLog.log(`[${this.name}] Connecting...`, 'info');

        try {
            this.connection = new EventSource(this.url);

            this.connection.onopen = () => {
                this.isConnecting = false;
                this.retryCount = 0;
                this.currentDelay = this.baseDelay;
                debugLog.log(`[${this.name}] Connected`, 'info');
                this.onConnect();
            };

            this.connection.onmessage = (event) => {
                try {
                    this.onMessage(event);
                } catch (err) {
                    console.error(`[${this.name}] Message handler error:`, err);
                    debugLog.log(`[${this.name}] Message error: ${err.message}`, 'error');
                }
            };

            this.connection.onerror = (event) => {
                this.isConnecting = false;
                debugLog.log(`[${this.name}] Connection error`, 'error');
                this.onError(event);
                this.handleDisconnect();
            };

        } catch (err) {
            this.isConnecting = false;
            console.error(`[${this.name}] Failed to create EventSource:`, err);
            this.handleDisconnect();
        }
    }

    /**
     * Handle disconnection and schedule reconnect
     */
    handleDisconnect() {
        if (this.isClosed || isPageUnloading) return;

        // Close existing connection
        if (this.connection) {
            this.connection.close();
            this.connection = null;
        }

        // Check retry limit
        if (this.retryCount >= this.maxRetries) {
            debugLog.log(`[${this.name}] Max retries (${this.maxRetries}) reached`, 'error');
            toast.error(
                `${this.name} Connection Failed`,
                `Unable to connect after ${this.maxRetries} attempts. Please refresh the page.`,
                0 // Don't auto-dismiss
            );
            return;
        }

        // Calculate delay and schedule reconnect
        const delay = this.calculateDelay();
        this.retryCount++;

        debugLog.log(`[${this.name}] Reconnecting in ${Math.round(delay/1000)}s (attempt ${this.retryCount}/${this.maxRetries})`, 'warn');

        this.reconnectTimeout = setTimeout(() => {
            this.connect();
        }, delay);
    }

    /**
     * Close the connection permanently
     */
    close() {
        this.isClosed = true;

        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }

        if (this.connection) {
            this.connection.close();
            this.connection = null;
        }

        debugLog.log(`[${this.name}] Closed`, 'info');
    }

    /**
     * Reset and reconnect
     */
    reset() {
        this.isClosed = false;
        this.retryCount = 0;
        this.currentDelay = this.baseDelay;
        this.connect();
    }
}

// SSE connection managers
let sseManagers = {};

// ============================================================================
// Toast Notification System
// ============================================================================

const toast = {
    container: null,

    init() {
        this.container = document.getElementById('toast_container');
    },

    show(title, message, type = 'info', duration = 5000) {
        if (!this.container) this.init();
        if (!this.container) return;

        const icons = {
            info: 'i',
            success: '\u2713',
            warning: '!',
            error: '\u2717'
        };

        const toastEl = document.createElement('div');
        toastEl.className = `toast toast-${type}`;
        toastEl.innerHTML = `
            <div class="toast-icon">${icons[type] || icons.info}</div>
            <div class="toast-content">
                <div class="toast-title">${title}</div>
                <div class="toast-message">${message}</div>
            </div>
            <button class="toast-close" aria-label="Close notification">&times;</button>
        `;

        const closeBtn = toastEl.querySelector('.toast-close');
        closeBtn.onclick = () => this.hide(toastEl);

        this.container.appendChild(toastEl);

        if (duration > 0) {
            setTimeout(() => this.hide(toastEl), duration);
        }

        return toastEl;
    },

    hide(toastEl) {
        if (!toastEl || !toastEl.parentNode) return;
        toastEl.classList.add('toast-hiding');
        setTimeout(() => {
            if (toastEl.parentNode) {
                toastEl.parentNode.removeChild(toastEl);
            }
        }, 300);
    },

    info(title, message, duration) {
        return this.show(title, message, 'info', duration);
    },

    success(title, message, duration) {
        return this.show(title, message, 'success', duration);
    },

    warning(title, message, duration) {
        return this.show(title, message, 'warning', duration);
    },

    error(title, message, duration = 8000) {
        return this.show(title, message, 'error', duration);
    }
};

// ============================================================================
// Connection Status Indicator
// ============================================================================

const connectionStatus = {
    element: null,
    textElement: null,
    streams: {
        coverage: 'unknown',
        route: 'unknown',
        main: 'unknown'
    },
    lastStatus: 'live',

    init() {
        this.element = document.getElementById('connection_status');
        this.textElement = this.element?.querySelector('.status-text');
    },

    update() {
        if (!this.element) this.init();
        if (!this.element) return;

        const statuses = Object.values(this.streams);
        const hasConnected = statuses.some(s => s === 'connected');
        const hasError = statuses.some(s => s === 'error');
        const hasConnecting = statuses.some(s => s === 'connecting');

        let newStatus;
        let text;

        if (hasError && !hasConnected) {
            newStatus = 'error';
            text = 'Disconnected';
        } else if (hasConnecting || (hasError && hasConnected)) {
            newStatus = 'reconnecting';
            text = 'Reconnecting...';
        } else if (hasConnected) {
            newStatus = 'live';
            text = 'Live';
        } else {
            newStatus = 'reconnecting';
            text = 'Connecting...';
        }

        // Only notify on status change
        if (this.lastStatus !== newStatus) {
            this.element.className = `connection-status connection-${newStatus}`;
            if (this.textElement) {
                this.textElement.textContent = text;
            }

            // Show toast on significant status changes
            if (newStatus === 'error' && this.lastStatus !== 'error') {
                toast.error('Connection Lost', 'Real-time data stream disconnected. Attempting to reconnect...');
            } else if (newStatus === 'live' && this.lastStatus === 'error') {
                toast.success('Connected', 'Real-time data stream restored.');
            }

            this.lastStatus = newStatus;
        }
    },

    setStreamStatus(streamName, status) {
        this.streams[streamName] = status;
        this.update();
    }
};

// Debug logging - gracefully handles missing debug panel in production
const debugLog = {
    maxLines: 50,
    lines: [],
    enabled: false,

    init() {
        this.enabled = document.getElementById('debug_panel') !== null;
    },

    log(msg, type = 'info') {
        if (!this.enabled) return;
        const time = new Date().toLocaleTimeString();
        this.lines.push({ time, msg, type });
        if (this.lines.length > this.maxLines) this.lines.shift();
        this.render();
    },

    render() {
        if (!this.enabled) return;
        const el = document.getElementById('debug_log');
        if (!el) return;
        el.innerHTML = this.lines.map(l =>
            `<div class="log-${l.type}">[${l.time}] ${l.msg}</div>`
        ).join('');
        el.scrollTop = el.scrollHeight;
    },

    updateStatus(id, value, className = '') {
        if (!this.enabled) return;
        const el = document.getElementById(id);
        if (el) {
            el.innerHTML = value;
            el.className = className;
        }
    }
};

// Initialize debug panel toggle
document.addEventListener('DOMContentLoaded', () => {
    // Initialize debug logging (checks if panel exists)
    debugLog.init();

    const panel = document.getElementById('debug_panel');
    const toggleBtn = document.getElementById('debug_toggle_btn');
    const closeBtn = document.getElementById('debug_close_btn');

    if (toggleBtn && panel) {
        toggleBtn.onclick = () => {
            panel.classList.toggle('collapsed');
        };
    }

    if (closeBtn && panel) {
        closeBtn.onclick = () => {
            panel.classList.add('collapsed');
        };
    }
});

window.addEventListener('beforeunload', function() {
    isPageUnloading = true;
    if (kafka_handler_coverage_stream) kafka_handler_coverage_stream.close();
    if (kafka_handler_route_response) kafka_handler_route_response.close();
    if (kafka_handler_main_stream) kafka_handler_main_stream.close();
});

// Stop & Exit: close all streams, call backend to flush Redis, redirect to home
document.addEventListener('DOMContentLoaded', function() {
    const stopBtn = document.getElementById('stop_exit_btn');
    if (!stopBtn) return;

    stopBtn.addEventListener('click', async function() {
        stopBtn.disabled = true;
        stopBtn.innerHTML = '<span class="stop-icon">&#x23F3;</span> Stopping...';

        // 1. Close all SSE streams immediately
        isPageUnloading = true;
        if (kafka_handler_coverage_stream) kafka_handler_coverage_stream.close();
        if (kafka_handler_route_response) kafka_handler_route_response.close();
        if (kafka_handler_main_stream) kafka_handler_main_stream.close();

        // 2. Call backend to flush Redis coverage/position data
        const citySlug = typeof __CITY_SLUG !== 'undefined' ? __CITY_SLUG : 'paris';
        try {
            const resp = await fetch(`/api/${citySlug}/stop`, { method: 'POST' });
            const result = await resp.json();
            console.log('[Stop] Backend response:', result);
        } catch (err) {
            console.warn('[Stop] Backend flush failed (non-critical):', err);
        }

        // 3. Redirect to home page
        window.location.href = '/';
    });
});

// Opens a connection to the server to begin receiving coverage events
function createCoverageStream() {
    if (isPageUnloading || !isPageReady) return null;

    debugLog.log('Connecting to coverage stream...', 'info');
    debugLog.updateStatus('coverage_sse_status', 'connecting...', 'status-pending');
    connectionStatus.setStreamStatus('coverage', 'connecting');

    var stream = new EventSource('/topic/' + KAFKA_TOPIC_COVERAGE_RESPONSE);

    stream.onopen = function() {
        console.log('[Coverage] Stream connected');
        debugLog.log('Coverage stream connected', 'info');
        debugLog.updateStatus('coverage_sse_status', 'connected', 'status-ok');
        connectionStatus.setStreamStatus('coverage', 'connected');
    };

    stream.onmessage = function(e) {
        try {
            debugLog.updateStatus('last_msg_time', new Date().toLocaleTimeString());
            const unit_coverage_update = JSON.parse(e.data);

            // Log first few IDs for debugging
            const firstUnit = unit_coverage_update.data?.[0];
            if (firstUnit) {
                const idCount = firstUnit.bld?.length || firstUnit.cov?.length || 0;
                console.log('[Coverage] unit', firstUnit.uni, 'IDs:', idCount);
                debugLog.log(`Coverage: unit ${firstUnit.uni}, ${idCount} IDs`, 'data');
            }

            update_coverage_data(unit_coverage_update);
        } catch (err) {
            console.error('[Coverage] Parse error:', err);
            debugLog.log(`Parse error: ${err.message}`, 'error');
        }
    };

    stream.onerror = function(e) {
        debugLog.log('Coverage stream error, reconnecting...', 'error');
        debugLog.updateStatus('coverage_sse_status', 'error', 'status-error');
        connectionStatus.setStreamStatus('coverage', 'error');
        stream.close();
        if (!isPageUnloading && isPageReady) {
            setTimeout(createCoverageStream, 2000);
        }
    };

    kafka_handler_coverage_stream = stream;
    return stream;
}


// Update coverage information
// Handles both "cov" (segment OSM IDs) and "bld" (building IDs) from backend
// NEW: Also handles "agg" (aggregated building coverage counts) for Deck.gl fast path
function update_coverage_data(units_data_update) {
    const startTime = performance.now();

    // =========================================================================
    // FAST PATH: Apply aggregated deltas directly to Deck.gl state (GPU)
    // This bypasses the expensive per-unit processing when backend sends agg data
    // =========================================================================
    if (USE_DECKGL_COVERAGE && units_data_update.agg && window.deckglApplyCoverageDeltas) {
        const updatedCount = window.deckglApplyCoverageDeltas(units_data_update.agg);
        const elapsed = performance.now() - startTime;

        debugLog.log(`Deck.gl fast path: ${updatedCount} deltas in ${elapsed.toFixed(1)}ms`, 'data');

        // Trigger Deck.gl layer update
        updateDeckGLLayer();

        // Still store per-unit data for filtering (if provided)
        if (units_data_update.data) {
            _storePerUnitCoverageData(units_data_update.data);
        }

        // Update stats display
        if (window.deckglGetCoverageStats) {
            const stats = window.deckglGetCoverageStats();
            debugLog.updateStatus('covered_ids_count', stats.totalCovered.toString());
        }

        return;
    }

    // =========================================================================
    // FALLBACK PATH: Per-unit processing (original code)
    // Used when Deck.gl is disabled or backend doesn't send agg data
    // =========================================================================
    let totalNewIds = 0;

    units_data_update['data'].forEach(function(unit_coverage_update) {
        var unit_to_update = unit_coverage_update['uni'];

        // Check for building IDs first (new format), then fall back to coverage IDs (original format)
        if ('bld' in unit_coverage_update) {
            // Convert string IDs to numbers (tiles have building_id as Number type)
            const numericIds = unit_coverage_update['bld'].map(id => parseInt(id, 10));
            units_for_coverage[unit_to_update] = new Set(numericIds);
            totalNewIds += numericIds.length;
            // Log sample IDs for debugging
            if (numericIds.length > 0) {
                debugLog.log(`Unit ${unit_to_update}: ${numericIds.length} bld IDs (sample: ${numericIds.slice(0, 3).join(',')})`, 'data');
            }
        } else if ('cov' in unit_coverage_update) {
            // Convert string IDs to numbers for roads too
            const numericIds = unit_coverage_update['cov'].map(id => parseInt(id, 10));
            units_for_coverage[unit_to_update] = new Set(numericIds);
            totalNewIds += numericIds.length;
        } else {
            units_for_coverage[unit_to_update] = new Set();
        }
    });

    if (totalNewIds > 0) {
        debugLog.log(`Coverage updated: ${totalNewIds} total IDs from ${units_data_update['data'].length} units`, 'info');
    }

    update_coverage_rendering();
}

/**
 * Store per-unit coverage data for filtering purposes
 * Called from fast path to maintain per-unit data alongside aggregated state
 */
function _storePerUnitCoverageData(unitsData) {
    unitsData.forEach(function(unit_coverage_update) {
        var unit_to_update = unit_coverage_update['uni'];

        if ('bld' in unit_coverage_update) {
            const numericIds = unit_coverage_update['bld'].map(id => parseInt(id, 10));
            units_for_coverage[unit_to_update] = new Set(numericIds);
        } else if ('cov' in unit_coverage_update) {
            const numericIds = unit_coverage_update['cov'].map(id => parseInt(id, 10));
            units_for_coverage[unit_to_update] = new Set(numericIds);
        } else {
            units_for_coverage[unit_to_update] = new Set();
        }
    });
}


// Track initialized coverage layers
let coverageLayersInitialized = false;
const MAX_COVERAGE_LEVELS = 10;

// Coverage state tracking - O(1) lookups
let coverageLookup = new Map(); // building_id -> coverage_level
let previousCoverageLookup = new Map(); // For delta updates

/**
 * Initialize coverage layers using feature-state based styling (FAST)
 * Instead of massive filter arrays, we use:
 * 1. A single layer with data-driven paint based on feature-state
 * 2. setFeatureState() for O(1) per-feature updates
 *
 * If USE_DECKGL_COVERAGE is true, uses Deck.gl MVTLayer instead (GPU-accelerated)
 */
function initCoverageLayers() {
    if (coverageLayersInitialized) return;

    // =========================================================================
    // Deck.gl path: GPU-accelerated coverage rendering
    // =========================================================================
    if (USE_DECKGL_COVERAGE) {
        const success = initDeckGLCoverage();
        if (success) {
            coverageLayersInitialized = true;
            debugLog.log('Coverage layers ready (Deck.gl GPU)', 'info');
            debugLog.updateStatus('layers_status', 'ready (Deck.gl)', 'status-ok');
            return;
        }
        // Fall through to MapLibre if Deck.gl init failed
        debugLog.log('Deck.gl init failed, falling back to MapLibre', 'warn');
    }

    // =========================================================================
    // MapLibre path: CPU-bound setFeatureState rendering
    // =========================================================================
    const filterProperty = COVERAGE_MODE === "buildings" ? "building_id" : "osm_id";
    debugLog.log(`Init layers: mode=${COVERAGE_MODE}, layer=${SOURCE_LAYER}`, 'info');
    debugLog.updateStatus('layers_status', 'initializing...', 'status-pending');

    try {
        // Reconfigure source with promoteId for feature state support
        const sourceConfig = map.getSource('composite');

        if (COVERAGE_MODE === "buildings") {
            // Single coverage layer with data-driven color based on feature-state
            map.addLayer({
                id: "buildings-coverage",
                type: "fill",
                source: "composite",
                "source-layer": SOURCE_LAYER,
                paint: {
                    // Data-driven color: check feature-state for coverage level
                    "fill-color": [
                        "case",
                        ["==", ["feature-state", "coverage"], 10], palette["10"] || "#006400",
                        ["==", ["feature-state", "coverage"], 9], palette["9"] || "#007800",
                        ["==", ["feature-state", "coverage"], 8], palette["8"] || "#008C00",
                        ["==", ["feature-state", "coverage"], 7], palette["7"] || "#00A000",
                        ["==", ["feature-state", "coverage"], 6], palette["6"] || "#00B400",
                        ["==", ["feature-state", "coverage"], 5], palette["5"] || "#00C800",
                        ["==", ["feature-state", "coverage"], 4], palette["4"] || "#00DC00",
                        ["==", ["feature-state", "coverage"], 3], palette["3"] || "#00F000",
                        ["==", ["feature-state", "coverage"], 2], palette["2"] || "#FFFF00",
                        ["==", ["feature-state", "coverage"], 1], palette["1"] || "#90EE90",
                        "#FF0000" // Default: uncovered (red)
                    ],
                    "fill-opacity": [
                        "case",
                        ["boolean", ["feature-state", "covered"], false], 0.75,
                        0.6 // Uncovered opacity
                    ],
                    "fill-outline-color": [
                        "case",
                        ["boolean", ["feature-state", "covered"], false], "#004400",
                        "#990000"
                    ]
                },
                filter: ["==", "$type", "Polygon"]
            });
            debugLog.log('Added unified coverage layer (feature-state)', 'info');

        } else {
            // Road mode - similar approach
            map.addLayer({
                id: "roads-coverage",
                type: "line",
                source: "composite",
                "source-layer": SOURCE_LAYER,
                paint: {
                    "line-color": [
                        "case",
                        [">=", ["feature-state", "coverage"], 1],
                        [
                            "interpolate", ["linear"], ["feature-state", "coverage"],
                            1, palette["1"] || "#90EE90",
                            5, palette["5"] || "#00C800",
                            10, palette["10"] || "#006400"
                        ],
                        "#FF0000"
                    ],
                    "line-width": { "base": 1.55, "stops": [[4, 0.25], [20, 30]] }
                },
                filter: ["==", "$type", "LineString"]
            });
        }

        coverageLayersInitialized = true;
        debugLog.log('Coverage layers ready (optimized)', 'info');
        debugLog.updateStatus('layers_status', 'ready', 'status-ok');

        // Add road graph overlay (hidden by default)
        _initRoadGraphLayer();
    } catch (e) {
        debugLog.log(`Layer init error: ${e.message}`, 'error');
        debugLog.updateStatus('layers_status', 'error', 'status-error');
        console.error('Coverage layer init error:', e);
    }
}

/**
 * Road graph overlay — same tiles as the Linkage Inspector
 */
function _initRoadGraphLayer() {
    try {
        map.addSource('roads-graph', {
            type: 'vector',
            tiles: [ROAD_TILESOURCE_URL],
            minzoom: 12,
            maxzoom: 17
        });

        map.addLayer({
            id: 'roads-graph-casing',
            type: 'line',
            source: 'roads-graph',
            'source-layer': ROAD_SOURCE_LAYER,
            paint: {
                'line-color': '#000',
                'line-width': ['interpolate', ['linear'], ['zoom'], 12, 2, 17, 5],
                'line-opacity': 0.25
            },
            layout: { 'visibility': 'none' }
        });

        map.addLayer({
            id: 'roads-graph-line',
            type: 'line',
            source: 'roads-graph',
            'source-layer': ROAD_SOURCE_LAYER,
            paint: {
                'line-color': '#b0b0b0',
                'line-width': ['interpolate', ['linear'], ['zoom'], 12, 1.2, 17, 3.5],
                'line-opacity': 0.8
            },
            layout: { 'visibility': 'none' }
        });

        // Toggle handler
        const toggle = document.getElementById('togBtnRoadGraph');
        if (toggle) {
            toggle.addEventListener('change', function () {
                const vis = this.checked ? 'visible' : 'none';
                map.setLayoutProperty('roads-graph-casing', 'visibility', vis);
                map.setLayoutProperty('roads-graph-line', 'visibility', vis);
            });
        }
    } catch (e) {
        console.warn('[roads-graph] Could not init road graph layer:', e);
    }
}

// Coverage state tracking
let viewportFeaturesUpdated = new Set(); // Track which features have been updated
let pendingViewportUpdate = false;

// Track which features have been updated to avoid redundant updates
const updatedFeatureStates = new Map(); // featureId -> coverageLevel

// Frame budget configuration for smooth rendering
const FRAME_BUDGET_MS = 12; // Target 12ms to stay under 16.67ms for 60fps
const MIN_UPDATES_PER_FRAME = 500;
const MAX_UPDATES_PER_FRAME_CAP = 5000;

// Adaptive updates tracking
let adaptiveUpdatesPerFrame = 2000;
let frameTimeSamples = [];
const SAMPLE_WINDOW = 5;

/**
 * Update coverage for VISIBLE features only (viewport-based)
 * OPTIMIZED: Dynamic frame budget, adaptive batch sizing for smooth rendering
 */
function updateVisibleFeaturesCoverage() {
    if (!coverageLayersInitialized || !map.isStyleLoaded()) return;

    const startTime = performance.now();
    const layerId = COVERAGE_MODE === "buildings" ? "buildings-coverage" : "roads-coverage";
    const idProperty = COVERAGE_MODE === "buildings" ? "building_id" : "osm_id";

    // Query only VISIBLE features in current viewport
    const visibleFeatures = map.queryRenderedFeatures({ layers: [layerId] });

    if (visibleFeatures.length === 0) return;

    // Deduplicate features (same building can appear in multiple tiles)
    const uniqueFeatures = new Map();
    for (const feature of visibleFeatures) {
        const featureId = feature.properties[idProperty];
        if (featureId !== undefined && !uniqueFeatures.has(featureId)) {
            uniqueFeatures.set(featureId, feature);
        }
    }

    let updatedCount = 0;
    let continueProcessing = true;

    for (const [featureId, feature] of uniqueFeatures) {
        // Dynamic frame budget check: stop if we've exceeded time budget
        if (updatedCount > 0 && updatedCount % 100 === 0) {
            const elapsed = performance.now() - startTime;
            if (elapsed >= FRAME_BUDGET_MS) {
                // Schedule remaining updates for next frame
                requestAnimationFrame(() => updateVisibleFeaturesCoverage());
                continueProcessing = false;
                break;
            }
        }

        // Also respect max updates cap
        if (updatedCount >= adaptiveUpdatesPerFrame) {
            requestAnimationFrame(() => updateVisibleFeaturesCoverage());
            continueProcessing = false;
            break;
        }

        const coverageLevel = global_coverage[featureId] || 0;
        const cappedLevel = Math.min(coverageLevel, MAX_COVERAGE_LEVELS);

        // Check our cache first (faster than getFeatureState)
        const cachedLevel = updatedFeatureStates.get(featureId);

        // Only update if coverage changed
        if (cachedLevel !== cappedLevel) {
            map.setFeatureState(
                { source: 'composite', sourceLayer: SOURCE_LAYER, id: featureId },
                { covered: cappedLevel > 0, coverage: cappedLevel }
            );
            updatedFeatureStates.set(featureId, cappedLevel);
            updatedCount++;
        }
    }

    const elapsed = performance.now() - startTime;

    // Adaptive batch sizing based on frame time
    if (updatedCount > 0) {
        frameTimeSamples.push({ updates: updatedCount, time: elapsed });
        if (frameTimeSamples.length > SAMPLE_WINDOW) {
            frameTimeSamples.shift();
        }

        // Adjust batch size based on average performance
        if (frameTimeSamples.length >= 3) {
            const avgTimePerUpdate = frameTimeSamples.reduce((sum, s) => sum + s.time / s.updates, 0) / frameTimeSamples.length;
            const targetUpdates = Math.floor(FRAME_BUDGET_MS / avgTimePerUpdate);
            adaptiveUpdatesPerFrame = Math.max(MIN_UPDATES_PER_FRAME, Math.min(MAX_UPDATES_PER_FRAME_CAP, targetUpdates));
        }
    }

    // Update stats
    debugLog.updateStatus('visible_features_count', uniqueFeatures.size.toString());
    debugLog.updateStatus('covered_ids_count', Object.keys(global_coverage).length.toString());

    if (updatedCount > 0 || elapsed > 50) {
        debugLog.log(`Viewport: ${updatedCount}/${uniqueFeatures.size} in ${elapsed.toFixed(0)}ms (budget: ${adaptiveUpdatesPerFrame})`, 'data');
    }
}

// Debounced viewport update (triggered on map move/zoom)
let viewportUpdateTimeout = null;
let viewportUpdateScheduled = false;

function scheduleViewportUpdate() {
    // Skip viewport updates when using Deck.gl - it handles its own rendering
    if (USE_DECKGL_COVERAGE && deckOverlay) {
        return;
    }

    if (viewportUpdateScheduled) return;
    viewportUpdateScheduled = true;

    // Use requestAnimationFrame for smooth updates
    requestAnimationFrame(() => {
        viewportUpdateScheduled = false;
        if (map && map.isStyleLoaded()) {
            updateVisibleFeaturesCoverage();
        }
    });
}

/**
 * Update coverage lookup and trigger viewport update
 * Fast: only builds the lookup Map, actual rendering is viewport-based
 */
function update_coverage_on_filter() {
    if (!coverageLayersInitialized) {
        debugLog.log('Layers not ready yet', 'warn');
        return;
    }

    const startTime = performance.now();

    // Count total covered IDs (for stats only)
    let totalCovered = 0;
    for (const id in global_coverage) {
        if (global_coverage[id] > 0) totalCovered++;
    }

    // Update debug display
    debugLog.updateStatus('covered_ids_count', totalCovered.toString());

    const elapsed = performance.now() - startTime;
    debugLog.log(`Coverage lookup: ${totalCovered} IDs (${elapsed.toFixed(1)}ms)`, 'data');

    // For Deck.gl, trigger layer update instead of viewport update
    if (USE_DECKGL_COVERAGE && deckOverlay) {
        updateDeckGLLayer();
        return;
    }

    // Update only visible features (MapLibre path)
    scheduleViewportUpdate();
}

// Helper function to adjust color brightness for outline
function adjustColorBrightness(hexColor, amount) {
    // Handle hex colors
    let color = hexColor.replace('#', '');
    if (color.length === 3) {
        color = color[0] + color[0] + color[1] + color[1] + color[2] + color[2];
    }

    let r = parseInt(color.substring(0, 2), 16);
    let g = parseInt(color.substring(2, 4), 16);
    let b = parseInt(color.substring(4, 6), 16);

    r = Math.max(0, Math.min(255, r + amount));
    g = Math.max(0, Math.min(255, g + amount));
    b = Math.max(0, Math.min(255, b + amount));

    return '#' + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
}


/**
 * Route handling - using MapLibre line layers
 */

/**
 * Add a route to MapLibre with glow effect
 */
function addRoute(unitId, coordinates, options = {}) {
    const sourceId = `route-${unitId}`;
    const glowLayerId = `route-glow-${unitId}`;
    const bgLayerId = `route-bg-${unitId}`;
    const lineLayerId = `route-line-${unitId}`;

    // Remove existing route if any
    removeRoute(unitId);

    // Store the layer IDs for later reference
    units[unitId].routeSourceId = sourceId;
    units[unitId].routeLayerId = lineLayerId;
    units[unitId].routeGlowLayerId = glowLayerId;
    units[unitId].routeBgLayerId = bgLayerId;

    const color = options.color || '#0066FF';

    // Add the source
    map.addSource(sourceId, {
        type: 'geojson',
        data: {
            type: 'Feature',
            geometry: {
                type: 'LineString',
                coordinates: coordinates.map(coord => [coord[1], coord[0]]) // [lon, lat]
            }
        }
    });

    // Layer 1: Outer glow (wide, transparent)
    map.addLayer({
        id: glowLayerId,
        type: 'line',
        source: sourceId,
        paint: {
            'line-color': color,
            'line-width': 12,
            'line-opacity': 0.15,
            'line-blur': 4
        }
    });

    // Layer 2: Inner glow / background
    map.addLayer({
        id: bgLayerId,
        type: 'line',
        source: sourceId,
        paint: {
            'line-color': color,
            'line-width': 6,
            'line-opacity': 0.3,
            'line-blur': 1
        }
    });

    // Layer 3: Main dashed line
    map.addLayer({
        id: lineLayerId,
        type: 'line',
        source: sourceId,
        paint: {
            'line-color': '#FFFFFF',
            'line-width': 2,
            'line-opacity': 0.9,
            'line-dasharray': [2, 3]
        }
    });
}

/**
 * Remove a route from MapLibre
 */
function removeRoute(unitId) {
    if (!units[unitId]) return;

    const sourceId = units[unitId].routeSourceId;
    const layerIds = [
        units[unitId].routeLayerId,
        units[unitId].routeGlowLayerId,
        units[unitId].routeBgLayerId
    ];

    try {
        // Remove all layers first
        layerIds.forEach(layerId => {
            if (layerId && map.getLayer(layerId)) {
                map.removeLayer(layerId);
            }
        });
        // Then remove the source
        if (sourceId && map.getSource(sourceId)) {
            map.removeSource(sourceId);
        }
    } catch (e) {
        // Layer/source may already be removed
    }

    delete units[unitId].routeSourceId;
    delete units[unitId].routeLayerId;
    delete units[unitId].routeGlowLayerId;
    delete units[unitId].routeBgLayerId;
}

/**
 * Set route visibility
 */
function setRouteVisibility(unitId, visible) {
    const layerIds = [
        units[unitId]?.routeLayerId,
        units[unitId]?.routeGlowLayerId,
        units[unitId]?.routeBgLayerId
    ];

    const visibility = visible ? 'visible' : 'none';

    try {
        layerIds.forEach(layerId => {
            if (layerId && map.getLayer(layerId)) {
                map.setLayoutProperty(layerId, 'visibility', visibility);
            }
        });
    } catch (e) {
        // Layer may not exist
    }
}


// Opens a connection to the server to begin receiving route events
function createRouteStream() {
    if (isPageUnloading || !isPageReady) return null;

    debugLog.log('Connecting to route stream...', 'info');
    debugLog.updateStatus('route_sse_status', 'connecting...', 'status-pending');
    connectionStatus.setStreamStatus('route', 'connecting');

    var stream = new EventSource('/topic/' + KAFKA_TOPIC_ROUTE_RESPONSE);

    stream.addEventListener('open', function() {
        debugLog.log('Route stream connected', 'info');
        debugLog.updateStatus('route_sse_status', 'connected', 'status-ok');
        connectionStatus.setStreamStatus('route', 'connected');
    });

    stream.addEventListener('message', function(e) {
        var ROUTE_RESPONSE = JSON.parse(e.data);
        var date = ROUTE_RESPONSE.date;
        debugLog.log(`Routes: ${ROUTE_RESPONSE.routes?.length || 0} routes`, 'data');

        ROUTE_RESPONSE['routes'].forEach(function(route_response) {
            // Skip if unit not loaded yet
            if (!units[route_response.uni]) return;
            if (units[route_response.uni].date == date) {
                var route_coordinates;

                if ('route' in route_response) {
                    route_coordinates = route_response.route;
                } else {
                    // Straight line from gp1 to gp2
                    route_coordinates = [route_response.gp1, route_response.gp2];
                }

                // Add route to MapLibre
                addRoute(route_response.uni, route_coordinates, {
                    color: "#0000FF",
                    weight: 4,
                    opacity: 0.7
                });

                // Check display selection and set visibility
                if (!(
                    selection_type == "all" ||
                    (selection_type == "category" && sub_selection_type == units[route_response.uni].cat) ||
                    (selection_type == "competence" && units[route_response.uni].competences &&
                     units[route_response.uni].competences.includes(sub_selection_type))
                )) {
                    setRouteVisibility(route_response.uni, false);
                }
            }
        });
    }, false);

    stream.onerror = function(e) {
        debugLog.log('Route stream error, reconnecting...', 'warn');
        debugLog.updateStatus('route_sse_status', 'error', 'status-error');
        connectionStatus.setStreamStatus('route', 'error');
        stream.close();
        if (!isPageUnloading && isPageReady) {
            setTimeout(createRouteStream, 2000);
        }
    };
    kafka_handler_route_response = stream;
    return stream;
}


// Opens a connection to the server to begin receiving main stream events
function createMainStream() {
    if (isPageUnloading || !isPageReady) return null;

    debugLog.log('Connecting to main stream...', 'info');
    debugLog.updateStatus('main_sse_status', 'connecting...', 'status-pending');
    connectionStatus.setStreamStatus('main', 'connecting');

    var stream = new EventSource('/topic/' + KAFKA_TOPIC_MAIN_STREAM);

    stream.onopen = function() {
        console.log('[Main] Stream connected');
        debugLog.log('Main stream connected', 'info');
        debugLog.updateStatus('main_sse_status', 'connected', 'status-ok');
        connectionStatus.setStreamStatus('main', 'connected');
    };

    stream.onmessage = function(e) {
        try {
            debugLog.updateStatus('last_msg_time', new Date().toLocaleTimeString());
            var units_data_update = JSON.parse(e.data);
            debugLog.log(`Main: ${units_data_update.data?.length || 0} units, date=${units_data_update.date}`, 'data');
            update_units_data(units_data_update);
        } catch (err) {
            console.error('[Main] Parse error:', err);
            debugLog.log(`Main parse error: ${err.message}`, 'error');
        }
    };

    stream.onerror = function(e) {
        debugLog.log('Main stream error, reconnecting...', 'error');
        debugLog.updateStatus('main_sse_status', 'error', 'status-error');
        connectionStatus.setStreamStatus('main', 'error');
        stream.close();
        if (!isPageUnloading && isPageReady) {
            setTimeout(createMainStream, 2000);
        }
    };
    kafka_handler_main_stream = stream;
    return stream;
}

// Initialize all SSE streams - call this after page is ready
async function initializeStreams() {
    console.log('[Streams] initializeStreams called');
    isPageReady = true;

    // Initialize toast and connection status systems
    toast.init();
    connectionStatus.init();

    // Fetch coverage snapshot for instant display (before SSE streams)
    console.log('[Streams] About to fetch coverage snapshot...');
    await fetchCoverageSnapshot();
    console.log('[Streams] Coverage snapshot fetch complete');

    debugLog.log('Starting SSE streams...', 'info');
    debugLog.updateStatus('stream_status', 'connecting...', 'status-pending');
    createCoverageStream();
    createRouteStream();
    createMainStream();
    debugLog.updateStatus('stream_status', 'active', 'status-ok');
}

/**
 * Fetch coverage snapshot from API for instant page load
 * Applies to Deck.gl before SSE streams start
 */
async function fetchCoverageSnapshot() {
    console.log('[Snapshot] fetchCoverageSnapshot called, USE_DECKGL_COVERAGE=', USE_DECKGL_COVERAGE);

    // Deck.gl path (original)
    if (USE_DECKGL_COVERAGE) {
        debugLog.log('Fetching coverage snapshot (Deck.gl)...', 'info');
        try {
            const cityService = (typeof SERVICE !== 'undefined') ? SERVICE : 'paris';
            console.log('[Snapshot] Fetching from /api/coverage/snapshot?service=' + cityService);
            const response = await fetch('/api/coverage/snapshot?service=' + encodeURIComponent(cityService));
            console.log('[Snapshot] Response status:', response.status);
            if (!response.ok) { console.warn('[Snapshot] Bad response:', response.status); return; }
            const snapshot = await response.json();
            const buildingCount = Object.keys(snapshot).length;
            console.log('[Snapshot] Parsed:', buildingCount, 'buildings, deckglApply:', !!window.deckglApplyCoverageDeltas);
            if (buildingCount > 0 && window.deckglApplyCoverageDeltas) {
                const updated = window.deckglApplyCoverageDeltas(snapshot);
                console.log('[Snapshot] Applied deltas:', updated, 'updated, stateSize:', window.deckglGetCoverageState ? window.deckglGetCoverageState().size : '?');
                updateDeckGLLayer();
                debugLog.log(`Snapshot loaded: ${buildingCount} buildings`, 'info');
                debugLog.updateStatus('covered_ids_count', buildingCount.toString());
            } else {
                console.warn('[Snapshot] NOT applied: count=', buildingCount, 'fn=', !!window.deckglApplyCoverageDeltas);
            }
        } catch (err) {
            console.error('[Snapshot] Error:', err);
            debugLog.log(`Snapshot error: ${err.message}`, 'error');
        }
        return;
    }

    // MapLibre feature-state path: compute coverage via Python backend
    const citySlug = (typeof __CITY_SLUG !== 'undefined') ? __CITY_SLUG : '';
    if (!citySlug) return;

    debugLog.log('Computing coverage snapshot...', 'info');
    try {
        const response = await fetch('/api/' + citySlug + '/coverage/compute');
        if (!response.ok) return;
        const result = await response.json();
        const agg = result.agg || {};
        const count = Object.keys(agg).length;
        console.log('[Snapshot] Python coverage computed:', count, 'buildings');

        if (count > 0 && COVERAGE_MODE === 'buildings') {
            // Apply as feature-state to building tiles
            const source = 'composite';
            const sourceLayer = SOURCE_LAYER;
            for (const [bid, level] of Object.entries(agg)) {
                map.setFeatureState(
                    { source, sourceLayer, id: bid },
                    { covered: true, coverage: Math.min(level, 10) }
                );
            }
            debugLog.log(`Coverage snapshot: ${count} buildings colored`, 'info');
            debugLog.updateStatus('covered_ids_count', count.toString());
        }

        // Also store per-unit data for filtering
        if (result.data) {
            for (const unit_cov of result.data) {
                const uid = unit_cov.uni;
                if (!units_for_coverage[uid]) units_for_coverage[uid] = {};
                for (const bid of (unit_cov.bld || [])) {
                    units_for_coverage[uid][bid] = true;
                }
            }
        }
    } catch (err) {
        console.warn('[Snapshot] Coverage compute error:', err);
    }
}


/**
 * Update units data from main stream
 */
function update_units_data(units_data_update) {
    // Update timestamp (if element exists)
    var datetimeEl = document.getElementById("datetime");
    if (datetimeEl) {
        datetimeEl.innerHTML = units_data_update.date;
    }

    // Update units count in debug panel
    debugLog.updateStatus('units_count', Object.keys(units).length.toString());

    // Process each unit update
    units_data_update.data.forEach(function(unit_update) {
        var unitId = unit_update.uni[0];

        // If unit is known, remove from cluster and indexes before re-adding
        if (units[unitId]) {
            // Remove from indexes (O(1) lookup maintenance)
            removeUnitFromIndexes(unitId);

            // Remove from donut cluster
            if (donutCluster) {
                donutCluster.removeUnit(unitId);
            }

            // Remove route if exists
            if (units[unitId].routeLayerId) {
                removeRoute(unitId);
            }
        } else {
            // Create new unit entry
            units[unitId] = {};
        }

        // Store update date
        units[unitId].date = units_data_update.date;

        // Unit category handling
        if (![null, -1].includes(unit_update.uni[1])) {
            var unit_category = parseInt(unit_update.uni[1]);
            units[unitId].cat = unit_category;

            // Track discovered categories for dropdown
            if (!(unit_category in categories_discovered)) {
                categories_discovered[unit_category] = unit_categories["code"][unit_category];
                rebuildCategoriesDropdown();
            }
        }

        // Unit competences handling
        if (unit_update.uni.length >= 4 && ![null, -1, []].includes(unit_update.uni[3])) {
            units[unitId].competences = unit_update.uni[3];

            unit_update.uni[3].forEach(function(competence) {
                competence = parseInt(competence);
                if (!(competence in competences_discovered)) {
                    competences_discovered[competence] = unit_competences["code"][competence];
                    rebuildCompetencesDropdown();
                }
            });
        }

        // Unit's parking station handling
        if (![null, -1].includes(unit_update.uni[2])) {
            units[unitId].station = unit_update.uni[2];
        }

        // Status id handling
        if (unit_update.sta[0] != null) {
            units[unitId].status = unit_update.sta[0];
        }

        var marker_color = "grey";
        if (units[unitId].status && STATUS["color"]) {
            marker_color = STATUS["color"][units[unitId].status];
        }

        // Add/update unit in donut cluster if we have GPS position
        if (unit_update.gp1 != null) {
            if (donutCluster) {
                donutCluster.addUnit(
                    unitId,
                    unit_update.gp1[0],  // lat
                    unit_update.gp1[1],  // lon
                    units[unitId].status,
                    {
                        cat: units[unitId].cat,
                        station: units[unitId].station,
                        competences: units[unitId].competences
                    }
                );
            }

            // Store position for reference
            units[unitId].lat = unit_update.gp1[0];
            units[unitId].lon = unit_update.gp1[1];
        }

        // Add unit to indexes for O(1) filtering
        addUnitToIndexes(unitId, units[unitId].cat, units[unitId].competences);

        // Intervention handling
        handleInterventionUpdate(unit_update, units_data_update.date);
    });
}


/**
 * Handle intervention updates
 */
function handleInterventionUpdate(unit_update, date) {
    var unitId = unit_update.uni[0];

    if (!units[unitId].status) return;

    // Check if unit was on a different intervention before
    if (units[unitId].intervention && unit_update.int && ![null, -1].includes(unit_update.int[0]) &&
        units[unitId].intervention != unit_update.int[0]) {
        var oldIntervention = units[unitId].intervention;
        if (interventions[oldIntervention]) {
            interventions[oldIntervention].units.delete(unitId);
            if (interventions[oldIntervention].units.size == 0) {
                removeInterventionMarker(oldIntervention);
                delete interventions[oldIntervention];
            }
        }
        delete units[unitId].intervention;
    }

    // Check if unit is on an intervention
    var isOnIntervention = STATUS["source_poi_type_id"] &&
        (parseInt(STATUS["source_poi_type_id"][units[unitId].status]) == 1 ||
         parseInt(STATUS["target_poi_type_id"][units[unitId].status]) == 1);

    if (isOnIntervention && unit_update.int != null && ![null, -1].includes(unit_update.int[0])) {
        units[unitId].intervention = unit_update.int[0];

        if (!interventions[unit_update.int[0]]) {
            interventions[unit_update.int[0]] = {
                units: new Set()
            };
        }

        // Add intervention marker at target position (gp2)
        if (unit_update.gp2 && !interventionMarkers[unit_update.int[0]]) {
            addInterventionMarker(unit_update.int[0], unit_update.gp2[0], unit_update.gp2[1]);
        }

        interventions[unit_update.int[0]].units.add(unitId);
    } else {
        // Unit no longer on intervention
        if (units[unitId].intervention) {
            var intervention = units[unitId].intervention;
            if (interventions[intervention]) {
                interventions[intervention].units.delete(unitId);
                if (interventions[intervention].units.size == 0) {
                    removeInterventionMarker(intervention);
                    delete interventions[intervention];
                }
            }
            delete units[unitId].intervention;
        }
    }
}


/**
 * Add intervention marker to map
 */
function addInterventionMarker(interventionId, lat, lon) {
    const el = document.createElement('div');
    el.className = 'intervention-marker';
    el.innerHTML = `<img src="${IMG_CALL.img}" width="${IMG_CALL.width}" height="${IMG_CALL.height}" />`;
    el.style.cursor = 'pointer';

    const marker = new maplibregl.Marker({ element: el })
        .setLngLat([lon, lat])
        .addTo(map);

    // Add popup
    const popup = new maplibregl.Popup({ offset: 25 })
        .setText(`Intervention: ${interventionId}`);

    el.addEventListener('click', () => {
        popup.setLngLat([lon, lat]).addTo(map);
    });

    interventionMarkers[interventionId] = marker;
}

/**
 * Remove intervention marker from map
 */
function removeInterventionMarker(interventionId) {
    if (interventionMarkers[interventionId]) {
        interventionMarkers[interventionId].remove();
        delete interventionMarkers[interventionId];
    }
}


/**
 * Rebuild categories dropdown
 */
function rebuildCategoriesDropdown() {
    var dropdown = "<option value='' selected disabled hidden>Filter by category</option>";
    for (var id in categories_discovered) {
        const selected = (selection_type === 'category' && sub_selection_type == id) ? ' selected' : '';
        dropdown += "<option value='" + id + "'" + selected + ">" + categories_discovered[id] + "</option>";
    }
    document.getElementById("categories_dropdownlist").innerHTML = dropdown;

    // If filter was restored from URL, apply it now that dropdown is populated
    if (selection_type === 'category' && sub_selection_type !== null && categories_discovered[sub_selection_type]) {
        update_coverage_rendering();
    }
}

/**
 * Rebuild competences dropdown
 */
function rebuildCompetencesDropdown() {
    var dropdown = "<option value='' selected disabled hidden>Filter by competence</option>";
    for (var id in competences_discovered) {
        const selected = (selection_type === 'competence' && sub_selection_type == id) ? ' selected' : '';
        dropdown += "<option value='" + id + "'" + selected + ">" + competences_discovered[id] + "</option>";
    }
    document.getElementById("competences_dropdownlist").innerHTML = dropdown;

    // If filter was restored from URL, apply it now that dropdown is populated
    if (selection_type === 'competence' && sub_selection_type !== null && competences_discovered[sub_selection_type]) {
        update_coverage_rendering();
    }
}


async function initialize_geopositions_and_status(url) {
    var api_response = await http_get(url, true);
    if (api_response) {
        JSON.parse(api_response).forEach(function(units_states_group_by_date) {
            update_units_data(units_states_group_by_date);
        });
    }
}

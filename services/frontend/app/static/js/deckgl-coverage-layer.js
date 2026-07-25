/**
 * Deck.gl Coverage Layer for GPU-accelerated building coverage rendering
 *
 * This module provides a high-performance alternative to MapLibre's setFeatureState()
 * by using Deck.gl's MVTLayer which renders directly on the GPU.
 *
 * Expected improvement: 60fps pan/zoom, ~20ms coverage updates (vs 50-200ms)
 *
 * Uses global deck object from CDN (no ES module imports)
 */

// Coverage state - Map for O(1) lookups
const deckglCoverageState = new Map();
let deckglStateVersion = 0;

// Color scale (matches existing palette from global_variables_initializer.js)
// Index corresponds to coverage count: 0=red (uncovered), 1-10=yellow->cyan gradient
const DECKGL_COVERAGE_COLORS = [
    [255, 0, 0, 180],      // 0: red (uncovered)
    [255, 209, 0, 190],    // 1: yellow
    [240, 255, 0, 190],    // 2
    [207, 255, 0, 190],    // 3
    [169, 255, 0, 190],    // 4
    [121, 255, 0, 190],    // 5: lime
    [26, 255, 0, 190],     // 6
    [0, 255, 125, 190],    // 7
    [0, 255, 188, 190],    // 8
    [0, 254, 231, 190],    // 9
    [5, 247, 255, 190],    // 10+: cyan
];

// Line colors for coverage outlines
const DECKGL_COVERED_LINE_COLOR = [0, 68, 0, 255];    // Dark green
const DECKGL_UNCOVERED_LINE_COLOR = [153, 0, 0, 255]; // Dark red

/**
 * Create the MVT coverage layer
 * Uses global deck.MVTLayer from CDN
 */
function deckglCreateCoverageLayer(tileUrl, sourceLayer, idProperty) {
    idProperty = idProperty || 'building_id';

    // Check if deck.gl is loaded
    if (typeof deck === 'undefined' || !deck.MVTLayer) {
        console.error('[Deck.gl] Library not loaded');
        return null;
    }

    return new deck.MVTLayer({
        id: 'coverage-buildings',
        data: tileUrl,
        minZoom: 12,
        maxZoom: 17,

        // Inline color lookup — avoids Map.get() + parseInt per feature per frame
        getFillColor: function(feature) {
            var featureId = feature.properties[idProperty];
            var coverage = deckglCoverageState.get(featureId) || 0;
            return DECKGL_COVERAGE_COLORS[Math.min(coverage, 10)];
        },

        getLineColor: function(feature) {
            var featureId = feature.properties[idProperty];
            return deckglCoverageState.has(featureId) ? DECKGL_COVERED_LINE_COLOR : DECKGL_UNCOVERED_LINE_COLOR;
        },

        lineWidthMinPixels: 1,

        // Update triggers - layer re-renders when stateVersion changes
        updateTriggers: {
            getFillColor: [deckglStateVersion],
            getLineColor: [deckglStateVersion]
        },

        // Disable picking — saves per-frame GPU overhead during pan/zoom
        pickable: false,
        autoHighlight: false
    });
}

/**
 * Apply coverage deltas from backend aggregated data
 * Fast path: directly updates the coverage state Map
 */
function deckglApplyCoverageDeltas(aggregatedData) {
    if (!aggregatedData || typeof aggregatedData !== 'object') return 0;

    var updatedCount = 0;

    var keys = Object.keys(aggregatedData);
    for (var i = 0; i < keys.length; i++) {
        var buildingId = keys[i];
        var count = aggregatedData[buildingId];
        // Use same key type as tiles provide (keep as-is for Map lookup match)
        var id = +buildingId;

        if (count <= 0) {
            if (deckglCoverageState.has(id)) {
                deckglCoverageState.delete(id);
                updatedCount++;
            }
        } else {
            if (deckglCoverageState.get(id) !== count) {
                deckglCoverageState.set(id, count);
                updatedCount++;
            }
        }
    }

    // Increment version to trigger layer re-render
    if (updatedCount > 0) {
        deckglStateVersion++;
    }

    return updatedCount;
}

/**
 * Get current state version for layer update triggers
 */
function deckglGetStateVersion() {
    return deckglStateVersion;
}

/**
 * Get coverage state Map (for filtering and stats)
 */
function deckglGetCoverageState() {
    return deckglCoverageState;
}

/**
 * Get coverage count for a specific building
 */
function deckglGetCoverage(buildingId) {
    return deckglCoverageState.get(buildingId) || 0;
}

/**
 * Clear all coverage state (used for reset/filter changes)
 */
function deckglClearCoverageState() {
    deckglCoverageState.clear();
    deckglStateVersion++;
}

/**
 * Set coverage for a specific building (used for per-unit fallback)
 */
function deckglSetCoverage(buildingId, count) {
    if (count <= 0) {
        deckglCoverageState.delete(buildingId);
    } else {
        deckglCoverageState.set(buildingId, count);
    }
}

/**
 * Get statistics about current coverage state
 */
function deckglGetCoverageStats() {
    var maxCoverage = 0;
    var totalCovered = 0;

    deckglCoverageState.forEach(function(count) {
        if (count > 0) totalCovered++;
        if (count > maxCoverage) maxCoverage = count;
    });

    return {
        totalBuildings: deckglCoverageState.size,
        totalCovered: totalCovered,
        maxCoverage: maxCoverage,
        stateVersion: deckglStateVersion
    };
}

/**
 * Create the MapboxOverlay for integrating Deck.gl with MapLibre
 * Uses global deck.MapboxOverlay from CDN
 */
function deckglCreateOverlay(layers) {
    if (typeof deck === 'undefined' || !deck.MapboxOverlay) {
        console.error('[Deck.gl] MapboxOverlay not loaded');
        return null;
    }

    return new deck.MapboxOverlay({
        interleaved: true,
        layers: layers
    });
}

// Expose functions globally for controller.js
window.deckglCreateCoverageLayer = deckglCreateCoverageLayer;
window.deckglApplyCoverageDeltas = deckglApplyCoverageDeltas;
window.deckglGetStateVersion = deckglGetStateVersion;
window.deckglGetCoverageState = deckglGetCoverageState;
window.deckglClearCoverageState = deckglClearCoverageState;
window.deckglGetCoverageStats = deckglGetCoverageStats;
window.deckglCreateOverlay = deckglCreateOverlay;

// Check if deck.gl loaded successfully
if (typeof deck !== 'undefined') {
    window.DeckGLMapboxOverlay = deck.MapboxOverlay;
    console.log('[Deck.gl] Library loaded successfully');
} else {
    window.DeckGLMapboxOverlay = null;
    console.error('[Deck.gl] Library not loaded - CDN scripts may have failed');
}

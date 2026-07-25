/**
 * Main entry point for Vite bundling
 *
 * This file imports all app modules and exposes them globally for compatibility
 * with the existing codebase. Gradually migrate to ES modules over time.
 */

// CSS
import '@static/styles/main.css'

// Configuration (must be first - defines constants)
import '@static/configuration_settings.js'

// Global variables initialization
import '@static/js/global_variables_initializer.js'

// Deck.gl coverage layer (GPU-accelerated rendering)
import {
    createCoverageLayer as deckglCreateCoverageLayer,
    applyCoverageDeltas as deckglApplyCoverageDeltas,
    getStateVersion as deckglGetStateVersion,
    getCoverageState as deckglGetCoverageState,
    clearCoverageState as deckglClearCoverageState,
    getCoverageStats as deckglGetCoverageStats,
    MapboxOverlay as DeckGLMapboxOverlay
} from '@static/js/deckgl-coverage-layer.js'

// Expose Deck.gl functions globally for controller.js
window.deckglCreateCoverageLayer = deckglCreateCoverageLayer;
window.deckglApplyCoverageDeltas = deckglApplyCoverageDeltas;
window.deckglGetStateVersion = deckglGetStateVersion;
window.deckglGetCoverageState = deckglGetCoverageState;
window.deckglClearCoverageState = deckglClearCoverageState;
window.deckglGetCoverageStats = deckglGetCoverageStats;
window.DeckGLMapboxOverlay = DeckGLMapboxOverlay;

// Utilities (functions used by other modules)
import '@static/js/utilities.js'

// Reference data loader callbacks
import '@static/js/reference_data_loader_callbacks.js'

// Main controller
import '@static/js/controller.js'

console.log('[Vite] App modules loaded')

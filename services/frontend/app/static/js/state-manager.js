/**
 * Lightweight State Management System
 * Simple pub/sub state container with immutable updates
 */

const StateManager = (function() {
    // Private state
    let state = {};
    const listeners = new Map(); // key -> Set of callbacks
    const globalListeners = new Set(); // callbacks for any state change

    /**
     * Initialize state with default values
     * @param {Object} initialState
     */
    function init(initialState = {}) {
        state = { ...initialState };
        notifyGlobalListeners();
    }

    /**
     * Get the current state or a specific key
     * @param {string} [key] - Optional key to get specific value
     * @returns {*} The state or value
     */
    function get(key) {
        if (key === undefined) {
            return { ...state }; // Return copy to prevent mutation
        }
        return state[key];
    }

    /**
     * Set state value(s)
     * @param {string|Object} keyOrObject - Key to set, or object of key-value pairs
     * @param {*} [value] - Value if first param is a key
     */
    function set(keyOrObject, value) {
        const changes = {};

        if (typeof keyOrObject === 'string') {
            if (state[keyOrObject] === value) return; // No change
            changes[keyOrObject] = value;
            state[keyOrObject] = value;
        } else if (typeof keyOrObject === 'object') {
            let hasChanges = false;
            for (const [key, val] of Object.entries(keyOrObject)) {
                if (state[key] !== val) {
                    changes[key] = val;
                    state[key] = val;
                    hasChanges = true;
                }
            }
            if (!hasChanges) return;
        }

        // Notify specific listeners
        for (const key of Object.keys(changes)) {
            notifyListeners(key, changes[key]);
        }

        // Notify global listeners
        notifyGlobalListeners(changes);
    }

    /**
     * Subscribe to changes on a specific key
     * @param {string} key - State key to watch
     * @param {Function} callback - Function to call on change
     * @returns {Function} Unsubscribe function
     */
    function subscribe(key, callback) {
        if (!listeners.has(key)) {
            listeners.set(key, new Set());
        }
        listeners.get(key).add(callback);

        // Return unsubscribe function
        return () => {
            const keyListeners = listeners.get(key);
            if (keyListeners) {
                keyListeners.delete(callback);
            }
        };
    }

    /**
     * Subscribe to all state changes
     * @param {Function} callback - Function to call on any change
     * @returns {Function} Unsubscribe function
     */
    function subscribeAll(callback) {
        globalListeners.add(callback);
        return () => globalListeners.delete(callback);
    }

    /**
     * Notify listeners for a specific key
     * @param {string} key
     * @param {*} value
     */
    function notifyListeners(key, value) {
        const keyListeners = listeners.get(key);
        if (keyListeners) {
            for (const callback of keyListeners) {
                try {
                    callback(value, key);
                } catch (e) {
                    console.error(`[StateManager] Error in listener for "${key}":`, e);
                }
            }
        }
    }

    /**
     * Notify global listeners
     * @param {Object} [changes] - Changed key-value pairs
     */
    function notifyGlobalListeners(changes = {}) {
        for (const callback of globalListeners) {
            try {
                callback({ ...state }, changes);
            } catch (e) {
                console.error('[StateManager] Error in global listener:', e);
            }
        }
    }

    /**
     * Batch multiple state updates
     * @param {Function} updateFn - Function that receives set() and makes multiple updates
     */
    function batch(updateFn) {
        const batchedChanges = {};
        const batchSet = (key, value) => {
            if (state[key] !== value) {
                batchedChanges[key] = value;
                state[key] = value;
            }
        };

        updateFn(batchSet);

        // Notify once for all changes
        for (const key of Object.keys(batchedChanges)) {
            notifyListeners(key, batchedChanges[key]);
        }
        if (Object.keys(batchedChanges).length > 0) {
            notifyGlobalListeners(batchedChanges);
        }
    }

    /**
     * Reset state to initial values
     * @param {Object} [newState] - New initial state
     */
    function reset(newState = {}) {
        state = { ...newState };
        notifyGlobalListeners(state);
    }

    // Public API
    return {
        init,
        get,
        set,
        subscribe,
        subscribeAll,
        batch,
        reset
    };
})();

// Default state schema
const DEFAULT_STATE = {
    // Filter state
    selectionType: 'all',
    subSelectionType: null,

    // Connection state
    connections: {
        coverage: 'unknown',
        route: 'unknown',
        main: 'unknown'
    },

    // UI state
    debugPanelOpen: false,
    loadingProgress: 0,
    loadingStep: '',

    // Data stats
    unitsCount: 0,
    coveredIdsCount: 0,
    visibleFeaturesCount: 0,

    // Last update timestamp
    lastUpdateTime: null
};

// Initialize state manager (can be called from app initialization)
// StateManager.init(DEFAULT_STATE);

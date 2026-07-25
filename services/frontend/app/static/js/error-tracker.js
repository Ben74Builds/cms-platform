/**
 * Frontend Error Tracking System
 * Captures errors and sends them to backend using sendBeacon API
 */

const ErrorTracker = (function() {
    // Configuration
    const ERROR_ENDPOINT = '/api/errors';
    const MAX_ERRORS_PER_SESSION = 50;
    const ERROR_BUFFER_INTERVAL = 5000; // 5 seconds

    // State
    let errorBuffer = [];
    let errorCount = 0;
    let flushTimeout = null;
    let sessionId = null;

    /**
     * Initialize error tracking
     */
    function init() {
        // Generate session ID
        sessionId = generateSessionId();

        // Global error handler
        window.onerror = function(message, source, lineno, colno, error) {
            captureError({
                type: 'uncaught',
                message: message,
                source: source,
                lineno: lineno,
                colno: colno,
                stack: error?.stack
            });
            return false; // Don't prevent default handling
        };

        // Unhandled promise rejection handler
        window.addEventListener('unhandledrejection', function(event) {
            captureError({
                type: 'unhandledrejection',
                message: event.reason?.message || String(event.reason),
                stack: event.reason?.stack
            });
        });

        // Send errors on page unload
        window.addEventListener('beforeunload', function() {
            flush(true);
        });

        // Visibility change - flush when going to background
        document.addEventListener('visibilitychange', function() {
            if (document.visibilityState === 'hidden') {
                flush(true);
            }
        });

        console.log('[ErrorTracker] Initialized, session:', sessionId);
    }

    /**
     * Generate a unique session ID
     */
    function generateSessionId() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    /**
     * Capture an error
     * @param {Object} errorData - Error details
     */
    function captureError(errorData) {
        if (errorCount >= MAX_ERRORS_PER_SESSION) {
            return; // Rate limit
        }

        const error = {
            ...errorData,
            timestamp: new Date().toISOString(),
            sessionId: sessionId,
            url: window.location.href,
            userAgent: navigator.userAgent,
            viewport: {
                width: window.innerWidth,
                height: window.innerHeight
            }
        };

        errorBuffer.push(error);
        errorCount++;

        // Schedule flush
        if (!flushTimeout) {
            flushTimeout = setTimeout(() => flush(), ERROR_BUFFER_INTERVAL);
        }

        // Log to console in development
        if (window.DEBUG_MODE) {
            console.error('[ErrorTracker] Captured:', error);
        }
    }

    /**
     * Capture a custom error/event
     * @param {string} name - Error/event name
     * @param {Object} data - Additional data
     */
    function capture(name, data = {}) {
        captureError({
            type: 'custom',
            name: name,
            data: data
        });
    }

    /**
     * Flush error buffer to server
     * @param {boolean} sync - Use sendBeacon for synchronous sending
     */
    function flush(sync = false) {
        if (flushTimeout) {
            clearTimeout(flushTimeout);
            flushTimeout = null;
        }

        if (errorBuffer.length === 0) {
            return;
        }

        const payload = JSON.stringify({
            errors: errorBuffer,
            meta: {
                sessionId: sessionId,
                totalCount: errorCount
            }
        });

        // Clear buffer before sending
        errorBuffer = [];

        if (sync && navigator.sendBeacon) {
            // Use sendBeacon for reliable delivery on page unload
            navigator.sendBeacon(ERROR_ENDPOINT, payload);
        } else {
            // Use fetch for normal operation
            fetch(ERROR_ENDPOINT, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: payload,
                keepalive: true // Keep request alive even if page closes
            }).catch((err) => {
                // Silently fail - don't cause more errors
                console.warn('[ErrorTracker] Failed to send errors:', err);
            });
        }
    }

    /**
     * Wrap a function with error tracking
     * @param {Function} fn - Function to wrap
     * @param {string} context - Context name for error reports
     */
    function wrap(fn, context = 'wrapped') {
        return function(...args) {
            try {
                return fn.apply(this, args);
            } catch (error) {
                captureError({
                    type: 'wrapped',
                    context: context,
                    message: error.message,
                    stack: error.stack
                });
                throw error; // Re-throw to maintain normal behavior
            }
        };
    }

    // Public API
    return {
        init,
        capture,
        captureError,
        wrap,
        flush
    };
})();

// Auto-initialize
if (typeof window !== 'undefined') {
    ErrorTracker.init();
}

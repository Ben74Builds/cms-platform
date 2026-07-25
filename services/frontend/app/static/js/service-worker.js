/**
 * Service Worker for CMS Platform
 * Provides offline support and caching strategies
 */

const CACHE_VERSION = 'cms-v1';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const TILE_CACHE = `${CACHE_VERSION}-tiles`;
const API_CACHE = `${CACHE_VERSION}-api`;

// Assets to cache on install
const STATIC_ASSETS = [
    '/',
    '/static/styles/main.css',
    '/static/js/controller.js',
    '/static/js/utilities.js',
    '/static/js/global_variables_initializer.js',
    '/static/js/maplibre_donut_cluster.js',
    '/static/js/reference_data_loader_callbacks.js',
    '/static/js/state-manager.js',
    '/static/configuration_settings.js',
    '/static/lib/maplibre-gl/4.4.0/maplibre-gl.js',
    '/static/lib/maplibre-gl/4.4.0/maplibre-gl.css',
    '/static/lib/d3/d3.v6.min.js',
    '/static/img/logo.png'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
    console.log('[ServiceWorker] Installing...');

    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then((cache) => {
                console.log('[ServiceWorker] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => {
                console.log('[ServiceWorker] Install complete');
                return self.skipWaiting();
            })
            .catch((err) => {
                console.error('[ServiceWorker] Install failed:', err);
            })
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('[ServiceWorker] Activating...');

    event.waitUntil(
        caches.keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames
                        .filter((name) => name.startsWith('cms-') && name !== STATIC_CACHE && name !== TILE_CACHE && name !== API_CACHE)
                        .map((name) => {
                            console.log('[ServiceWorker] Deleting old cache:', name);
                            return caches.delete(name);
                        })
                );
            })
            .then(() => {
                console.log('[ServiceWorker] Activate complete');
                return self.clients.claim();
            })
    );
});

// Fetch event - implement caching strategies
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Skip non-GET requests
    if (event.request.method !== 'GET') {
        return;
    }

    // Skip SSE streams (they need real-time connection)
    if (url.pathname.startsWith('/topic/') || url.pathname === '/stream') {
        return;
    }

    // Skip API calls that need fresh data
    if (url.pathname.startsWith('/api/') && url.pathname !== '/api/health') {
        return;
    }

    // Map tiles - Stale While Revalidate strategy
    if (url.pathname.includes('/tiles/') && url.pathname.endsWith('.pbf')) {
        event.respondWith(staleWhileRevalidate(event.request, TILE_CACHE));
        return;
    }

    // Static assets - Cache First strategy
    if (url.pathname.startsWith('/static/')) {
        event.respondWith(cacheFirst(event.request, STATIC_CACHE));
        return;
    }

    // HTML pages - Network First with fallback
    if (event.request.headers.get('accept')?.includes('text/html')) {
        event.respondWith(networkFirst(event.request, STATIC_CACHE));
        return;
    }

    // Default - Network First
    event.respondWith(networkFirst(event.request, STATIC_CACHE));
});

/**
 * Cache First Strategy
 * Best for static assets that rarely change
 */
async function cacheFirst(request, cacheName) {
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
        return cachedResponse;
    }

    try {
        const networkResponse = await fetch(request);
        if (networkResponse.ok) {
            const cache = await caches.open(cacheName);
            cache.put(request, networkResponse.clone());
        }
        return networkResponse;
    } catch (error) {
        console.error('[ServiceWorker] Fetch failed:', error);
        return new Response('Offline', { status: 503 });
    }
}

/**
 * Network First Strategy
 * Best for pages that need fresh content
 */
async function networkFirst(request, cacheName) {
    try {
        const networkResponse = await fetch(request);
        if (networkResponse.ok) {
            const cache = await caches.open(cacheName);
            cache.put(request, networkResponse.clone());
        }
        return networkResponse;
    } catch (error) {
        const cachedResponse = await caches.match(request);
        if (cachedResponse) {
            return cachedResponse;
        }
        return new Response('Offline', { status: 503 });
    }
}

/**
 * Stale While Revalidate Strategy
 * Best for map tiles - shows cached content immediately, updates in background
 */
async function staleWhileRevalidate(request, cacheName) {
    const cache = await caches.open(cacheName);
    const cachedResponse = await cache.match(request);

    // Start fetch in background
    const fetchPromise = fetch(request)
        .then((networkResponse) => {
            if (networkResponse.ok) {
                cache.put(request, networkResponse.clone());
            }
            return networkResponse;
        })
        .catch((error) => {
            console.warn('[ServiceWorker] Background fetch failed:', error);
            return null;
        });

    // Return cached response immediately if available
    if (cachedResponse) {
        return cachedResponse;
    }

    // Otherwise wait for network
    const networkResponse = await fetchPromise;
    if (networkResponse) {
        return networkResponse;
    }

    return new Response('Tile not available', { status: 503 });
}

// Handle messages from main thread
self.addEventListener('message', (event) => {
    if (event.data === 'skipWaiting') {
        self.skipWaiting();
    }

    if (event.data === 'clearCache') {
        caches.keys().then((names) => {
            names.forEach((name) => caches.delete(name));
        });
    }
});

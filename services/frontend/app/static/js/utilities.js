/*****
 * Create an associative array from a CSV file to be used as: my_data[key]
 * Require D3: https://cdnjs.cloudflare.com/ajax/libs/d3/4.11.0/d3.min.js
 **/
function csv_to_associative_array(source, array, callback) {
    d3.csv(source, (data) => {
        data.map(d => {
            array[d[Object.keys(d)[0]]] = d[Object.keys(d)[1]];
        });
        callback();
    });
}

/*****
 * Create a two-dimensional associative array from a CSV file to be used as: my_data[column][index]
 * Require D3
 **/
async function csv_to_dataframe_like_array(source, index, df, callback) {
    const data = await d3.csv(source);

    index = Object.keys(data[0])[0];
    var column_names = Object.keys(data[0]).slice(1);

    column_names.forEach(function(column) {
        df[column] = {};
        data.map(d => {
            df[column][d[index]] = d[column] == '' ? null : d[column];
        });
    });
    callback();
}


// ============================================================================
// Web Worker CSV Loader (non-blocking)
// ============================================================================

let dataLoaderWorker = null;
let workerCallbacks = new Map();
let workerRequestId = 0;

/**
 * Initialize the data loader web worker
 * @returns {Promise<Worker>} The worker instance
 */
function initDataLoaderWorker() {
    return new Promise((resolve, reject) => {
        if (dataLoaderWorker) {
            resolve(dataLoaderWorker);
            return;
        }

        try {
            dataLoaderWorker = new Worker('/static/js/data-loader-worker.js');

            dataLoaderWorker.onmessage = function(e) {
                const { type, id, result, results, error, success } = e.data;

                if (type === 'ready') {
                    console.log('[DataLoaderWorker] Ready');
                    resolve(dataLoaderWorker);
                    return;
                }

                const callback = workerCallbacks.get(id);
                if (callback) {
                    workerCallbacks.delete(id);
                    if (success) {
                        callback.resolve(type === 'multipleCSVParsed' ? results : result);
                    } else {
                        callback.reject(new Error(error));
                    }
                }
            };

            dataLoaderWorker.onerror = function(e) {
                console.error('[DataLoaderWorker] Error:', e);
                reject(e);
            };

            // Timeout fallback
            setTimeout(() => {
                if (!dataLoaderWorker) {
                    reject(new Error('Worker initialization timeout'));
                }
            }, 5000);
        } catch (e) {
            console.warn('[DataLoaderWorker] Not supported, using main thread');
            reject(e);
        }
    });
}

/**
 * Parse CSV using web worker (non-blocking)
 * Falls back to main thread D3 parsing if worker unavailable
 * @param {string} url - URL to CSV file
 * @param {Object} df - Target dataframe object to populate
 * @param {Function} callback - Callback after parsing
 */
async function csv_to_dataframe_worker(url, df, callback) {
    try {
        await initDataLoaderWorker();

        const id = ++workerRequestId;

        const result = await new Promise((resolve, reject) => {
            workerCallbacks.set(id, { resolve, reject });
            dataLoaderWorker.postMessage({ type: 'parseCSV', id, url });
        });

        // Copy result to target dataframe
        for (const col in result.data) {
            df[col] = result.data[col];
        }

        callback();
    } catch (e) {
        // Fallback to main thread parsing
        console.warn('[DataLoaderWorker] Falling back to D3 parsing:', e.message);
        await csv_to_dataframe_like_array(url, 'id', df, callback);
    }
}

/**
 * Parse multiple CSVs in parallel using web worker
 * @param {Array<{url: string, df: Object, callback: Function}>} configs - Array of CSV configs
 */
async function csv_batch_load_worker(configs) {
    try {
        await initDataLoaderWorker();

        const urls = configs.map(c => c.url);
        const id = ++workerRequestId;

        const results = await new Promise((resolve, reject) => {
            workerCallbacks.set(id, { resolve, reject });
            dataLoaderWorker.postMessage({ type: 'parseMultipleCSV', id, urls });
        });

        // Distribute results to target dataframes
        for (const config of configs) {
            const result = results[config.url];
            if (result && result.data) {
                for (const col in result.data) {
                    config.df[col] = result.data[col];
                }
            }
            if (config.callback) config.callback();
        }
    } catch (e) {
        // Fallback to sequential D3 parsing
        console.warn('[DataLoaderWorker] Falling back to D3 batch parsing:', e.message);
        for (const config of configs) {
            await csv_to_dataframe_like_array(config.url, 'id', config.df, config.callback || (() => {}));
        }
    }
}


function string_to_color(given_string) {
    var hash = 0;
    for (var i = 0; i < given_string.length; i++) {
        hash = given_string.charCodeAt(i) + ((hash << 5) - hash);
    }
    var colour = '#';
    for (var i = 0; i < 3; i++) {
        var value = (hash >> (i * 8)) & 0xFF;
        colour += ('00' + value.toString(16)).substr(-2);
    }
    return colour;
}


function getRadius(y) {
    var r = Math.sqrt(y / Math.PI);
    return r;
}


function get_type(obj) {
    return ({}).toString.call(obj).match(/\s([a-zA-Z]+)/)[1].toLowerCase();
}


function get_station_by_id(id) {
    return Object.keys(stations["code"]).filter(
        function(stations) { return stations.id == id; }
    );
}


function contains_object(obj, list) {
    for (var i = 0; i < list.length; i++) {
        if (list[i] === obj) {
            return true;
        }
    }
    return false;
}


function csv_to_json(csv) {
    var lines = csv.replace(/['"\r]+/g, '').split("\n");
    var result = [];
    var headers = lines[0].split(",");

    for (var i = 1; i < lines.length; i++) {
        var obj = {};
        var currentline = lines[i].split(",");

        for (var j = 0; j < headers.length; j++) {
            obj[headers[j]] = currentline[j];
        }
        result.push(obj);
    }
    return JSON.stringify(result);
}


/****
 * Performance monitoring with FPS, memory, and coverage stats
 **/
let perfStats = {
    fps: 0,
    frameCount: 0,
    lastFpsUpdate: 0,
    coveredBuildings: 0,
    totalCoverageIds: 0,
    lastCoverageUpdate: 0
};

function load_memory_consumption_legend() {
    // FPS counter
    let lastTime = performance.now();

    function updateFPS() {
        const now = performance.now();
        perfStats.frameCount++;

        if (now - perfStats.lastFpsUpdate >= 1000) {
            perfStats.fps = Math.round(perfStats.frameCount * 1000 / (now - perfStats.lastFpsUpdate));
            perfStats.frameCount = 0;
            perfStats.lastFpsUpdate = now;
        }

        requestAnimationFrame(updateFPS);
    }
    requestAnimationFrame(updateFPS);

    // Update display every second
    setInterval(function() {
        var resultEl = document.getElementById("result");
        var heapLimitEl = document.getElementById("heap_size_limit");
        var totalHeapEl = document.getElementById("total_heap_size");
        var usedHeapEl = document.getElementById("used_heap_size");
        var fpsEl = document.getElementById("fps_counter");
        var coverageStatsEl = document.getElementById("coverage_stats");

        if (resultEl) {
            resultEl.innerHTML = "Performance Monitor";
        }

        // FPS
        if (fpsEl) {
            const fpsColor = perfStats.fps >= 30 ? '#00ff00' : (perfStats.fps >= 15 ? '#ffff00' : '#ff0000');
            fpsEl.innerHTML = `FPS: <span style="color:${fpsColor}">${perfStats.fps}</span>`;
        }

        // Memory (Chrome only)
        if ("performance" in window && "memory" in window.performance) {
            const usedMB = (window.performance.memory.usedJSHeapSize / 1024 / 1024).toFixed(1);
            const totalMB = (window.performance.memory.totalJSHeapSize / 1024 / 1024).toFixed(1);

            if (heapLimitEl) {
                heapLimitEl.innerHTML = "Heap: " + usedMB + " / " + totalMB + " MB";
            }
            if (totalHeapEl) totalHeapEl.style.display = 'none';
            if (usedHeapEl) usedHeapEl.style.display = 'none';
        } else {
            if (heapLimitEl) heapLimitEl.innerHTML = "Memory: N/A";
        }

        // Coverage stats
        if (coverageStatsEl) {
            const unitsCount = Object.keys(units_for_coverage).length;
            let totalCovered = 0;
            for (const unit in units_for_coverage) {
                totalCovered += units_for_coverage[unit].size;
            }
            coverageStatsEl.innerHTML = `Units: ${unitsCount} | Covered: ${totalCovered}`;
        }

    }, 1000);
}


// ============================================================================
// Request Deduplication Cache
// ============================================================================

const pendingRequests = new Map(); // URL -> Promise
const REQUEST_CACHE_TTL = 5000; // 5 seconds cache for completed requests
const completedRequestsCache = new Map(); // URL -> { data, timestamp }

/**
 * Clean up expired cache entries
 */
function cleanupRequestCache() {
    const now = Date.now();
    for (const [url, entry] of completedRequestsCache) {
        if (now - entry.timestamp > REQUEST_CACHE_TTL) {
            completedRequestsCache.delete(url);
        }
    }
}

// Periodic cache cleanup
setInterval(cleanupRequestCache, 30000);

/**
 * Query an API with request deduplication
 * Coalesces duplicate concurrent requests to the same URL
 * @param {string} url - URL to fetch
 * @param {boolean} useCache - Whether to use short-term cache (default: false)
 * @returns {Promise<string|null>} Response text or null on error
 */
async function http_get(url, useCache = false) {
    // Check short-term cache
    if (useCache) {
        const cached = completedRequestsCache.get(url);
        if (cached && Date.now() - cached.timestamp < REQUEST_CACHE_TTL) {
            return cached.data;
        }
    }

    // Check if there's already a pending request for this URL
    if (pendingRequests.has(url)) {
        // Return the existing promise (request deduplication)
        return pendingRequests.get(url);
    }

    // Create new request
    const requestPromise = (async () => {
        try {
            const response = await fetch(url);

            if (response.ok) {
                const data = await response.text();

                // Cache the result
                if (useCache) {
                    completedRequestsCache.set(url, {
                        data: data,
                        timestamp: Date.now()
                    });
                }

                return data;
            } else {
                console.error("HTTP error " + response.status + " - " + response.statusText);
                console.log("Failed URL: " + url);
                return null;
            }
        } catch (error) {
            console.error("Failed URL: " + url);
            console.error("Exception during HTTP request:", error);
            const errorElement = document.getElementById('apis_unavailable');
            if (errorElement) {
                errorElement.style.display = 'block';
            }
            return null;
        } finally {
            // Remove from pending requests
            pendingRequests.delete(url);
        }
    })();

    // Store the promise for deduplication
    pendingRequests.set(url, requestPromise);

    return requestPromise;
}


function type_of(obj) {
    return {}.toString.call(obj).split(' ')[1].slice(0, -1).toLowerCase();
}


function empty_function() {
    // No-op placeholder
}


function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}


function select_element(id, value_to_select) {
    let element = document.getElementById(id);
    if (element) {
        element.value = value_to_select;
    }
}


function getBaseUrlWithoutPort() {
    var protocol = window.location.protocol;
    var host = window.location.host;

    // Extract hostname from host (removes port if present)
    var hostname = host.split(':')[0];

    // Construct base URL without port
    var baseUrlWithoutPort = protocol + '//' + hostname;

    return baseUrlWithoutPort;
}

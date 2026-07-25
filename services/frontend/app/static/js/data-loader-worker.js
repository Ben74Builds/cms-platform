/**
 * Web Worker for off-main-thread CSV parsing
 * Prevents UI blocking during initial data load
 */

/**
 * Parse CSV text into dataframe-like structure
 * @param {string} csvText - Raw CSV text
 * @returns {Object} Parsed data { columns: [], data: {} }
 */
function parseCSV(csvText) {
    const lines = csvText.trim().split('\n');
    if (lines.length === 0) return { columns: [], data: {} };

    // Parse header
    const headers = parseCSVLine(lines[0]);
    const indexCol = headers[0];
    const dataColumns = headers.slice(1);

    // Initialize result structure
    const result = {};
    for (const col of dataColumns) {
        result[col] = {};
    }

    // Parse data rows
    for (let i = 1; i < lines.length; i++) {
        const values = parseCSVLine(lines[i]);
        if (values.length < 2) continue;

        const rowId = values[0];
        for (let j = 1; j < values.length && j <= dataColumns.length; j++) {
            const value = values[j];
            result[dataColumns[j - 1]][rowId] = value === '' ? null : value;
        }
    }

    return {
        columns: dataColumns,
        indexColumn: indexCol,
        data: result
    };
}

/**
 * Parse a single CSV line handling quoted values
 * @param {string} line - CSV line
 * @returns {string[]} Parsed values
 */
function parseCSVLine(line) {
    const values = [];
    let current = '';
    let inQuotes = false;

    for (let i = 0; i < line.length; i++) {
        const char = line[i];

        if (char === '"') {
            inQuotes = !inQuotes;
        } else if (char === ',' && !inQuotes) {
            values.push(current.trim());
            current = '';
        } else {
            current += char;
        }
    }

    // Don't forget the last value
    values.push(current.trim());

    return values;
}

/**
 * Fetch and parse a CSV file
 * @param {string} url - URL to fetch
 * @returns {Promise<Object>} Parsed CSV data
 */
async function fetchAndParseCSV(url) {
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    const text = await response.text();
    return parseCSV(text);
}

// Handle messages from main thread
self.onmessage = async function(e) {
    const { type, id, url, urls } = e.data;

    try {
        if (type === 'parseCSV') {
            // Single CSV file
            const result = await fetchAndParseCSV(url);
            self.postMessage({
                type: 'csvParsed',
                id: id,
                url: url,
                result: result,
                success: true
            });
        } else if (type === 'parseMultipleCSV') {
            // Multiple CSV files in parallel
            const results = {};
            const promises = urls.map(async (csvUrl) => {
                const result = await fetchAndParseCSV(csvUrl);
                results[csvUrl] = result;
            });

            await Promise.all(promises);

            self.postMessage({
                type: 'multipleCSVParsed',
                id: id,
                results: results,
                success: true
            });
        }
    } catch (error) {
        self.postMessage({
            type: 'error',
            id: id,
            error: error.message,
            success: false
        });
    }
};

// Notify main thread that worker is ready
self.postMessage({ type: 'ready' });

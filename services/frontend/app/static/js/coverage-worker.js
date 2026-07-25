/**
 * Coverage Web Worker
 * Offloads coverage calculations from main thread for smooth UI
 *
 * Messages:
 * - { type: 'update', units_for_coverage, selection_type, sub_selection_type, units }
 * - { type: 'clear' }
 *
 * Responses:
 * - { type: 'coverage', global_coverage, totalCovered, computeTime }
 */

// Store coverage data
let units_for_coverage = {};
let global_coverage = {};

self.onmessage = function(e) {
    const { type, data } = e.data;

    switch (type) {
        case 'update_unit':
            // Update coverage for a single unit
            updateUnitCoverage(data);
            break;

        case 'compute':
            // Compute global coverage based on selection
            computeGlobalCoverage(data);
            break;

        case 'clear':
            // Clear all coverage data
            units_for_coverage = {};
            global_coverage = {};
            self.postMessage({ type: 'cleared' });
            break;
    }
};

/**
 * Update coverage data for a single unit
 */
function updateUnitCoverage(data) {
    const { unitId, buildingIds } = data;

    if (buildingIds && buildingIds.length > 0) {
        // Store as object for fast lookup
        const coverage = {};
        for (let i = 0; i < buildingIds.length; i++) {
            coverage[buildingIds[i]] = true;
        }
        units_for_coverage[unitId] = coverage;
    } else {
        units_for_coverage[unitId] = {};
    }

    self.postMessage({
        type: 'unit_updated',
        unitId: unitId,
        count: buildingIds ? buildingIds.length : 0
    });
}

/**
 * Compute global coverage based on current selection
 * This is the heavy computation that would block the main thread
 */
function computeGlobalCoverage(data) {
    const startTime = performance.now();
    const { selection_type, sub_selection_type, units } = data;

    // Reset global coverage
    global_coverage = {};

    const unitIds = Object.keys(units_for_coverage);

    for (let i = 0; i < unitIds.length; i++) {
        const unitId = unitIds[i];
        const coverage = units_for_coverage[unitId];
        const unitInfo = units ? units[unitId] : null;

        // Check if this unit should be counted based on selection
        let shouldCount = false;

        if (selection_type === 'all') {
            shouldCount = true;
        } else if (selection_type === 'category' && unitInfo) {
            shouldCount = unitInfo.cat === sub_selection_type;
        } else if (selection_type === 'competence' && unitInfo && unitInfo.competences) {
            shouldCount = unitInfo.competences.includes(sub_selection_type);
        } else {
            shouldCount = true; // Default to include
        }

        if (shouldCount) {
            // Add this unit's coverage to global
            const buildingIds = Object.keys(coverage);
            for (let j = 0; j < buildingIds.length; j++) {
                const buildingId = buildingIds[j];
                global_coverage[buildingId] = (global_coverage[buildingId] || 0) + 1;
            }
        }
    }

    const totalCovered = Object.keys(global_coverage).length;
    const computeTime = performance.now() - startTime;

    // Send result back to main thread
    self.postMessage({
        type: 'coverage',
        global_coverage: global_coverage,
        totalCovered: totalCovered,
        computeTime: computeTime
    });
}

/**
 * MapLibre Donut Cluster
 * Supercluster-based clustering with SVG donut chart markers
 * Replaces L.DonutCluster from Leaflet
 */

class MapLibreDonutCluster {
    constructor(map, options = {}) {
        this.map = map;
        this.options = {
            clusterRadius: options.clusterRadius || 50,
            clusterMaxZoom: options.clusterMaxZoom || 16,
            statusKey: options.statusKey || 'status',
            colorDict: options.colorDict || {},
            markerSize: options.markerSize || 20,
            clusterSizeBase: options.clusterSizeBase || 30,
            clusterSizeScale: options.clusterSizeScale || 0.5,
            ...options
        };

        this.supercluster = null;
        this.markers = new Map(); // unit_id -> marker
        this.clusterMarkers = new Map(); // cluster_id -> marker element
        this.points = []; // GeoJSON features for Supercluster
        this.pointIndex = new Map(); // unit_id -> index in points array (for O(1) lookup)
        this.visible = true;
        this._rebuildTimeout = null;
        this._popup = null; // Shared popup for tooltips
        this._indexBuilt = false; // Flag to track if supercluster index has been built

        this._initSupercluster();
        this._initPopup();
        this._bindEvents();
    }

    _initPopup() {
        this._popup = new maplibregl.Popup({
            closeButton: false,
            closeOnClick: false,
            className: 'donut-cluster-popup',
            maxWidth: '300px'
        });
    }

    _initSupercluster() {
        this.supercluster = new Supercluster({
            radius: this.options.clusterRadius,
            maxZoom: this.options.clusterMaxZoom,
            map: (props) => ({
                statusCounts: { [props.status]: 1 }
            }),
            reduce: (accumulated, props) => {
                for (const status in props.statusCounts) {
                    accumulated.statusCounts[status] =
                        (accumulated.statusCounts[status] || 0) + props.statusCounts[status];
                }
            }
        });
    }

    _bindEvents() {
        // Only update clusters when movement stops — not during pan/zoom
        this.map.on('moveend', () => this._updateClusters());
    }

    /**
     * Add or update a unit marker (batched)
     */
    addUnit(unitId, lat, lon, status, extraProps = {}) {
        // Create GeoJSON feature
        const feature = {
            type: 'Feature',
            geometry: {
                type: 'Point',
                coordinates: [lon, lat]
            },
            properties: {
                unitId: unitId,
                status: status,
                ...extraProps
            }
        };

        // Check if unit already exists (O(1) lookup)
        if (this.pointIndex.has(unitId)) {
            // Update existing point in place
            const idx = this.pointIndex.get(unitId);
            this.points[idx] = feature;
        } else {
            // Add new point
            this.pointIndex.set(unitId, this.points.length);
            this.points.push(feature);
        }

        this._scheduleRebuild();
    }

    /**
     * Remove a unit marker (batched)
     */
    removeUnit(unitId) {
        // Remove from points array using index (O(1) lookup)
        if (this.pointIndex.has(unitId)) {
            const idx = this.pointIndex.get(unitId);
            // Mark as null, will be cleaned up during rebuild
            this.points[idx] = null;
            this.pointIndex.delete(unitId);
            this._needsCompaction = true;
            this._scheduleRebuild();
        }

        // Remove marker if exists
        if (this.markers.has(unitId)) {
            this.markers.get(unitId).remove();
            this.markers.delete(unitId);
        }
    }

    /**
     * Schedule a batched rebuild of the index
     */
    _scheduleRebuild() {
        if (this._rebuildTimeout) return;
        this._rebuildTimeout = setTimeout(() => {
            this._rebuildTimeout = null;
            this._rebuildIndex();
            this._updateClusters();
        }, 50); // Batch updates within 50ms
    }

    /**
     * Update unit status (e.g., when status changes)
     */
    updateUnitStatus(unitId, newStatus) {
        if (!this.pointIndex.has(unitId)) return;
        const point = this.points[this.pointIndex.get(unitId)];
        if (point) {
            point.properties.status = newStatus;
            this._scheduleRebuild();
        }
    }

    /**
     * Update unit position
     */
    updateUnitPosition(unitId, lat, lon) {
        if (!this.pointIndex.has(unitId)) return;
        const point = this.points[this.pointIndex.get(unitId)];
        if (point) {
            point.geometry.coordinates = [lon, lat];
            this._scheduleRebuild();
        }
    }

    /**
     * Rebuild Supercluster index
     */
    _rebuildIndex() {
        // Compact array if needed (remove null entries)
        if (this._needsCompaction) {
            this._needsCompaction = false;
            const newPoints = [];
            this.pointIndex.clear();

            for (let i = 0; i < this.points.length; i++) {
                const point = this.points[i];
                if (point !== null) {
                    this.pointIndex.set(point.properties.unitId, newPoints.length);
                    newPoints.push(point);
                }
            }
            this.points = newPoints;
        }

        this.supercluster.load(this.points);
        this._indexBuilt = true;
    }

    /**
     * Update visible clusters/markers based on current map view
     */
    _updateClusters() {
        if (!this.visible) {
            this._clearAllMarkers();
            return;
        }

        // Don't try to get clusters if no data has been loaded yet
        if (this.points.length === 0 || !this._indexBuilt) {
            this._clearAllMarkers();
            return;
        }

        const bounds = this.map.getBounds();
        const zoom = Math.floor(this.map.getZoom());

        const bbox = [
            bounds.getWest(),
            bounds.getSouth(),
            bounds.getEast(),
            bounds.getNorth()
        ];

        const clusters = this.supercluster.getClusters(bbox, zoom);

        // Track which markers/clusters we need
        const neededMarkers = new Set();
        const neededClusters = new Set();

        clusters.forEach(cluster => {
            if (cluster.properties.cluster) {
                // It's a cluster
                const clusterId = cluster.properties.cluster_id;
                neededClusters.add(clusterId);
                this._renderCluster(cluster);
            } else {
                // It's an individual point
                const unitId = cluster.properties.unitId;
                neededMarkers.add(unitId);
                this._renderMarker(cluster);
            }
        });

        // Remove markers/clusters that are no longer needed
        this.markers.forEach((marker, unitId) => {
            if (!neededMarkers.has(unitId)) {
                marker.remove();
                this.markers.delete(unitId);
            }
        });

        this.clusterMarkers.forEach((marker, clusterId) => {
            if (!neededClusters.has(clusterId)) {
                marker.remove();
                this.clusterMarkers.delete(clusterId);
            }
        });
    }

    /**
     * Render a single unit marker
     */
    _renderMarker(feature) {
        const unitId = feature.properties.unitId;
        const [lon, lat] = feature.geometry.coordinates;
        const status = feature.properties.status;
        const color = this.options.colorDict[status] || '#888888';

        if (this.markers.has(unitId)) {
            // Update position
            this.markers.get(unitId).setLngLat([lon, lat]);
            return;
        }

        // Create marker element
        const el = document.createElement('div');
        el.className = 'maplibre-unit-marker';
        el.style.width = this.options.markerSize + 'px';
        el.style.height = this.options.markerSize + 'px';
        el.style.backgroundColor = color;
        el.style.borderRadius = '50%';
        el.style.border = '2px solid white';
        el.style.boxShadow = '0 2px 4px rgba(0,0,0,0.3)';
        el.style.cursor = 'pointer';

        const marker = new maplibregl.Marker({ element: el })
            .setLngLat([lon, lat])
            .addTo(this.map);

        // Add popup on click
        el.addEventListener('click', () => {
            this._onMarkerClick(feature);
        });

        // Add tooltip on hover
        el.addEventListener('mouseenter', () => {
            this._showMarkerTooltip(feature, [lon, lat]);
        });
        el.addEventListener('mouseleave', () => {
            this._popup.remove();
        });

        this.markers.set(unitId, marker);
    }

    /**
     * Show tooltip for individual marker
     */
    _showMarkerTooltip(feature, coordinates) {
        const props = feature.properties;
        const unitId = props.unitId;
        const status = props.status;
        const statusColor = this.options.colorDict[status] || '#888888';

        // Get status label from STATUS array if available
        let statusLabel = status;
        if (typeof STATUS !== 'undefined' && STATUS[status]) {
            statusLabel = STATUS[status].label || status;
        }

        // Get unit name from units_for_coverage if available
        let unitName = `Unit ${unitId}`;
        if (typeof units_for_coverage !== 'undefined' && units_for_coverage[unitId]) {
            unitName = units_for_coverage[unitId].name || unitName;
        }

        const html = `
            <div class="tooltip-content">
                <div class="tooltip-unit-name"><strong>${unitName}</strong></div>
                <div class="tooltip-status">
                    <span class="status-dot" style="background-color: ${statusColor};"></span>
                    ${statusLabel}
                </div>
            </div>
        `;

        this._popup
            .setLngLat(coordinates)
            .setHTML(html)
            .addTo(this.map);
    }

    /**
     * Render a cluster with donut chart
     */
    _renderCluster(cluster) {
        const clusterId = cluster.properties.cluster_id;
        const [lon, lat] = cluster.geometry.coordinates;
        const pointCount = cluster.properties.point_count;
        const statusCounts = cluster.properties.statusCounts;

        if (this.clusterMarkers.has(clusterId)) {
            // Update position
            this.clusterMarkers.get(clusterId).setLngLat([lon, lat]);
            return;
        }

        // Calculate cluster size based on point count
        const size = this.options.clusterSizeBase +
                     Math.sqrt(pointCount) * this.options.clusterSizeScale * 10;

        // Create SVG donut element
        const el = document.createElement('div');
        el.className = 'maplibre-cluster-marker';
        el.innerHTML = this._createDonutSVG(statusCounts, size, pointCount);
        el.style.cursor = 'pointer';

        const marker = new maplibregl.Marker({ element: el })
            .setLngLat([lon, lat])
            .addTo(this.map);

        // Zoom in on click
        el.addEventListener('click', () => {
            const zoom = this.supercluster.getClusterExpansionZoom(clusterId);
            this.map.easeTo({
                center: [lon, lat],
                zoom: zoom
            });
        });

        // Add tooltip on hover
        el.addEventListener('mouseenter', () => {
            this._showClusterTooltip(cluster, [lon, lat]);
        });
        el.addEventListener('mouseleave', () => {
            this._popup.remove();
        });

        this.clusterMarkers.set(clusterId, marker);
    }

    /**
     * Show tooltip for cluster donut
     */
    _showClusterTooltip(cluster, coordinates) {
        const clusterId = cluster.properties.cluster_id;
        const pointCount = cluster.properties.point_count;
        const statusCounts = cluster.properties.statusCounts;

        // Get leaves (units in this cluster) - limit to 10 for display
        const leaves = this.supercluster.getLeaves(clusterId, 10);

        // Build status summary HTML
        let statusSummaryHtml = '<div class="tooltip-status-summary">';
        for (const [status, count] of Object.entries(statusCounts)) {
            const color = this.options.colorDict[status] || '#888888';
            let statusLabel = status;
            if (typeof STATUS !== 'undefined' && STATUS[status]) {
                statusLabel = STATUS[status].label || status;
            }
            statusSummaryHtml += `
                <div class="tooltip-status-row">
                    <span class="status-dot" style="background-color: ${color};"></span>
                    <span class="status-label">${statusLabel}</span>
                    <span class="status-count">${count}</span>
                </div>
            `;
        }
        statusSummaryHtml += '</div>';

        // Build units list HTML
        let unitsHtml = '<div class="tooltip-units-list">';
        leaves.forEach(leaf => {
            const props = leaf.properties;
            const unitId = props.unitId;
            const status = props.status;
            const color = this.options.colorDict[status] || '#888888';

            let unitName = `Unit ${unitId}`;
            if (typeof units_for_coverage !== 'undefined' && units_for_coverage[unitId]) {
                unitName = units_for_coverage[unitId].name || unitName;
            }

            unitsHtml += `
                <div class="tooltip-unit-row">
                    <span class="status-dot" style="background-color: ${color};"></span>
                    <span class="unit-name">${unitName}</span>
                </div>
            `;
        });
        if (pointCount > 10) {
            unitsHtml += `<div class="tooltip-more">...and ${pointCount - 10} more</div>`;
        }
        unitsHtml += '</div>';

        const html = `
            <div class="tooltip-content cluster-tooltip">
                <div class="tooltip-header"><strong>${pointCount} Units</strong></div>
                ${statusSummaryHtml}
                <hr class="tooltip-divider">
                ${unitsHtml}
                <div class="tooltip-hint">Click to zoom in</div>
            </div>
        `;

        this._popup
            .setLngLat(coordinates)
            .setHTML(html)
            .addTo(this.map);
    }

    /**
     * Create SVG donut chart
     */
    _createDonutSVG(statusCounts, size, totalCount) {
        const total = Object.values(statusCounts).reduce((a, b) => a + b, 0);
        const radius = size / 2;
        const innerRadius = radius * 0.6;
        const centerX = radius;
        const centerY = radius;

        let paths = '';
        let startAngle = -Math.PI / 2; // Start at top

        for (const [status, count] of Object.entries(statusCounts)) {
            const color = this.options.colorDict[status] || '#888888';
            const angle = (count / total) * 2 * Math.PI;
            const endAngle = startAngle + angle;

            // Calculate arc path
            const x1 = centerX + radius * Math.cos(startAngle);
            const y1 = centerY + radius * Math.sin(startAngle);
            const x2 = centerX + radius * Math.cos(endAngle);
            const y2 = centerY + radius * Math.sin(endAngle);
            const x3 = centerX + innerRadius * Math.cos(endAngle);
            const y3 = centerY + innerRadius * Math.sin(endAngle);
            const x4 = centerX + innerRadius * Math.cos(startAngle);
            const y4 = centerY + innerRadius * Math.sin(startAngle);

            const largeArc = angle > Math.PI ? 1 : 0;

            paths += `<path d="M ${x1} ${y1} A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2} L ${x3} ${y3} A ${innerRadius} ${innerRadius} 0 ${largeArc} 0 ${x4} ${y4} Z" fill="${color}" />`;

            startAngle = endAngle;
        }

        // Add center text with count
        const fontSize = Math.max(10, size * 0.3);

        return `
            <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
                ${paths}
                <circle cx="${centerX}" cy="${centerY}" r="${innerRadius - 2}" fill="white" />
                <text x="${centerX}" y="${centerY}" text-anchor="middle" dominant-baseline="central"
                      font-size="${fontSize}px" font-weight="bold" fill="#333">
                    ${totalCount}
                </text>
            </svg>
        `;
    }

    /**
     * Handle marker click
     */
    _onMarkerClick(feature) {
        const props = feature.properties;
        // Emit custom event for external handling
        const event = new CustomEvent('unitclick', {
            detail: {
                unitId: props.unitId,
                status: props.status,
                coordinates: feature.geometry.coordinates,
                properties: props
            }
        });
        this.map.getContainer().dispatchEvent(event);
    }

    /**
     * Clear all markers
     */
    _clearAllMarkers() {
        this.markers.forEach(marker => marker.remove());
        this.markers.clear();
        this.clusterMarkers.forEach(marker => marker.remove());
        this.clusterMarkers.clear();
    }

    /**
     * Show/hide the cluster layer
     */
    setVisible(visible) {
        this.visible = visible;
        this._updateClusters();
    }

    /**
     * Get all units matching a filter function
     */
    getUnitsWhere(filterFn) {
        return this.points.filter(p => filterFn(p.properties));
    }

    /**
     * Clear all data
     */
    clear() {
        this._clearAllMarkers();
        this.points = [];
        this.pointIndex.clear();
        this._indexBuilt = false;
    }

    /**
     * Destroy the cluster instance
     */
    destroy() {
        this._clearAllMarkers();
        this.map.off('move', this._updateClusters);
        this.map.off('zoom', this._updateClusters);
    }
}

// CSS styles for markers (injected dynamically)
(function() {
    const style = document.createElement('style');
    style.textContent = `
        .maplibre-unit-marker {
            transition: transform 0.1s ease;
        }
        .maplibre-unit-marker:hover {
            transform: scale(1.2);
            z-index: 1000 !important;
        }
        .maplibre-cluster-marker {
            transition: transform 0.1s ease;
        }
        .maplibre-cluster-marker:hover {
            transform: scale(1.1);
            z-index: 1000 !important;
        }

        /* Donut cluster tooltip styles */
        .donut-cluster-popup .maplibregl-popup-content {
            padding: 10px 12px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
            font-size: 13px;
        }

        .tooltip-content {
            min-width: 120px;
        }

        .tooltip-unit-name {
            margin-bottom: 4px;
        }

        .tooltip-status {
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .status-dot {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            flex-shrink: 0;
        }

        .tooltip-header {
            margin-bottom: 8px;
            font-size: 14px;
        }

        .tooltip-status-summary {
            margin-bottom: 8px;
        }

        .tooltip-status-row {
            display: flex;
            align-items: center;
            gap: 6px;
            margin-bottom: 3px;
        }

        .tooltip-status-row .status-label {
            flex: 1;
        }

        .tooltip-status-row .status-count {
            font-weight: bold;
            color: #666;
        }

        .tooltip-divider {
            border: none;
            border-top: 1px solid #ddd;
            margin: 8px 0;
        }

        .tooltip-units-list {
            max-height: 150px;
            overflow-y: auto;
        }

        .tooltip-unit-row {
            display: flex;
            align-items: center;
            gap: 6px;
            margin-bottom: 2px;
            font-size: 12px;
        }

        .tooltip-unit-row .unit-name {
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .tooltip-more {
            color: #888;
            font-style: italic;
            font-size: 11px;
            margin-top: 4px;
        }

        .tooltip-hint {
            color: #888;
            font-size: 11px;
            margin-top: 8px;
            text-align: center;
        }
    `;
    document.head.appendChild(style);
})();

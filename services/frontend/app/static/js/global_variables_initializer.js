maplibregl.accessToken = "not-needed-unless-using-maplibre-styles";

// Deck.gl coverage rendering toggle
// Set to true to use GPU-accelerated Deck.gl MVTLayer for coverage
// Set to false to use MapLibre setFeatureState (CPU-bound)
var USE_DECKGL_COVERAGE = true;

// Map layer reference (MapLibre only)
var map = {};
var maplibre_layer_base_style;

// Donut cluster instance (replaces Leaflet DonutCluster)
var donutCluster = null;
var donutClusterByCategory = {};
var donutClusterByCompetence = {};

/**
 * Coverage data
 **/
// Number of units covering each way
var global_coverage = {};
// Ways covered for each unit
var units_for_coverage = {};
// Ways group by number of units covering them
var compressed_coverage = {};
// Stations dataframe
var stations = {};

// Palette de couleur
var palette = [];
palette["0"] = "#ff0000";
palette["1"] = "#ffd100";
palette["2"] = "#f0ff00";
palette["3"] = "#cfff00";
palette["4"] = "#a9ff00";
palette["5"] = "#79ff00";
palette["6"] = "#1aff00";
palette["7"] = "#00ff7d";
palette["8"] = "#00ffbc";
palette["9"] = "#00fee7";
palette["10"] = "#05f7ff";

// Hold marker plots on the map
var units = {};
// Hold different marker colors
var marker_colors = {};
// Marker tooltips initial display option
var display_tooltips = DISPLAY_TOOLTIPS;

// O(1) lookup indexes for filtering (populated in controller.js)
var unitsByCategory = new Map();      // category_id -> Set of unitIds
var unitsByCompetence = new Map();    // competence_id -> Set of unitIds

STATUS = {};
stations = {};
pois_types = {};
pois = {};
unit_categories = {};
unit_competences = {};

categories_discovered = {};
competences_discovered = {};

var selection_type = "all"; // all, category, competence
var sub_selection_type = null;

var interventions = {};
var interventions_displayed = new Set();
var buffer_interventions_to_display = [];

// Intervention markers (MapLibre)
var interventionMarkers = {};

var hospitals = [];

global_coverage = {};

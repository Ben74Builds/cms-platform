const PAGE_URL = window.location.origin;
const PAGE_TITLE='Coverage Live Map';

const SERVICE = (typeof __CITY_CONFIG !== 'undefined' && __CITY_CONFIG.service) ? __CITY_CONFIG.service : 'paris';

// Kafka
const KAFKA_TOPIC_MAIN_STREAM = SERVICE + '_gps_status';
const KAFKA_TOPIC_ROUTE_RESPONSE = SERVICE + '_route_response';
const KAFKA_TOPIC_COVERAGE_RESPONSE = SERVICE + '_coverage_response';


// Redis
const REDIS_CHANNEL = SERVICE + '_gps_status';


// Map
const MAP_URL_TEMPLATE = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const MAP_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const MAP_STARTING_CENTER = (typeof __CITY_CONFIG !== 'undefined' && __CITY_CONFIG.center) ? [__CITY_CONFIG.center[1], __CITY_CONFIG.center[0]] : [48.8566, 2.3522];
const MAP_STARTING_ZOOM = (typeof __CITY_CONFIG !== 'undefined' && __CITY_CONFIG.zoom) ? __CITY_CONFIG.zoom : 12;
const MAP_MAX_ZOOM = 18;
const MAX_CLUSTER_RADIUS = 10;
// Map center (overridden by city config if available)
const INITIAL_CENTER_LON = (typeof __CITY_CONFIG !== 'undefined' && __CITY_CONFIG.center) ? __CITY_CONFIG.center[0] : 2.333333;
const INITIAL_CENTER_LAT = (typeof __CITY_CONFIG !== 'undefined' && __CITY_CONFIG.center) ? __CITY_CONFIG.center[1] : 48.866667;
// MapBox zoom levels
const INITIAL_ZOOM = (typeof __CITY_CONFIG !== 'undefined' && __CITY_CONFIG.zoom) ? __CITY_CONFIG.zoom + 5 : 17;
const MIN_ZOOM = (typeof __CITY_CONFIG !== 'undefined' && __CITY_CONFIG.min_zoom) ? __CITY_CONFIG.min_zoom : 10;
const MAX_ZOOM = 17;
const DISPLAY_TOOLTIPS = false;
const DRAW_LINE_TO_STATION = false;
const MAPLIBRE_LAYER_BASE_STYLE_FILE = "../../static/styles/maplibre_styles.json";
//var mapbox_layer_base_style = {};

// Coverage visualization mode: "buildings" or "roads"
const COVERAGE_MODE = "buildings";

// Building tiles (polygon-based coverage) - city-aware
const _buildingTileset = (typeof __CITY_CONFIG !== 'undefined' && __CITY_CONFIG.building_tiles) ? __CITY_CONFIG.building_tiles : 'buildings';
const BUILDING_TILESOURCE_URL = location.protocol + '//' + location.host + '/static/data/tiles/' + _buildingTileset + '/{z}/{x}/{y}.pbf';
const BUILDING_SOURCE_LAYER = (typeof __CITY_CONFIG !== 'undefined' && __CITY_CONFIG.building_source_layer) ? __CITY_CONFIG.building_source_layer : "buildings";

// Road tiles (line-based coverage) - city-aware
const _roadTileset = (typeof __CITY_CONFIG !== 'undefined' && __CITY_CONFIG.road_tiles) ? __CITY_CONFIG.road_tiles : 'roads';
const ROAD_TILESOURCE_URL = location.protocol + '//' + location.host + '/static/data/tiles/' + _roadTileset + '/{z}/{x}/{y}.pbf';
const ROAD_SOURCE_LAYER = (typeof __CITY_CONFIG !== 'undefined' && __CITY_CONFIG.road_source_layer) ? __CITY_CONFIG.road_source_layer : "roads";

// Active tile source based on coverage mode
const TILESOURCE_URL = COVERAGE_MODE === "buildings" ? BUILDING_TILESOURCE_URL : ROAD_TILESOURCE_URL;
const SOURCE_LAYER = COVERAGE_MODE === "buildings" ? BUILDING_SOURCE_LAYER : ROAD_SOURCE_LAYER;

// Dict

const dict = {
    "units" : "unités"
    , "of_units" : "des unités"
};

 

// Data
const CSV_FILE_STATUS = "../../../static/data/reference/status.csv";
const CSV_FILE_UNIT_COMPETENCES = "../../../static/data/reference/competences.csv";
const CSV_FILE_UNIT_CATEGORIES = "../../../static/data/reference/unit_categories.csv";
const CSV_FILE_STATIONS = "../../../static/data/reference/stations.csv";
const CSV_FILE_POIS_TYPES = "../../../static/data/reference/pois_types.csv";
const CSV_FILE_POIS = "../../../static/data/reference/pois.csv";



const IMG_CALL = { 
    img:'../../../static/img/call.svg'
    , width:24
    , height:24
};
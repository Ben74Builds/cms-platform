<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
    <meta http-equiv="Pragma" content="no-cache" />
    <meta http-equiv="Expires" content="0" />

    
    <script type="text/javascript">



    </script>
    
    <!-- maplibre GL -->
    <!--<script src="https://api.maplibre.com/maplibre-gl-js/v0.35.1/maplibre-gl.js"></script>-->
    <!--<link href="https://api.maplibre.com/maplibre-gl-js/v0.35.1/maplibre-gl.css" rel="stylesheet" />-->
    <script src="../../../static/lib/maplibre-gl/4.4.0/maplibre-gl.js"></script>
    <link href="../../../static/lib/maplibre-gl/4.4.0/maplibre-gl.css" rel="stylesheet" />
 
    <!-- Leaflet -->
    <!-- LOAD LEAFLET -->
    <!--<link rel="stylesheet" href="../../../static/lib/leaflet/leaflet.css" crossorigin=""/>-->
    <!-- Make sure you put this AFTER Leaflet's CSS -->
    <!--<script src="../../../static/lib/leaflet/leaflet.js" crossorigin=""></script>-->

    <link href='../../../static/lib/leaflet/leaflet.css' rel='stylesheet' />
    <link href="../../../static/lib/leaflet/leaflet.MarkerCluster.css" rel='stylesheet' />
    <link href="../../../static/lib/leaflet/leaflet.DonutCluster.css" rel='stylesheet' />
    
    <script src="../../../static/lib/leaflet/leaflet.js"></script>
    <script src="../../../static/lib/leaflet/leaflet.MarkerCluster.js"></script>
    <script src="../../../static/lib/leaflet/leaflet.DonutCluster.js"></script>

    <script src="https://unpkg.com/leaflet-ant-path@1.3.0/dist/leaflet-ant-path.js" crossorigin=""></script>
    <!-- https://github.com/jieter/Leaflet.Sync -->
    <script src="../../../static/lib/leaflet/L.Maps.Sync.js"></script>    
    <!-- <script src="https://cdnjs.cloudflare.com/ajax/libs/d3/4.11.0/d3.min.js"></script> -->
    <script src="../../../static/lib/d3/d3.v6.min.js"></script>
            
    <script src="../../../static/lib/jquery/jquery-3.6.0.min.js"></script>
    

    <link href="../../../static/styles/main.css?<?php echo date('Y-m-d_H:i:s'); ?>" rel="stylesheet" />

    <title>{{ service_coverage }}</title>
</head>
<body>

    <div id='map_view'>
        <div id='object_layer'></div>
        <div id='mb_layer'></div>
        <div id='osm_layer'></div>
    </div>
    <!-- 
    <br>

    Show/Hide unit informations:<br>
    <span class="toggle">
        <input type="checkbox" onclick="toggle_button()" id="toggle_button" value="0">
        <label data-off="&#10006;" data-on="&#10004;"></label>
    </span>
    -->

    <script src="../../../static/configuration_settings.js"></script>  
    <script src="../../../static/js/global_variables_initializer.js"></script>
    <script src="../../../static/js/reference_data_loader_callbacks.js"></script>
    <script src="../../../static/js/controller.js"></script>
    <script src="../../../static/js/utilities.js"></script>
    <script type="text/javascript">
        
        var stations;

        window.onload = async function(){

            const LATLNG_GROUND_ZERO = L.latLng(1000,1000);
            
            // Load a coverage information

            /*
            var source = new EventSource('/stream');
            source.onmessage = function (event) {
                // alert(event.data);
                update_maplibre_layer(event.data);
            };
            */
     

            // Utilisé par DonutCluster
            await csv_to_dataframe_like_array(CSV_FILE_STATUS, "id",STATUS, callback_status_loaded);
            // Chargement des objets cartographiques
            await load_maplibre_layer();
            await load_leaflet_layers();
            await load_memory_consumption_legend();

            // Chargement des données nécessitant le chargement préalable des objets cartographiques
            await Promise.all([
                , csv_to_dataframe_like_array(CSV_FILE_UNIT_COMPETENCES, "id", unit_competences, callback_unit_competences_loaded)
                , csv_to_dataframe_like_array(CSV_FILE_UNIT_CATEGORIES, "id", unit_categories, callback_unit_categories_loaded)
                , csv_to_dataframe_like_array(CSV_FILE_STATIONS, "id", stations, callback_stations_loaded)
                , csv_to_dataframe_like_array(CSV_FILE_POIS_TYPES, "id", pois_types, callback_pois_types_loaded)
                , csv_to_dataframe_like_array(CSV_FILE_POIS, "id", pois, callback_pois_loaded)
            ])

            //Pour tester une couverture statique
            // $.getJSON("../../../static/json_test.json?nocache=123", function(json) {
            //     map_style_to_load = maplibre_layer_base_style;

            //     // Append each coverage information to the 'layers' property
            //     // when all files have been successfully loaded
            //     console.log
            //     for (var i =0; i< json.length ;i++) {
            //         map_style_to_load['layers'][i] = json[i];
                    
            //     } 

            //     console.log("Mise à jour de la couverture");
            //     mb_layer.setStyle(map_style_to_load);
            // });
            
            //await initialize_geopositions_and_status('http://127.0.0.1:9080/get_gp_and_status/1');
            await initialize_geopositions_and_status(getBaseUrlWithoutPort() + ':9080/get_gp_and_status/1');
    
                
        };

    </script>

</body>
</html>
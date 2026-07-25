## Prerequisites

Install GDAL
```
conda create -n gdal python
conda activate gdal
conda install -c conda-forge gdal
# Check the installation
ogr2ogr --version
```

Build and install tippecanoe
```
cd lib/tippecanoe
make
sudo make install
cd ../../
```

## HERE Data Layers

It is possible to get different HERE data layers such as "Navigable Roads".

HERE data layers: https://developer.here.com/products/data-layers
Access HERE data from HERE Studio: https://studio.here.com/studio/your-data 


HERE "Navigable Roads" data layers is provided under a GeoJSON shape as:
```
{
    "id": "56241063",
    "type": "Feature",
    "properties": {
      "roads": [],
      "divider": "N",
      "endNode": ...
      ...
    },
    "geometry": {
      "type": "LineString",
      "coordinates": [
        [
          2.29149,
          48.86891,
```
Copy the id under properties

// TODO


With tippecanoe it is possible to generate tiles from such a GeoJSON file with the following command:
```
tippecanoe \
	--no-feature-limit \
	--no-tile-size-limit \
	--include={"category"} \
	--maximum-zoom=16 \
	--layer="navigable-roads" \
	--output-to-directory "./paris-here" \
	"./paris-navigableroads-v89_8zL5iOyA.geojson"
```

We also can check the content of the generated tiles with tippecanoe:
```
tippecanoe-decode 11259.pbf zoom 0 0
```
Return
```
{
    "type": "FeatureCollection",
    "properties": {
        "zoom": 0,
        "x": 0,
        "y": 0
    },
    "features": [
        {
            "type": "FeatureCollection",
            "properties": {
                "layer": "navigable-roads",
                "version": 2,
                "extent": 4096
            },
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "category": "Residential"
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [
                                -166.552734,
                                -9.102097
                            ],
                            [
                                -180.000000,
                                -8.667918
                            ],
                            [
                                -187.031250,
                                -8.494105
                            ]
                        ]
                    }
                },
```
Note that our tiles generated on OSM data are of the form:
```
{
    "type": "FeatureCollection",
    "properties": {
        "zoom": 0,
        "x": 0,
        "y": 0,
        "compressed": false
    },
    "features": [
        {
            "type": "FeatureCollection",
            "properties": {
                "layer": "paris",
                "version": 2,
                "extent": 4096
            },
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "osm_id": "4217063",
                        "highway": "residential"
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [
                                -187.031250,
                                65.330178
                            ],
                            [
                                -180.000000,
                                64.052978
                            ],
                            [
                                -150.644531,
                                57.984808
                            ]
                        ]
                    }
                },
```


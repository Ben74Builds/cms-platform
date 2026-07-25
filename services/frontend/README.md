# Coverage Monitoring Service (Front-End)

This repo offers a front-end solution to project in a fast and efficient way a high resolution of the service capacity coverage information for critical dispatch services such as an emergency service.

This is made possible thanks to MapBox GL JS and the self production of vector tiles which are really small, enabling global high resolution maps, fast map loads, and efficient caching. 

![Rendering example for Ile-de-France region](img/rendering_example_ile-de-france.jpg)

For real time units tracking (UBER like) you could consider these repo: https://github.com/ds4es/real-time-units-gps-tracking

A demo and usage of various free tile providers can be found here:

* https://leaflet-extras.github.io/leaflet-providers/preview/

# Installation instructions

## Installation de l'environnement

```bash
apt install python3.10-venv
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt
```

Installation des locales (sur Ubuntu)
```bash
sudo apt update && sudo apt upgrade
# Installation des locales
sudo apt install locales
# Génération des locales
sudo locale-gen en_US.UTF-8
sudo locale-gen fr_FR.UTF-8
# Mise à jour de la configuration des locales
sudo update-locale
Vérification des locales installées
locale -a
```

Lancement de l'application
```bash
source env/bin/activate
python3 app.py
```

Builder et lancer le conteneur
```bash
docker build -t service-coverage-monitoring-frontend . && docker run -it --rm --name service-coverage-monitoring-frontend -p 5001:5001 service-coverage-monitoring-frontend 
```

Builder et lancer le conteneur en mode détaché
```bash
docker stop service-coverage-monitoring-frontend
docker rm service-coverage-monitoring-frontend
docker build -t service-coverage-monitoring-frontend . && docker run -d --rm --name service-coverage-monitoring-frontend -p 5001:5001 service-coverage-monitoring-frontend 
```

Accéder au conteneur localement
```bash
docker exec -it service-coverage-monitoring-frontend bash
```

Accéder au conteneur localement
```bash
docker exec -it service-coverage-monitoring-frontend bash
```

Lecture des logs

Accéder au conteneur localement
```bash
docker logs service-coverage-monitoring-frontend
```

Stopper et supprimer les conteneurs
```bash
docker stop $(docker ps -a -q)
docker rm $(docker ps -a -q)
```

## Generate your own vector tiles 

In order to visualize the coverage information stored under `data/coverage`, tiles have to be generated first for regions relative to the index_###.html files available.

We save our tiles in a dedicated folder under `data/tiles/<region_name>`.

Prerequisite packages
```
sudo dnf install wget git expat sqlite-devel proj-devel libnsl
```

Git clone this repo where it will be serve by a web server (like Apache or Nginx)
```
cd /path/to/my/web/server
git clone https://github.com/ds4es/service-coverage-monitoring-frontend
cd service-coverage-monitoring-frontend
```

Pull all git submodules
```
git submodule update --init --recursive
```

#### Install GDAL (with Anaconda things are much more easier)
Install Anaconda
```
# Browse to your Downloads directory
mkdir -p ~/Downloads && cd ~/Downloads
# Download one lastest Anaconda installer suiting your OS
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
# Add execute rights for this installer
chmod +x Miniconda3-latest-Linux-x86_64.sh
# Launch the installation script
./Miniconda3-latest-Linux-x86_64.sh
# Add the Anaconda bin folder location to your PATH variable.
echo 'export PATH="$HOME/miniconda3/bin:$PATH"' | tee -a ~/.bashrc
# Reload ~/.bashrc
. ~/.bashrc
```

Install GDAL
```
conda create -n gdal python
conda activate gdal
conda install -c conda-forge gdal
# Check the installation
ogr2ogr --version
```

#### Build and install tippecanoe
```
cd lib/tippecanoe
make
sudo make install
cd ../../
```

#### Generate vector tiles (example for Luxembourg)
Download any OpenStreetMap .pbf file you would like to render.
```
wget -P ./data/pbf https://download.geofabrik.de/europe/luxembourg-latest.osm.pbf
```
Convert .osm.pbf data to GeoJSON format specifying the data layer to extract, here: lines
```
conda activate gdal
ogr2ogr -f 'GeoJSON' -s_srs 'EPSG:4326' -t_srs 'EPSG:4326' './data/json/luxembourg.json' './data/pbf/luxembourg-latest.osm.pbf' lines
```
Having our data in a GeoJSON file, we can now generate tiles that way:
```
mkdir ./data/tiles/luxembourg
tippecanoe \
	--no-feature-limit \
	--no-tile-size-limit \
	--include={"osm_id","highway"} \
	--maximum-zoom=16 \
	--layer="luxembourg" \
	--output-to-directory "./data/tiles/luxembourg" \
	"./data/json/luxembourg.json"
```

If the repo has been placed under a web server (like Apache or Nginx), you should have the following rendering at http://your_web_server_url/service-coverage-monitoring-frontend/index_luxembourg.html:

![Rendering example for Luxembourg](img/rendering_example_luxembourg.jpg)


### Troubleshooting
#### message: "Unimplemented type: 3"
If you get the following error while rendering in the browser: 
```
Error {message: "Unimplemented type: 3"} message: "Unimplemented type: 3
```

Regenerate your tiles with tippecanoe adding the following argument: `--no-tile-compression`

Cf. https://github.com/mapbox/tippecanoe#setting-or-disabling-tile-size-limits: `-pC` or `--no-tile-compression`: Don't compress the PBF vector tile data. If you are getting "Unimplemented type 3" error messages from a renderer, it is probably because it expects uncompressed tiles using this option rather than the normal gzip-compressed tiles.

## Dashboard :

Basic 
Pie charts états des MMA par :
- SAV
- pompes
- Echelles

Sollicitation des personnels 

Délai d'arrivée d'un 1er MMA sur les interventions passées
Représenté par des boxplot par heure sur les dernières 24 heures
Avec en correspondance les 3 CSTC les plus longs à arriver sur les lieux 


Evolué
non couvert à 10 minutes
couverture à 10 minutes 1 engin
couverture à 10 minutes + d'1 engin
temps de réponse 1er quartile
temps de réponse médian
temps de réponse 3e quartile
temps de réponse maximum

(prédiction du temps d'intervention en fonction des messages)

Sollicitation du personnel

unités prochainement disponible à 15 minutes :

unités prochainement disponible à 1 heure :

CSTC des centroides des zones en souffrances :
1. 	si réallocation amélioration de la couverture de X% à X%
2.
3.  

Main courantes des derniers évènements (onglets: interventions, statuts MMAs, MMAs disponibles, MMA indispo) :
horodatage - XXX

## Additional features :
How to make curved line for 2 points in Leaflet? : https://stackoverflow.com/questions/53502953/how-to-make-curved-line-for-2-points-in-leaflet

# Observation des messages
http://127.0.0.1:5001/topic/paris_gps_status
http://127.0.0.1:5001/topic/paris_coverage_response

# Backup
```bash 
zip -r service-coverage-monitoring-frontend.zip  ./service-coverage-monitoring-frontend  -x "*env*" -x "*.git*" -x "*__pycache__*" -x "*.pbf" -x "*lib/*"
```




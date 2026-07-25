# Service Coverage Monitoring (Back-End)

This project aims to propose a solution to offer a high resolution of the capacity coverage monitoring for critical dispatch services such as an emergency service.   

By **capacity coverage** we mean the information relying on: *How many teams can reach any point of a jurisdiction within a given timeframe?*

Below is an example of how this information could be used in a dispatch application:

![Dispatch application example](https://benjaminberhault.com/images/01-Project-Getting_a_clear_picture_on_the_front_line/option01.jpg)

At some point this project will need one or more machine learning models to estimate accurately the routes. For that purpose a project has been initiated: https://github.com/ds4es/unit-response-oracle

## Installation instructions on RHEL 8 / CentOS 8

```
sudo dnf install wget autoconf automake libtool curl make cmake unzip git gcc-c++ boost boost-devel zlib-devel -y
```
 
Retrieve this repo
```
git clone https://github.com/ds4es/service-coverage-monitoring-backend
cd service-coverage-monitoring-backend
```

Pull all git submodules
```
git submodule update --init --recursive
```

Build and install submodules that needs to be
```
# protobuf
cd ./lib/protobuf && ./autogen.sh
./configure
make
sudo make install
cd ../../
# OSM-binary
make -C ./lib/OSM-binary/src
sudo make -C ./lib/OSM-binary/src install
# RoutingKit
make -C ./lib/RoutingKit
# hiredis
cd ./lib/hiredis
make
sudo make install
# redis-plus-plus
cd ../redis-plus-plus/
mkdir compile
cd compile/
# if you build redis-plus-plus with -std=c++17 standard (i.e. by 
# specifying -DREDIS_PLUS_PLUS_CXX_STANDARD=17 with cmake command)
cmake .. -DREDIS_PLUS_PLUS_CXX_STANDARD=17
make
sudo make install
```

Declare needed shared libraries in the `LD_LIBRARY_PATH` search path environment variable:
```
echo 'export LD_LIBRARY_PATH=\$LD_LIBRARY_PATH:./lib/RoutingKit/lib:/usr/local/lib64:/usr/local/lib' | tee -a ~/.bashrc
. ~/.bashrc
```

## Test

Each script in the test directory got on the top of it build and execute instructions.

_NB: A minimum of 4GB RAM will be required to run those scripts_

```
# Get some data
wget -P ./data/pbf https://download.geofabrik.de/europe/andorra-latest.osm.pbf
# build
g++ -Ilib/RoutingKit/include -Llib/RoutingKit/lib -std=c++11 ./test/pbf_to_contracted_graph.cpp -o ./bin/pbf_to_contracted_graph -lroutingkit -lprotobuf-lite -losmpbf -lz -lboost_serialization
# Run
./bin/graph_properties_preview ./data/pbf/andorra-latest.osm.pbf
```

## Dlib
Compiling and installing DLib
```
git clone https://github.com/davisking/dlib.git
cd dlib/
mkdir build
cd build
cmake .. -DUSE_AVX_INSTRUCTIONS=ON
cmake --build . --config Release
make
sudo make install
sudo ldconfig
```

Build a script with Dlib
```
g++ --std=c++11 kkmeans_ex.cpp -o run -ldlib
```

## Docker
```bash
docker build -t service-coverage-monitoring-backend .
```
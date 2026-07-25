/**
 * Retrieve status + geoloc and record it on a first topic
 * Compute unit coverage and record it on a different topic Redis
 * Publish an update information for unit  
 *
 * # Declare dynamic libraries
 * export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:./lib/RoutingKit/lib:/usr/local/lib64:/usr/local/lib
 * # Build 
 * g++ -Ilib/RoutingKit/include -Llib/RoutingKit/lib  -std=c++11 ./test/capacity_response_from_gps_signals.cpp -o ./bin/capacity_response_from_gps_signals -lredis++ -lhiredis -pthread  -lroutingkit -lprotobuf-lite -losmpbf -lz -lboost_serialization -lstdc++fs
 *
 * # In a first terminal run the build script
 * ./bin/capacity_response_from_gps_signals <channel name>
 * 
 * ex: ./bin/capacity_response_from_gps_signals paris_units_gps_tracking
 * 
 * Avancée actuelle : Ecriture de la couverture dans fichier JSON
 * 
 * # In a second terminal open redis cli
 * redis-cli
 * # Publish messages 
 * PUBLISH channel my_awesome_message
 **/
#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <unordered_set>
#include <algorithm>
#include <iterator>
#include <sw/redis++/redis++.h>
// Graph dependencies
#include <dirent.h>
#include "../src/graph.cpp"

using namespace sw::redis;

/**
 * Split a string by the specified character 
 *
 * @param s the string to split.
 * @param delimiter the character to csider to split the given string.
 * @return a vector of the splitted strings.
 */
std::vector<std::string> split(const std::string& s, char delimiter)                                                                                                                          
{    
    std::vector<std::string> result;
        std::stringstream  ss(s);
        std::string str;
        while (getline(ss, str, delimiter)) {
            result.push_back(str);
        }
    return result;
}

/**
 * Build the graph object
 */
void get_graph(cms::GraphCH &graph){

        std::string path_to_data_files = "./data/backup/paris";

        std::cout << "\n*** Start loading data in memory ***" << std::endl;

        std::cout << "1. Loading the road graph" << std::endl;

        graph.load_from_binary(path_to_data_files + "/graph.dat");

        std::vector<cms::Way> ways(graph.way_osmid.size());

        for (unsigned int i = 0; i < graph.way.size(); i++ ) {
            ways[graph.way[i]].way_idx = graph.way[i];
            ways[graph.way[i]].geo_distance = graph.geo_distance[i];
            // Retrieve the geometry
            ways[graph.way[i]].geometry = "["; 
            ways[graph.way[i]].geometry += graph.get_nodes_from_way(graph.osmwayid_to_idx[graph.way_osmid[graph.way[i]]]).c_str();
            ways[graph.way[i]].geometry += "]";
        }
        std::cout << "For " + std::to_string(ways.size()) + " distinct road segments making up the road graph:" << std::endl;
        std::cout << " - Indexes recovered" << std::endl;
        std::cout << " - Lengths in meters recovered" << std::endl;
        std::cout << " - GPS geometries (polyline) recovered\n" << std::endl;


        std::cout << "2. Loading the contracted form of the road graph" << std::endl;
        graph.load_contraction_hierarchy(path_to_data_files + "/ch.dat");

        std::cout << "*** Loading completed ***" << std::endl;
        std::cout << "graph.way_osmid.size() " << graph.way_osmid.size() << std::endl;
        std::cout << "graph.geo_distance.size() " << graph.geo_distance.size() << std::endl;
        std::cout << "graph.osmwayid_to_idx.size()" << graph.osmwayid_to_idx.size() << std::endl;
        std::cout << "graph.way.size() " << graph.way.size() << std::endl;
        std::cout << "graph.latitude.size() " << graph.latitude.size() << std::endl;
        std::cout << "graph.first_out.size() " << graph.first_out.size() << std::endl;
        std::cout << "graph.head.size() " << graph.head.size() << std::endl;
        std::cout << "graph.node_count " << graph.node_count << std::endl;
        std::cout << "graph.arc_count " << graph.arc_count << std::endl;
       
}

void retrieve_all_uncovered_nodes(cms::GraphCH &graph, std::vector<std::pair<double,double>>) {



}

int main(int argc, char*argv[])
{

    std::string channel;

    if (argc > 1) {
        channel = std::string(argv[1]);
    } else {
        channel = "channel";
    }
    std::string channel_unit_coverage = "paris_units_coverage_up_to_date";

    
    /**
     * Build a graph instance
     */
    cms::GraphCH graph;
    get_graph(graph);

    // Build the index to quickly map latitudes and longitudes
    unsigned threshold = 300;
    threshold = threshold * 1000;

    std::vector<std::string> response_args;
    // pour maintenir les couvertures de chaque unité 
    std::map<std::string, RoutingKit::BitVector> unit_covers;
    // pour maintenir l'information de couverture globale
    std::vector<unsigned short int> service_cover(graph.way_osmid.size(), 0);
    // Uncovered area
    double uncovered_area = 0;
    // Area covered within 10 minutes by one unit
    double area_covered_by_one_unit = 0;
    // Area covered within 10 minutes by more than one unit
    double area_covered_by_more_than_one_unit = 0;
    
    try {
        /**
         * Retrieve status + geoloc and record it on a first topic
         **/
        // Create a Redis object, which is movable but NOT copyable.
        auto redis = Redis("tcp://127.0.0.1:6379");

        auto sub = redis.subscriber();
        sub.on_message([&](std::string channel, std::string msg) {
            // Process message of MESSAGE type.
           
            response_args = split(msg,';');

            std::string unit = response_args[0]; //std::stoi(response_args[0]);

            uncovered_area = 0;
            area_covered_by_one_unit = 0;
            area_covered_by_more_than_one_unit = 0;
            /**
             * Record an up to date unit status, latitude and longitude on Redis
             **/
            std::string status = response_args[1];
            redis.set("mma:"+unit+":status", status);
            float latitude = std::stof(response_args[2]);
            std::string latitude_s = response_args[2];
            redis.set("mma:"+unit+":lat", latitude_s);
            float longitude = std::stof(response_args[3]);
            std::string longitude_s = response_args[3];
            redis.set("mma:"+unit+":lon", longitude_s);

            bool should_we_process = std::stoi(response_args[4].c_str());
            //if (should_we_process){

                /**
                 * Compute unit coverage 
                 **/

                RoutingKit::GeoPositionToNode map_geo_position(graph.latitude, graph.longitude);

                // récupère le noeud le plus proche de la position
                std::cout << latitude << ',' << longitude << std::endl;
                unsigned source = map_geo_position.find_nearest_neighbor_within_radius(latitude, longitude, 1000).id;

                std::cout << "Node: " << source << ' ' << msg << std::endl;
       
                // calcul de la couverture de l'unité
                if(source != RoutingKit::invalid_id){

                    std::string unit_coverage_stringify;
                    std::string output;
  

                    output = "{\"service\": \"not set yet\""
                        ",\"unit\":" + unit +
                        ",\"datetime\": \"not set yet\""
                        ",\"color\":\"" + status + "\""
                        ",\"latitude\":" + latitude_s +
                        ",\"longitude\":" + longitude_s;

                    if (status == "Green") {
                        RoutingKit::BitVector node_bit_vector(graph.node_count);
                        RoutingKit::BitVector way_bit_vector(graph.way_osmid.size());

                        /**********
                         * Calcul de la nouvelle information de couverture
                         **/
                        // Calcul direct
                        // graph.unit_coverage(way_bit_vector, source);
                        
                        // Calcul avec conservation de l'information de couverture des noeuds
                        graph.unit_coverage_on_nodes(node_bit_vector, source);
                        for (unsigned i = 0; i < graph.head.size(); ++i)
                        {
                            if(node_bit_vector.is_set(graph.head[i]) && node_bit_vector.is_set(graph.tail[i])) {
                                way_bit_vector.set(graph.way[i], 1);
                            }
                        }
                        /**
                         * Fin du calcul de la nouvelle information de couverture
                         **********/
                         
                        // Mise à jour de l'information de couverture "service_cover" maintenue globalement
                        if ( unit_covers.find(unit) == unit_covers.end() ) {
                            // "unit" not found 
                            for (unsigned i = 0; i < graph.way_osmid.size(); ++i)
                            {
                                if(way_bit_vector.is_set(i))
                                    // way_bit_to_increment
                                    service_cover[i]++;
                            }
                        } else {
                            // "unit" found
                            for (unsigned i = 0; i < graph.way_osmid.size(); ++i)
                            {
                                if(way_bit_vector.is_set(i) && !(unit_covers[unit].is_set(i)))
                                    // way_bit_to_increment
                                    service_cover[i]++;

                                if(!(way_bit_vector.is_set(i)) && unit_covers[unit].is_set(i))
                                    // way_bit_to_decrement
                                    service_cover[i]--;
                            }
                        }
                        
                        // this retrieve nodes from 0 unit covered ways SUITE
                        /*
                        int o;
                        for (uint64_t i = 0; i < service_cover.size(); ++i) 
                        {
                            if(service_cover[i] == 0) {
                                std::vector<std::pair<double,double>> my_vector = graph.get_nodes_from_way_into_vec(i);
                                for(int j = 0; j < my_vector.size(); j++)
                                    std::cout << '[' <<  my_vector[j].first << ", " << my_vector[j].second << "]," ;
                                std::cout << std::endl;    
                            }
                                
                            o++;
                            if (o> 10)
                                break;
                        }
                        */

                        // peut être optimisé
                        for (unsigned i = 0; i < graph.way_osmid.size(); ++i)
                        {
                            switch (service_cover[i]) {
                                case 0: 
                                    uncovered_area += (double) graph.get_geo_distance_from_way(i);
                                    break;
                                case 1: 
                                    area_covered_by_one_unit += (double) graph.get_geo_distance_from_way(i);
                                    break;
                                default: 
                                    area_covered_by_more_than_one_unit += (double) graph.get_geo_distance_from_way(i);
                            }
                            /*
                            if(service_cover[i] == 0)
                                uncovered_area += (double) graph.get_geo_distance_from_way(i);

                            if(service_cover[i] == 1)
                                area_covered_by_one_unit += (double) graph.get_geo_distance_from_way(i);
                            
                            if(service_cover[i] > 1)
                                area_covered_by_more_than_one_unit += (double) graph.get_geo_distance_from_way(i);
                            */
                            
                        }

                        double total_geo_distances = uncovered_area + area_covered_by_one_unit + area_covered_by_more_than_one_unit;

                        std::cout << "Total geo distances: " << total_geo_distances << " meters" << std::endl;
                        std::cout << "Uncovered area: " << uncovered_area << " meters -> " << uncovered_area / total_geo_distances * 100 << "%" << std::endl;
                        std::cout << "Area covered within 10 minutes by one unit: " << area_covered_by_one_unit << " meters -> " << area_covered_by_one_unit / total_geo_distances * 100 << "%" << std::endl;
                        std::cout << "Area covered within 10 minutes by more than one unit: " << area_covered_by_more_than_one_unit << " meters -> " << area_covered_by_more_than_one_unit / total_geo_distances * 100 << "%" << std::endl;

                        // Sauvegarde de la nouvelle information de couverture pour l'unité
                        unit_covers[unit] = way_bit_vector;

                        // assess for each way if it could be reach under the defined threshold 
                        // (a way is covered if both extrimity node can be reach under the defined threshold)		
                        std::cout << "unit coverage computed" << std::endl;
                        
                        std::unordered_set<std::string> unit_coverage_set;

                        // Récupération des ways courverts par l'unité
                       for (unsigned i = 0; i < graph.way_osmid.size(); ++i)
                        {
                            if(way_bit_vector.is_set(i)) {
                                // conservation de l'information au sein de Redis
                                unit_coverage_set.insert(std::to_string(i));
                                // préparation du message à publier 
                                unit_coverage_stringify = unit_coverage_stringify + "\"" + std::to_string(graph.way_osmid[i])+"\",";
                            }
                        }


                        
                        // On supprime la dernière "," de trop
                        unit_coverage_stringify = unit_coverage_stringify.substr(0, unit_coverage_stringify.size()-1);

                        // Record the computed unit coverage on Redis
                        const StringView redis_key = "mma:"+unit+":coverage";
                        redis.sadd(redis_key, unit_coverage_set.begin(), unit_coverage_set.end());
  
                        // finalisation du message à publier
                        output += ",\"coverage\":["+ unit_coverage_stringify+"]";
                        output += ",\"uncovered_area\":" + std::to_string(round(uncovered_area / total_geo_distances * 100));
                        output += ",\"area_covered_by_one_unit\":" + std::to_string(round(area_covered_by_one_unit / total_geo_distances * 100));
                        output += ",\"area_covered_by_more_than_one_unit\": " + std::to_string(round(area_covered_by_more_than_one_unit / total_geo_distances * 100));

                    } else {

                        redis.set("mma:"+unit+":coverage", "");

                    };

                    output += "}";

                    redis.publish(channel_unit_coverage, output); // output);// 

                } else {
                    std::cout << "No node within 1000m from source position" << std::endl;
                }

            //} // if (should_we_process)

        });
        sub.subscribe(channel);
        //sub.psubscribe("pattern*");
        while (true) {
            try {
                sub.consume();
            } catch (const Error &err) {
                // Handle exceptions.
            }
        }


    } catch (const Error &err) {
        // Handle exceptions.
    }
	return 0;
}
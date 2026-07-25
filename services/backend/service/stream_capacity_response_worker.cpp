/**
 * Retrieve status + geoloc and record it on a first topic
 * Compute unit coverage and record it on a different topic Redis
 * Publish an update information for unit  
 *
 * # Declare dynamic libraries
 * export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:./lib/RoutingKit/lib:/usr/local/lib64:/usr/local/lib
 * # Build 
 * g++ -Ilib/RoutingKit/include -Llib/RoutingKit/lib -std=c++17 ./service/stream_capacity_response_worker.cpp -o ./bin/stream_capacity_response_worker -lredis++ -lhiredis -pthread  -lroutingkit -lprotobuf-lite -losmpbf -lz -lboost_serialization -lstdc++fs
 *
 * # In a first terminal run the build script
 * ./bin/stream_capacity_response_worker <channel name>
 * 
 * ex: ./bin/stream_capacity_response_worker paris_units_gps_tracking
 * 
 * Avancée actuelle : Ecriture de la couverture dans fichier JSON
 * 
 * # In a second terminal open redis cli
 * redis-cli
 * # Publish messages 
 * PUBLISH channel my_awesome_message
 **/
// Compile with -DDEBUG flag to enable messages
#ifdef DEBUG
#define D(x) (std::cerr << "**DEBUG message**: " << (x) << std::endl)
#else 
#define D(x) do{}while(0)
#endif

#include <iostream>
#include <fstream>
#include <sstream>  
#include <string>
#include <vector>
#include <unordered_set>
#include <algorithm>
#include <iterator>
#include <sw/redis++/redis++.h>
//debug
#include <typeinfo>
// Graph dependencies
#include <dirent.h>
#include "../src/graph.cpp"

namespace config {
    const bool PRINT_MESSAGES = true;
    const unsigned THRESHOLD = 300; // In milliseconds

    // Service prefix from env var, default "paris"
    inline std::string get_env_or(const char* var, const char* def) {
        const char* v = std::getenv(var);
        return v ? std::string(v) : std::string(def);
    }

    const std::string SERVICE = get_env_or("CMS_SERVICE", "paris");
    const std::string PATH_TO_THE_PREBUILD_GRAPH = get_env_or("CMS_GRAPH_PATH", "./data/backup/paris");

    //Redis config
    const std::string REDIS_HOST = "localhost";
    const std::string REDIS_PORT = "6379";
    const std::string REDIS_PASSWORD = "";
    const std::string REDIS_CHANNEL_GPS_AND_UNITS_STATUS = SERVICE + "_gps_status";
    const std::string REDIS_CHANNEL_COVERAGE_UPDATE = SERVICE + "_capacity_response";
    const int REDIS_MESSAGE_LENGTH = 6;
}

using namespace sw::redis;
using namespace config;

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
void get_graph(cms::GraphCH &graph, std::string path_to_the_prebuild_graph){

        cout_message("\n*** Start loading data in memory ***");

        cout_message("1. Loading the road graph");
        graph.load_from_binary(path_to_the_prebuild_graph + "/graph.dat");

        std::vector<cms::Way> ways(graph.way_osmid.size());

        for (unsigned int i = 0; i < graph.way.size(); i++ ) {
            ways[graph.way[i]].way_idx = graph.way[i];
            ways[graph.way[i]].geo_distance = graph.geo_distance[i];
            // Retrieve the geometry
            ways[graph.way[i]].geometry = "["; 
            ways[graph.way[i]].geometry += graph.get_nodes_from_way(graph.osmwayid_to_idx[graph.way_osmid[graph.way[i]]]).c_str();
            ways[graph.way[i]].geometry += "]";
        }
        cout_message("For " + std::to_string(ways.size()) + " distinct road segments making up the road graph:"); 
        cout_message(" - Indexes recovered"); 
        cout_message(" - Lengths in meters recovered"); 
        cout_message(" - GPS geometries (polyline) recovered\n");  


        cout_message("2. Loading the contracted form of the road graph");
        graph.load_contraction_hierarchy(path_to_the_prebuild_graph + "/ch.dat");

        cout_message("*** Loading completed ***");

        cout_message("3. Data check");
        std::cout << "graph.way_osmid.size() " << graph.way_osmid.size() << std::endl;
        std::cout << "graph.geo_distance.size() " << graph.geo_distance.size() << std::endl;
        std::cout << "graph.osmwayid_to_idx.size()" << graph.osmwayid_to_idx.size() << std::endl;
        std::cout << "graph.way.size() " << graph.way.size() << std::endl;
        std::cout << "graph.latitude.size() " << graph.latitude.size() << std::endl;
        std::cout << "graph.first_out.size() " << graph.first_out.size() << std::endl;
        std::cout << "graph.head.size() " << graph.head.size() << std::endl;
        std::cout << "graph.node_count " << graph.node_count << std::endl;
        std::cout << "graph.arc_count " << graph.arc_count << std::endl;
        //std::cout << "Premier way" << "[" << graph.get_nodes_from_way(graph.osmwayid_to_idx[graph.way_osmid[graph.way[0]]]).c_str() << "]" << std::endl;

       
}

void retrieve_all_uncovered_nodes(cms::GraphCH &graph, std::vector<std::pair<double,double>>) {


}

int main(int argc, char*argv[])
{

    std::string channel = (argc > 1) ? std::string(argv[1]) : REDIS_CHANNEL_GPS_AND_UNITS_STATUS;
    cout_message("REDIS CHANNEL USED: "+channel);

    cms::GraphCH graph;
    // Load a graph instance
    get_graph(graph, PATH_TO_THE_PREBUILD_GRAPH);

    std::vector<std::string> exploded_message;
    /*
    // pour maintenir les couvertures de chaque unité 
    std::map<std::string, RoutingKit::BitVector> unit_covers;
    // pour maintenir l'information de couverture globale
    std::vector<unsigned short int> service_cover(graph.way_osmid.size(), 0);
    */
    RoutingKit::BitVector node_bit_vector(graph.node_count);
    RoutingKit::BitVector way_bit_vector(graph.way_osmid.size());
    std::map<std::string, RoutingKit::BitVector> coverage_for_each_unit;                                // couverture de chaque unité 
    std::vector<unsigned short int> coverage_aggregated_for_the_service(graph.way_osmid.size(), 0);     // couverture globale
    double uncovered_area = 0;                      // Measure of uncovered areas
    double area_covered_by_one_unit = 0;            // Measure of areas covered within 10 minutes by one unit  
    double area_covered_by_more_than_one_unit = 0;  // Measure of area covered within 10 minutes by more than one unit
    
    try {
        /**
         * Retrieve status + geoloc and record it on a first topic
         **/
        // Create a Redis object, which is movable but NOT copyable.
        auto redis = Redis("tcp://"+REDIS_HOST+":"+REDIS_PORT);
        // Instanciate a Redis subscriber
        auto sub = redis.subscriber();

        sub.on_message([&](std::string channel, std::string message) {

            uncovered_area = 0;
            area_covered_by_one_unit = 0;
            area_covered_by_more_than_one_unit = 0;

            float latitude, longitude;
            bool free, try_compute_service_coverage;
            std::string output = "{\"service\": \"" + SERVICE + "\"";
       
            // Explode the received message
            exploded_message = split(message,';');
            int message_size = ((exploded_message.size())-1)/REDIS_MESSAGE_LENGTH;
       
            output += ",\"date\": \"" + exploded_message[0] + "\"";
            output += ",\"units\": {";

            bool is_there_at_least_one_coverage_data_update = false;

            for (size_t i = 0; i < message_size; i++)
            { 
                const std::string unit = exploded_message[1+i];
                //output += "{\"unit\":" + unit;

                std::string redis_key = SERVICE+":mma:"+unit;

                const std::string& status = exploded_message[2+i];
                //if(status != "None")
                    // output += ",\"status\":\"" + status + "\"";
        
                const std::string& latitude_s = exploded_message[3+i];
                if(latitude_s != "None") {
                    latitude = std::stof(latitude_s);
                    // output += ",\"lat\":" + latitude_s;
                }
                const std::string& longitude_s = exploded_message[4+i];
                if(longitude_s != "None") {
                    longitude = std::stof(longitude_s);
                    // output += ",\"lon\":" + longitude_s;
                }

                free = 0;
                const std::string& free_s = exploded_message[5+i];
                if(free_s != "None") {
                    std::istringstream(free_s) >> free;
                    // output +=",\"free\":" + free_s;
                }

                std::istringstream(exploded_message[6+i]) >> try_compute_service_coverage;

                if (try_compute_service_coverage == true){

                    std::cout << "MESSAGE: " << message << std::endl;
                       
                    /**
                     * Compute unit coverage 
                     **/

                    // On récupère le noeud le plus proche de la position

                    // calcul de la couverture de l'unité

                    std::cout << "free: " << free << std::endl;
                    if (free == true) {

                        RoutingKit::GeoPositionToNode map_geo_position(graph.latitude, graph.longitude);
                        unsigned source = map_geo_position.find_nearest_neighbor_within_radius(latitude, longitude, 1000).id;

                        // Si un noeud valide est trouvé on calcul la couverture
                        if(source != RoutingKit::invalid_id){
                            D( cout_message("Coordonnées GPS de l'unité: " + std::to_string(latitude) + "," + std::to_string(longitude)); );
                            D( cout_message("Noeud du graphe routier le plus proche: " + std::to_string(source)); );
                            cout_message("Coordonnées GPS de l'unité: " + std::to_string(latitude) + "," + std::to_string(longitude)); 
                            cout_message("Noeud du graphe routier le plus proche: " + std::to_string(source));

                            /**********
                             * GPU-accelerated fused coverage computation
                             **/
                            cout_message(" 1. Calcul de la nouvelle information de couverture");
                            graph.unit_coverage_gpu_fused(node_bit_vector, way_bit_vector, source, THRESHOLD);
                            cout_message("    Fin de calcul de la nouvelle information de couverture");
                            /**
                             * Fin du calcul de la nouvelle information de couverture
                             **********/

                            // assess for each way if it could be reach under the defined threshold 
                            // (a way is covered if both extrimity node can be reach under the defined threshold)		
                                                       
                            /**********
                             * Mise à jour de l'information de couverture "coverage_aggregated_for_the_service" maintenue globalement
                             **/
                            cout_message(" 2. Mise à jour de l'information de couverture \"coverage_aggregated_for_the_service\" maintenue globalement");
                            if ( coverage_for_each_unit.find(unit) == coverage_for_each_unit.end() ) {
                                //cout_message("    unit not found ");
                                for (unsigned i = 0; i < graph.way_osmid.size(); ++i)
                                {
                                    if(way_bit_vector.is_set(i)) {
                                        // way_bit_to_increment
                                        coverage_aggregated_for_the_service[i]++;
                                        //std::cout << "+1,";
                                    }
                                }
                            } else {
                                //cout_message("    unit found ");
                                for (unsigned i = 0; i < graph.way_osmid.size(); ++i)
                                {
                                    if(way_bit_vector.is_set(i) && !(coverage_for_each_unit[unit].is_set(i))) {
                                        // way_bit_to_increment
                                        coverage_aggregated_for_the_service[i]++;
                                        //std::cout << "+1,";
                                    }

                                    if(!(way_bit_vector.is_set(i)) && coverage_for_each_unit[unit].is_set(i)) {
                                        // way_bit_to_decrement
                                        coverage_aggregated_for_the_service[i]--;
                                        //std::cout << "-1,";
                                    }
                                }
                            }
                            cout_message("    Fin de mise à jour de l'information de couverture \"coverage_aggregated_for_the_service\" maintenue globalement");
                            /**
                             * Fin de la mise à jour de l'information de couverture "coverage_aggregated_for_the_service" maintenue globalement
                             **********/

                            /**********
                             * Récupération et concaténation des ID OSM des ways couverts par l'unité
                             **/
                            cout_message(" 3. Récupération et concaténation des ID OSM des ways couverts par l'unité");
                            std::unordered_set<std::string> unit_coverage_set;

                            // Récupération des ways courverts par l'unité
                            for (unsigned i = 0; i < graph.way_osmid.size(); ++i) {
                                if(way_bit_vector.is_set(i)) {
                                    // conservation de l'information au sein de Redis
                                    unit_coverage_set.insert(std::to_string(i));
                                    // préparation du message à publier 
                                    // unit_coverage_stringify = unit_coverage_stringify + "\"" + std::to_string(graph.way_osmid[i])+"\",";
                                }
                            }
                            cout_message("    Fin de récupération et concaténation des ID OSM des ways couverts par l'unité");

                            // On supprime la dernière "," de trop
                            // unit_coverage_stringify = unit_coverage_stringify.substr(0, unit_coverage_stringify.size()-1);

                            /**
                             * Fin de récupération et concaténation des ID OSM des ways couverts par l'unité
                             **********/

                            //DEBUG Check nodes_previously_covered_by_the_unit
                            std::cout << "    Aperçu des ID OSM des ways couverts par l'unité: ";
                            int i = 0;
                            for (auto elem : unit_coverage_set) {
                                i++;
                                std::cout << elem ;
                                if(i == 10)
                                    break;
                                std::cout << ",";
                            }
                            std::cout << "..." << std::endl;
                            // Fin de heck nodes_previously_covered_by_the_unit

                            // Record the computed unit coverage on Redis
                            cout_message(" 4. Record the computed unit coverage on Redis");
                            const StringView redis_key_sv = redis_key+":coverage";
                            redis.sadd(redis_key+":coverage", unit_coverage_set.begin(), unit_coverage_set.end());
                            cout_message("    Fin de record the computed unit coverage on Redis");
        
                            // Finalisation du message de l'unité à publier
                            // output += ",\"coverage\":[" + unit_coverage_stringify + "]";

                            output += unit+":1,";   
                            is_there_at_least_one_coverage_data_update = true;     


                            // Sauvegarde de la nouvelle information de couverture pour l'unité
                            coverage_for_each_unit[unit] = way_bit_vector;
                    

                        } else {
                            std::cout << "No node within 1000m from source position" << std::endl;
                        }

                        std::cout << std::endl;

                    } else {
                        
                        cout_message(" 1. Suppression de l'information de couverture de ");
                        auto val = redis.get(redis_key+":coverage");
                        if(val) {

                            cout_message(redis_key+":coverage");
                            std::unordered_set<std::string> nodes_previously_covered_by_the_unit;

                            redis.smembers(redis_key+":coverage", std::inserter(nodes_previously_covered_by_the_unit, nodes_previously_covered_by_the_unit.begin()));
                            
                            //DEBUG 
                            std::cout << "Précédente données stockées: ";
                            int i = 0;
                            for (auto elem : nodes_previously_covered_by_the_unit) {
                                i++;
                                std::cout << elem << ",";
                                if(i == 10)
                                    break;
                            }
                            std::cout << std::endl;
                            // Fin de heck nodes_previously_covered_by_the_unit

                            for (auto elem : nodes_previously_covered_by_the_unit) {
                                coverage_aggregated_for_the_service[stoi(elem)]--;
                            }
                            redis.hset(redis_key,":coverage", "");
                            output += unit+":0,";
                            is_there_at_least_one_coverage_data_update = true;     
                        }
                        cout_message("    Fin de suppression de l'information de couverture de ");

                    };

                } // END: if (try_compute_service_coverage)
                output = output.substr(0, output.size()-1);
                output += "},";
            } // END: for (size_t i = 0; i < message_size; i++)


            if (is_there_at_least_one_coverage_data_update == true) {

                /**********
                 * Recalcul des 3 valeurs d'évaluation de la couverture
                 **/
                cout_message(" X. Recalcul des 3 valeurs d'évaluation de la couverture");
                std::cout << "    graph.way_osmid.size(): " << graph.way_osmid.size() << std::endl;
                int j = 0;
                for (unsigned i = 0; i < graph.way_osmid.size(); ++i)
                {
                    // Fin de heck nodes_previously_covered_by_the_unit
                    switch (coverage_aggregated_for_the_service[i]) {
                        case 0: 
                            uncovered_area += (double) graph.get_geo_distance_from_way(i);
                            break;
                        case 1: 
                            area_covered_by_one_unit += (double) graph.get_geo_distance_from_way(i);
                            break;
                            j++;
                        default: 
                            area_covered_by_more_than_one_unit += (double) graph.get_geo_distance_from_way(i);
                    }                            
                }
                std::cout << "    For loop " << j << std::endl;
                cout_message("    Fin de recalcul des 3 valeurs d'évaluation de la couverture");
                /**
                 * Fin du recalcul des 3 valeurs d'ébaluation de la couverture
                 **********/

                double total_geo_distances = uncovered_area + area_covered_by_one_unit + area_covered_by_more_than_one_unit;

                std::cout << "Total geo distances: " << total_geo_distances << " meters" << std::endl;
                std::cout << "Uncovered area: " << uncovered_area << " meters -> " << uncovered_area / total_geo_distances * 100 << "%" << std::endl;
                std::cout << "Area covered within 10 minutes by one unit: " << area_covered_by_one_unit << " meters -> " << area_covered_by_one_unit / total_geo_distances * 100 << "%" << std::endl;
                std::cout << "Area covered within 10 minutes by more than one unit: " << area_covered_by_more_than_one_unit << " meters -> " << area_covered_by_more_than_one_unit / total_geo_distances * 100 << "%" << std::endl;

                output = output.substr(0, output.size()-1);
                output += ",\"uncovered_area\":" + std::to_string(round(uncovered_area / total_geo_distances * 100));
                output += ",\"area_covered_by_one_unit\":" + std::to_string(round(area_covered_by_one_unit / total_geo_distances * 100));
                output += ",\"area_covered_by_more_than_one_unit\": " + std::to_string(round(area_covered_by_more_than_one_unit / total_geo_distances * 100));
                output += "}";

                std::cout << "Enfin quelque chose à publier: " << output << std::endl;

                redis.publish(REDIS_CHANNEL_COVERAGE_UPDATE, output);
            }
        });

        sub.subscribe(channel);

        while (true) {
            try {
                sub.consume();
            } catch (const Error &err) {
                // Handle exceptions.
                std::cerr << err.what();
            }
        }

    } catch (const Error &err) {
        // Handle exceptions.
        std::cerr << err.what();
    }
	return 0;
}
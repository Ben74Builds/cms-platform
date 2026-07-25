/**
 * This script load a road graph from an OpenStreetMap PBF file,
 * save its properties and the contracted form for later reuse
 *
 * COMPILE AND EXECUTE
 * Kafka et Zookeeper doivent être démarrés
 * # Compile:
 * g++ -Ilib/RoutingKit/include -Llib/RoutingKit/lib -std=c++17 ./service/stream_geo_worker.cpp -o ./bin/stream_geo_worker -lpthread -lroutingkit -lprotobuf-lite -losmpbf -lz -lboost_serialization  -lrdkafka++ -lpq -lpqxx  -lredis++ -lhiredis
 * 
 * NB 
 *  source: https://stackoverflow.com/questions/23250863/difference-between-pthread-and-lpthread-while-compiling
 *  -pthread tells the compiler to link in the pthread library as well as configure the compilation for threads. Using the -lpthread option only causes the pthread library to be linked - the pre-defined macros don't get defined. Bottom line: you should use the -pthread option.
 * 
 * # Launch the generated executable
 * ./bin/stream_geo_worker
 * 
 * # Tester lançant dans un autre terminal une console d'envoi de messages Kafka
 * ~/Kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topiayaa
 * 
 * # Transmettre un message conforme
 * 48.884113,2.289324,48.8669931,2.3545479
 */
#include <string>
#include <sstream>
#include <thread>
#include "rapidjson/document.h"
#include "../src/graph.cpp"
#include "../src/kafka.cpp"
#include <sw/redis++/redis++.h>

#include <iostream>
#include <memory>

/**
 * PERFORMANCE OPTIMIZATION: Iterate only set bits in BitVector
 * Instead of O(n) loop through all bits, this is O(k) where k = number of set bits
 * Uses __builtin_ctzll (count trailing zeros) for efficient bit scanning
 */
template<typename Func>
inline void for_each_set_bit(const RoutingKit::BitVector& bv, Func&& func) {
    const uint64_t* data = bv.data();
    const uint64_t size = bv.size();
    const uint64_t num_words = (size + 63) / 64;

    for (uint64_t word_idx = 0; word_idx < num_words; ++word_idx) {
        uint64_t word = data[word_idx];
        while (word != 0) {
            // Find position of lowest set bit
            int bit_pos = __builtin_ctzll(word);
            uint64_t global_idx = word_idx * 64 + bit_pos;

            // Check bounds and call function
            if (global_idx < size) {
                func(global_idx);
            }

            // Clear the lowest set bit
            word &= (word - 1);
        }
    }
}


struct AllocationMetrics {
    uint32_t TotalAllocated = 0;
    uint32_t TotalFreed = 0;

    uint32_t CurrentUsage() {
        return TotalAllocated - TotalFreed;
    }
};

static AllocationMetrics s_AllocationMetrics;

void* operator new(size_t size)
{
    s_AllocationMetrics.TotalAllocated += size;
    //std::cout << "Allocating " << size << " bytes\n";
    return malloc(size);
}


void operator delete(void* memory, size_t size)
{
    s_AllocationMetrics.TotalFreed += size;
    //std::cout << "Freeing " << size << " bytes\n";

    free(memory);
}

static void PrintMemoryUsage()
{
    std::cout << "Memory Usage: " << s_AllocationMetrics.CurrentUsage() << " bytes\n";
}



/**
 * Build the graph object
 */
void get_graph(cms::GraphCH &graph, std::string path_to_data_files = "./data/backup/paris"){

  cout_message("\n*** Start loading data in memory ***");

  cout_message("1. Loading the road graph");
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
  cout_message("For " + std::to_string(ways.size()) + " distinct road segments making up the road graph:"); 
  cout_message(" - Indexes recovered"); 
  cout_message(" - Lengths in meters recovered"); 
  cout_message(" - GPS geometries (polyline) recovered\n");  


  cout_message("2. Loading the contracted form of the road graph");
  graph.load_contraction_hierarchy(path_to_data_files + "/ch.dat");

  cout_message("3. Loading building-to-segment mapping for building coverage");
  graph.load_building_mapping(path_to_data_files + "/building_segment_mapping.json");

  cout_message("*** Loading completed ***");

}

class KafkaConsumerToRoutePlannerProducer : public KafkaConsumer
{
  KafkaMessageProducer &producer;
  cms::GraphCH &graph;  

  public:  
    using KafkaConsumer::KafkaConsumer;
    KafkaConsumerToRoutePlannerProducer(
      std::string brokers_
      , std::string kafka_topic_
      , KafkaMessageProducer &producer_
      , cms::GraphCH &graph_
    ):
      KafkaConsumer(brokers_,kafka_topic_)
      , producer(producer_)
      , graph(graph_)
    {};

    void custom_consume(RdKafka::Message* message) {
      
      std::cout << "**RoutePlannerProducer** ";

      rapidjson::Document document = parse(message);
      if(document.IsObject() == 0)
        return;

      std::string routes;
      std::string date = document["date"].GetString();
      int serv = document["serv"].GetInt();

      // try to get a route for each unit
      // otherwise send back po1 and gp2 lon and lat
      for (rapidjson::Value::ConstValueIterator itr = document["data"].Begin(); itr != document["data"].End(); ++itr) { // Ok

        if (itr -> HasMember("uni")) { // Ok
          std::string unit =  rapidjson_element_to_string(( * itr),"uni");
          float lat1 = ( * itr)["gp1"][0].GetDouble();
          float lng1 = ( * itr)["gp1"][1].GetDouble();
          float lat2 = ( * itr)["gp2"][0].GetDouble();
          float lng2 = ( * itr)["gp2"][1].GetDouble();

          bool do_we_have_a_route = false;
          routes = routes + "{\"uni\":" + unit + ",";
          try {

            std::string route = graph.get_route_lat_lon_nodes(lat1, lng1, lat2, lng2);

            if (route != "[]" && route != "") {
              do_we_have_a_route = true;
              routes = routes + "\"route\":" + route + "},";
              
            }

          } catch (std::exception & err) {

            printf("Unable to calculate route with source: [%.9g,%.9g] and target: [%.9g,%.9g]\n", lat1, lng1, lat2, lng2);

          }

          if (do_we_have_a_route == false)
            routes = routes + "\"gp1\":[" + std::to_string(lat1) + "," + std::to_string(lng1) + "],\"gp2\":[" + std::to_string(lat2) + "," + std::to_string(lng2) + "]},";

        }
      }

      // Remove the extra ","
      routes.pop_back();
      std::cout << "Response: " << "{\"date\":\"" + date + "\",\"serv\":" + std::to_string(serv) + ",\"routes\":[" + routes + "]}" << std::endl;
      // Send the message through Kafka
      producer.kafka_message_builder("{\"date\":\"" + date + "\",\"serv\":" + std::to_string(serv) + ",\"routes\":[" + routes + "]}");
      
      
    }
};



// class KafkaConsumerToCoverageProducer : public KafkaConsumer
// {
//   KafkaMessageProducer &producer;
//   cms::GraphCH &graph;  

//   public:  
//     using KafkaConsumer::KafkaConsumer;
//     KafkaConsumerToCoverageProducer(
//       std::string brokers_
//       , std::string kafka_topic_
//       , KafkaMessageProducer &producer_
//       , cms::GraphCH &graph_
//     ):
//       KafkaConsumer(brokers_,kafka_topic_)
//       , producer(producer_)
//       , graph(graph_)
//     {};

//     void custom_consume(RdKafka::Message* message) {

//       rapidjson::Document document = parse(message);
//       if(document.IsObject() == 0)
//         return;

//       std::string routes;
//       std::string date = document["date"].GetString();
//       int serv = document["serv"].GetInt();

//       // try to get a route for each unit
//       // otherwise send back po1 and gp2 lon and lat
//       for (rapidjson::Value::ConstValueIterator itr = document["data"].Begin(); itr != document["data"].End(); ++itr) { // Ok

//         if (itr -> HasMember("uni")) { // Ok
//           std::string unit =  rapidjson_element_to_string(( * itr),"uni");
//           float lat1 = ( * itr)["gp1"][0].GetFloat();
//           float lng1 = ( * itr)["gp1"][1].GetFloat();
//           float lat2 = ( * itr)["gp2"][0].GetFloat();
//           float lng2 = ( * itr)["gp2"][1].GetFloat();

//           bool do_we_have_a_route = false;
//           routes = routes + "{\"uni\":" + unit + ",";
//           try {

//             std::string route = graph.get_route_lat_lon_nodes(lat1, lng1, lat2, lng2);

//             if (route != "[]" && route != "") {
//               do_we_have_a_route = true;
//               routes = routes + "\"route\":" + route + "},";
              
//             }

//           } catch (std::exception & err) {

//             printf("Unable to calculate route with source: [%.9g,%.9g] and target: [%.9g,%.9g]\n", lat1, lng1, lat2, lng2);

//           }

//           if (do_we_have_a_route == false)
//             routes = routes + "\"gp1\":[" + std::to_string(lat1) + "," + std::to_string(lng1) + "],\"gp2\":[" + std::to_string(lat2) + "," + std::to_string(lng2) + "]},";

//         }
//       }

//       // Remove the extra ","
//       routes.pop_back();
//       std::cout << "Response: " << "{\"date\":\"" + date + "\",\"serv\":" + std::to_string(serv) + ",\"routes\":[" + routes + "]}" << std::endl;
//       // Send the message through Kafka
//       producer.kafka_message_builder("{\"date\":\"" + date + "\",\"serv\":" + std::to_string(serv) + ",\"routes\":[" + routes + "]}");
      
      
//     }
// };



class KafkaConsumerToCoverageProducer : public KafkaConsumer
{
  KafkaMessageProducer &producer;
  cms::GraphCH &graph;
  sw::redis::Redis &redis;
  std::string service_name;  // e.g. "paris", "annecy" — for per-service Redis keys

  RoutingKit::BitVector node_bit_vector;
  RoutingKit::BitVector way_bit_vector;
  std::map<std::string, RoutingKit::BitVector> coverage_for_each_unit;                                // couverture de chaque unité
  std::vector<unsigned short int> coverage_aggregated_for_the_service;     // couverture globale
  std::unordered_map<uint64_t, int> batch_delta_changes;  // Track changes per batch for aggregated broadcast
  std::unordered_map<uint64_t, int> building_coverage_snapshot;  // Full building coverage state for snapshot API
  double uncovered_area = 0;                      // Measure of uncovered areas
  double area_covered_by_one_unit = 0;            // Measure of areas covered within 10 minutes by one unit
  double area_covered_by_more_than_one_unit = 0;  // Measure of area covered within 10 minutes by more than one unit

  unsigned int THRESHOLD = 300;  // Default, overridden by message 'threshold' field if present

  public:
    using KafkaConsumer::KafkaConsumer;
    KafkaConsumerToCoverageProducer(
      std::string brokers_
      , std::string kafka_topic_
      , KafkaMessageProducer &producer_
      , cms::GraphCH &graph_
      , sw::redis::Redis &redis_
      , std::string service_name_
    ):
      KafkaConsumer(brokers_,kafka_topic_)
      , producer(producer_)
      , graph(graph_)
      , redis(redis_)
      , service_name(service_name_)
      , way_bit_vector(graph_.way_osmid.size())
      , node_bit_vector(graph_.node_count)
      , coverage_aggregated_for_the_service(graph_.way_osmid.size(), 0)
    { };

    /*****
     * Exemple de message
     * {
     *  'date': '2019-01-12 08:32:57'
     *  , 'serv': 1
     *  , 'data': [
     *    {
     *      'uni': 1727
     *      , 'gp1': [
     *        48.838402
     *        , 2.273166
     *      ]
     *    },{
     *      'uni': 174          // order to remove coverage
     *    },{
     *      'uni': 1327
     *      , 'gp1': [
     *        48.838402
     *        , 2.273166
     *      ]
     *    }
     *  ]
     * }
     * 
     * Exemple de réponse
     * {
     *  'date': '2019-01-12 08:32:57'
     *  , 'serv': 1
     *  , 'data': [
     *    {
     *      'uni': 1327
     *      , 'cov': [ 2234312,2213432,1223444,4234765,3232434,...]
     *    },{
     *      'uni': 174          // order to remove coverage
     *    },{
     *      'uni': 1523
     *      , 'cov': [ 2234312,2213432,1213144,4234765,3434434,...]
     *    }
     *  ]
     * }
     */
    void custom_consume(RdKafka::Message* message) {
      PrintMemoryUsage();

      std::cout << "**COVERAGE PRODUCER** ";
      // On parse le message
      rapidjson::Document document = parse(message);
      if(document.IsObject() == 0)
        return;


      rapidjson::StringBuffer buffer;
      buffer.Clear();
      rapidjson::Writer<rapidjson::StringBuffer> writer(buffer);
      document.Accept(writer);
      std::cout << "message à traiter: " << buffer.GetString() << std::endl;
  



      //cout_message("Est un objet");
      static const char* kTypeNames[] = 
        { "Null", "False", "True", "Object", "Array", "String", "Number" };

      //printf("Type of serv is %s\n", kTypeNames[document["serv"].GetType()]);

      std::string routes;
      std::string date = document["date"].GetString();

      std::string serv = std::to_string(document["serv"].GetInt());

      // Dynamic threshold from signals (600s target minus mobilization for current hour)
      if (document.HasMember("threshold") && document["threshold"].IsInt()) {
          THRESHOLD = document["threshold"].GetUint();
          std::cout << "Coverage threshold: " << THRESHOLD << "s" << std::endl;
      }
   
      std::string output = "{\"serv\": \"" + serv + "\""; 
      output += ",\"date\": \"" + date + "\"";
      output += ",\"data\": [";
    
      bool is_there_at_least_one_coverage_data_update = false;

      // on essaye de calculer la couverture de chaque unité
      for (rapidjson::Value::ConstValueIterator itr = document["data"].Begin(); itr != document["data"].End(); ++itr) { // Ok

        try {

          // on vérifie qu'une unité est spécifiée
          if (itr -> HasMember("uni")) {
            std::string unit =  rapidjson_element_to_string(( * itr),"uni");

            // si gp1 est renseigné c'est qu'une couverture d'unité doit être calculée
            if (itr -> HasMember("gp1")) {
              //printf("Type of lat is %s and type of lon is %s\n", kTypeNames[( * itr)["gp1"][0].GetType()], kTypeNames[( * itr)["gp1"][1].GetType()]);
              //std::cout << "gp1 est renseigné, lat " << ( * itr)["gp1"][0].GetString() << ", lat " << ( * itr)["gp1"][0].GetType();   
              float lat1 = ( * itr)["gp1"][0].GetDouble();
              float lng1 = ( * itr)["gp1"][1].GetDouble();  
              //cout_message("Lat lon lues");   

              // récupère le noeud à proximité des coordonnées de l'unité
              unsigned source = graph.map_geo_position.find_nearest_neighbor_within_radius(lat1, lng1, 1000).id;

              //cout_message("Noeud à proximité");   


              // Si un noeud valide est trouvé on calcul la couverture
              if(source != RoutingKit::invalid_id){

                // on débute la réponse pour l'unité
                // Use "bld" key for building IDs, "cov" for segment OSM IDs
                std::string coverage_key = graph.building_mapping_loaded ? "bld" : "cov";
                output = output + "{\"uni\":" + unit + ",\"" + coverage_key + "\":[";

                //cout_message("Coordonnées GPS de l'unité: " + std::to_string(lat1) + "," + std::to_string(lng1)); 
                //cout_message("Noeud du graphe routier le plus proche: " + std::to_string(source));

                // std::string unit_coverage_stringify;
                node_bit_vector.reset_all();
                way_bit_vector.reset_all();

                // GPU-accelerated fused coverage: threshold + way marking in one call
                graph.unit_coverage_gpu_fused(node_bit_vector, way_bit_vector, source, THRESHOLD);

                //cout_message("    Fin de calcul de la nouvelle information de couverture");
                /**
                 * Fin du calcul de la nouvelle information de couverture
                 **********/

                // assess for each way if it could be reach under the defined threshold 
                // (a way is covered if both extrimity node can be reach under the defined threshold)		
                                            
                /**********
                 * OPTIMIZED: Mise à jour de l'information de couverture
                 * Uses for_each_set_bit for O(k) instead of O(n) iteration
                 * Also tracks building-level delta changes for aggregated broadcast
                 **/
                if (coverage_for_each_unit.find(unit) == coverage_for_each_unit.end()) {
                    // Unit not found - increment all newly covered ways
                    for_each_set_bit(way_bit_vector, [&](uint64_t i) {
                        coverage_aggregated_for_the_service[i]++;
                        // Track building delta changes
                        if (graph.building_mapping_loaded) {
                            const auto& buildings = graph.get_buildings_for_segment(graph.way_osmid[i]);
                            for (uint64_t bid : buildings) {
                                batch_delta_changes[bid] = coverage_aggregated_for_the_service[i];
                            }
                        }
                    });
                } else {
                    // Unit found - compute delta
                    const auto& prev_coverage = coverage_for_each_unit[unit];

                    // Increment newly covered ways (in new but not in previous)
                    for_each_set_bit(way_bit_vector, [&](uint64_t i) {
                        if (!prev_coverage.is_set(i)) {
                            coverage_aggregated_for_the_service[i]++;
                            // Track building delta changes
                            if (graph.building_mapping_loaded) {
                                const auto& buildings = graph.get_buildings_for_segment(graph.way_osmid[i]);
                                for (uint64_t bid : buildings) {
                                    batch_delta_changes[bid] = coverage_aggregated_for_the_service[i];
                                }
                            }
                        }
                    });

                    // Decrement no longer covered ways (in previous but not in new)
                    for_each_set_bit(prev_coverage, [&](uint64_t i) {
                        if (!way_bit_vector.is_set(i)) {
                            coverage_aggregated_for_the_service[i]--;
                            // Track building delta changes
                            if (graph.building_mapping_loaded) {
                                const auto& buildings = graph.get_buildings_for_segment(graph.way_osmid[i]);
                                for (uint64_t bid : buildings) {
                                    batch_delta_changes[bid] = coverage_aggregated_for_the_service[i];
                                }
                            }
                        }
                    });
                }
                /**
                 * Fin de la mise à jour optimisée
                 **********/

                /**********
                 * OPTIMIZED: Récupération et concaténation des IDs
                 * Uses for_each_set_bit + stringstream for efficiency
                 **/
                std::unordered_set<std::string> unit_coverage_set;
                std::unordered_set<uint64_t> building_ids_set;
                std::stringstream ss;  // Much faster than string concatenation
                bool has_coverage = false;
                bool first_id = true;

                // Iterate only set bits - O(k) instead of O(n)
                for_each_set_bit(way_bit_vector, [&](uint64_t i) {
                    unit_coverage_set.insert(std::to_string(i));

                    if (graph.building_mapping_loaded) {
                        const auto& buildings = graph.get_buildings_for_segment(graph.way_osmid[i]);
                        for (uint64_t building_id : buildings) {
                            building_ids_set.insert(building_id);
                        }
                    } else {
                        if (!first_id) ss << ",";
                        ss << "\"" << graph.way_osmid[i] << "\"";
                        first_id = false;
                    }
                    has_coverage = true;
                });

                // OPTIMIZED: Build output using stringstream
                if (graph.building_mapping_loaded && !building_ids_set.empty()) {
                    // Use stringstream for building IDs
                    std::stringstream bss;
                    bool first_bld = true;
                    for (uint64_t building_id : building_ids_set) {
                        if (!first_bld) bss << ",";
                        bss << "\"" << building_id << "\"";
                        first_bld = false;
                    }
                    output += bss.str() + "]},";
                } else if (!graph.building_mapping_loaded && has_coverage) {
                    // Road mode - append stringstream content
                    output += ss.str() + "]},";
                } else {
                    output += "]},";
                }

                // On supprime la dernière "," de trop
                // unit_coverage_stringify = unit_coverage_stringify.substr(0, unit_coverage_stringify.size()-1);

                /**
                 * Fin de récupération et concaténation des ID OSM des ways couverts par l'unité
                 **********/

                //DEBUG Check nodes_previously_covered_by_the_unit
                //std::cout << "    Aperçu des ID OSM des ways couverts par l'unité: ";
                int i = 0;
                for (auto elem : unit_coverage_set) {
                    i++;
                    std::cout << elem ;
                    if(i == 10)
                        break;
                    std::cout << ",";
                }
                //std::cout << "... Key: " << serv + ":" + unit + ":coverage " << " Size: " << unit_coverage_set.size() << std::endl;
                // Fin de heck nodes_previously_covered_by_the_unit

                // Record the computed unit coverage on Redis
                // cout_message(" 4. Record the computed unit coverage on Redis");
                const sw::redis::StringView redis_key_sv = serv + ":" + unit + ":coverage";

                if(unit_coverage_set.size() != 0)
                  redis.sadd(redis_key_sv, unit_coverage_set.begin(), unit_coverage_set.end());
                else 
                  redis.sadd(redis_key_sv, {});
                // cout_message("    Fin de record the computed unit coverage on Redis");

                // Finalisation du message de l'unité à publier
                // output += ",\"coverage\":[" + unit_coverage_stringify + "]";

                is_there_at_least_one_coverage_data_update = true;     

                // Sauvegarde de la nouvelle information de couverture pour l'unité
                coverage_for_each_unit[unit] = way_bit_vector;
        

              } else {  // FIN de if(source != RoutingKit::invalid_id)
                std::cout << "No node within 1000m from source position" << std::endl;
                output = output + "{\"uni\":" + unit + "},";
                is_there_at_least_one_coverage_data_update = true;  
              }

            } else {  // FIN if (!itr -> HasMember("gp1")) 
          
              //const sw::redis::StringView redis_key_sv = serv + ":" + unit + ":coverage";
              redis.del({serv + ":" + unit + ":coverage"});

              // cout_message(" 1. Suppression de l'information de couverture de ");
              // auto val = redis.get(serv + ":" + unit + ":coverage");
              // if(val) {

              //   cout_message(serv + ":" + unit + ":coverage");
              //   std::unordered_set<std::string> nodes_previously_covered_by_the_unit;

              //   redis.smembers(serv + ":" + unit + ":coverage", std::inserter(nodes_previously_covered_by_the_unit, nodes_previously_covered_by_the_unit.begin()));
                
              //   //DEBUG 
              //   std::cout << "Précédente données stockées: ";
              //   int i = 0;
              //   for (auto elem : nodes_previously_covered_by_the_unit) {
              //     i++;
              //     std::cout << elem << ",";
              //     if(i == 10)
              //         break;
              //   }
              //   std::cout << std::endl;
              //   // Fin de heck nodes_previously_covered_by_the_unit

              //   for (auto elem : nodes_previously_covered_by_the_unit) {
              //       coverage_aggregated_for_the_service[stoi(elem)]--;
              //   }
              //   redis.hset(serv + ":" + unit,":coverage", "");
              
              //   is_there_at_least_one_coverage_data_update = true;     
              // }
              is_there_at_least_one_coverage_data_update = true;     
              output = output + "{\"uni\":" + unit + "},";
              //cout_message("    Fin de suppression de l'information de couverture de ");

            };  // FIN de else (!itr -> HasMember("gp1")) 

          }
        } catch(std::exception&err) {

          std::cerr << "Stopped on exception : " << err.what() << std::endl;


        }
      } // END For loop over units

      if (output.back() == ',')
        output = output.substr(0, output.size()-1);

      output = output + "]";  // Close the data array

      // Always add aggregated delta changes for Deck.gl fast path
      // Even empty agg triggers fast path (avoids expensive frontend rebuild)
      if (graph.building_mapping_loaded) {
        output += ",\"agg\":{";
        bool first_agg = true;
        for (const auto& [bid, count] : batch_delta_changes) {
          if (!first_agg) output += ",";
          output += "\"" + std::to_string(bid) + "\":" + std::to_string(count);
          first_agg = false;

          // Update persistent snapshot
          if (count <= 0) {
            building_coverage_snapshot.erase(bid);
          } else {
            building_coverage_snapshot[bid] = count;
          }
        }
        output += "}";
        batch_delta_changes.clear();

        // Store snapshot to Redis for API access (every 10 updates to reduce writes)
        static int update_counter = 0;
        if (++update_counter >= 10) {
          update_counter = 0;
          std::string snapshot_json = "{";
          bool first_snap = true;
          for (const auto& [bid, count] : building_coverage_snapshot) {
            if (!first_snap) snapshot_json += ",";
            snapshot_json += "\"" + std::to_string(bid) + "\":" + std::to_string(count);
            first_snap = false;
          }
          snapshot_json += "}";
          redis.set("coverage:snapshot:" + service_name, snapshot_json);
        }
      }

      output = output + "}";  // Close the main object

      std::cout << "Message à publier sur kafka" << output << std::endl;

      if (is_there_at_least_one_coverage_data_update == true)
        producer.kafka_message_builder(output);

    } // END custom_consume method
};

/*
bool kafka_message_consumer(const char * message,cms::GraphCH &graph) {

  std::cout<< message << std::endl;

  rapidjson::Document document;
  // Est-ce ,écessaire ?
  document.SetFloat(0.09f); 
  document.Parse(message);

  std::string date = document["date"].GetString();
  for (rapidjson::Value::ConstValueIterator itr = document["data"].Begin(); itr != document["data"].End(); ++itr) { // Ok

    if (itr->HasMember("unit")) { // Ok
      int unit = (*itr)["unit"].GetInt();
      double lat1 = (*itr)["gp1"][0].GetDouble();
      float lng1 = (*itr)["gp1"][1].GetFloat();
      float lat2 = (*itr)["gp2"][0].GetFloat();
      float lng2 = (*itr)["gp2"][1].GetFloat();
      try {
        std::cout << graph.get_route_lat_lon_nodes(lat1,lng1,lat2,lng2) << std::endl;
      }catch(std::exception&err){
        std::cerr << "Unable to calculate route with source: [" << lat1 << "," << lng1 << "] and target: [" << lat1 << "," << lat2 << "]" << std::endl;
      }
            // std::cout.precision(9);
      // std::cout << unit << "," << lat1 << "," << lng1 << "," << lat2 << "," << lng2 << std::endl;
      // printf("%.9g %.9g %.9g %.9g\n", lat1, lng1, lat2, lng2);

    }
  }

  //kafka_message_producer(message);


  std::vector<float> splitted_message;

  // string_to_coordinates_vector(message, splitted_message);
  // if(splitted_message.size() != 0) {
  //   std::cout << "Process (lat1 lon1 lat2 lon2): " ;
  //   for (std::vector<float>::const_iterator i = splitted_message.begin(); i != splitted_message.end(); ++i)
  //     std::cout << *i << ' ';
  //   std::cout << std::endl;
  // 	std::cout << graph.get_route_lat_lon_nodes(splitted_message[0],splitted_message[1],splitted_message[2],splitted_message[3]) << std::endl;
  //   return(true);
  // }


  return(true);
}
*/

void fonction_deux()
{
    std::cout << "fonction_deux()" << std::endl;
    sleep(1);
    std::cout << "fonction_deux()" << std::endl;
    sleep(1);
    std::cout << "fonction_deux()" << std::endl;
    sleep(1);
    std::cout << "fonction_deux()" << std::endl;
}


int main(int argc, char*argv[])
{
    // Service prefix from env var or CLI arg, default "paris"
    std::string service = "paris";
    if (const char* env = std::getenv("CMS_SERVICE")) service = env;
    if (argc > 1) service = argv[1];

    std::string kafka_topic_route_request = service + "_route_request";
    std::string kafka_topic_route_response = service + "_route_response";
    std::string kafka_topic_coverage_request = service + "_coverage_request";
    std::string kafka_topic_coverage_response = service + "_coverage_response";
    std::string brokers = "localhost:9092";

    // Graph data path from env var, default "./data/backup/paris"
    std::string graph_path = "./data/backup/paris";
    if (const char* env = std::getenv("CMS_GRAPH_PATH")) graph_path = env;
    if (argc > 2) graph_path = argv[2];

    std::cout << "[stream_geo_worker] service=" << service << " graph=" << graph_path << std::endl;

    /**
     * Build a graph instance
     */
    cms::GraphCH graph;
    get_graph(graph, graph_path);
    sw::redis::Redis redis = sw::redis::Redis("tcp://127.0.0.1:6379");



    try{

        // Route service
        KafkaMessageProducer route_response_producer(brokers, kafka_topic_route_response);
        KafkaConsumerToRoutePlannerProducer route_request_consumer(brokers, kafka_topic_route_request, route_response_producer, graph);
        
        // Coverage service
        KafkaMessageProducer coverage_response_producer(brokers, kafka_topic_coverage_response);
        KafkaConsumerToCoverageProducer coverage_request_consumer(brokers, kafka_topic_coverage_request, coverage_response_producer, graph, redis, service);

        // Constructs new threads and runs them. 
        // Does not block execution.
        std::thread route_service(&KafkaConsumerToRoutePlannerProducer::listen, // the pointer-to-member
                            route_request_consumer,      // the object, could also be a pointer
                            1000); 
        std::thread coverage_service(&KafkaConsumerToCoverageProducer::listen, // the pointer-to-member
                            coverage_request_consumer,      // the object, could also be a pointer
                            1000); 
        //std::thread coverage_service(fonction_deux);

        // Do other things...

        // Makes the main thread wait for the new thread to finish execution, therefore blocks its own execution.
        route_service.join();
        coverage_service.join();

        std::cout << "Message exécuté suite à l'arrêt des thread" << std::endl;


        //kafka_messages_listener(brokers, kafka_topic_route_request, 1000, consumer);
        
        //kafka_messages_listener(brokers, kafka_topic, 1000, kafka_message_consumer, graph);
            //graph.get_route_lat_lon_nodes(48.884113,2.289324,48.8669931,2.3545479);

        //48.8824867,2.2882517
	} catch(std::exception&err) {

		std::cerr << "Stopped on exception : " << err.what() << std::endl;
		return 1;

	}

	return 0;
}


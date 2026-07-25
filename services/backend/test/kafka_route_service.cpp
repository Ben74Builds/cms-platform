/**
 * This script load a road graph from an OpenStreetMap PBF file,
 * save its properties and the contracted form for later reuse
 *
 * COMPILE AND EXECUTE
 * Kafka et Zookeeper doivent être démarrés
 * # Compile:
 * g++ -Ilib/RoutingKit/include -Llib/RoutingKit/lib -std=c++11 ./test/print_route.cpp -o ./bin/print_route -lroutingkit -lprotobuf-lite -losmpbf -lz -lboost_serialization  -lrdkafka++
 * 
 * # Launch the generated executable
 * ./bin/print_route
 * 
 * # Tester lançant dans un autre terminal une console d'envoi de messages Kafka
 * ~/Kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topiayaa
 * 
 * # Transmettre un message conforme
 * 48.884113,2.289324,48.8669931,2.3545479
 */
#include "rapidjson/document.h"
#include "../src/graph.cpp"
#include "../src/kafka.cpp"


/**
 * Build the graph object
 */
void get_graph(cms::GraphCH &graph){

  std::string path_to_data_files = "./data/backup/paris";

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

  cout_message("*** Loading completed ***");
       
}



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
      double lat1 = (*itr)["pos1"][0].GetDouble();
      float lng1 = (*itr)["pos1"][1].GetFloat();
      float lat2 = (*itr)["pos2"][0].GetFloat();
      float lng2 = (*itr)["pos2"][1].GetFloat();
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

int main(int argc, char*argv[])
{

    std::string kafka_topic_request = "paris_route_request";
    std::string kafka_topic_response = "paris_route_response";
    std::string brokers = "localhost:9092";

    /**
     * Build a graph instance
     */
    cms::GraphCH graph;
    get_graph(graph);


	try{

    KafkaMessageProducer producer(brokers, kafka_topic_response);
    KafkaConsumer consumer(brokers, kafka_topic_request, producer, graph);
  	kafka_messages_listener(brokers, kafka_topic_request, 1000, consumer);
  	//kafka_messages_listener(brokers, kafka_topic, 1000, kafka_message_consumer, graph);
		//graph.get_route_lat_lon_nodes(48.884113,2.289324,48.8669931,2.3545479);

    //48.8824867,2.2882517
	} catch(std::exception&err) {

		std::cerr << "Stopped on exception : " << err.what() << std::endl;
		return 1;

	}

	return 0;
}


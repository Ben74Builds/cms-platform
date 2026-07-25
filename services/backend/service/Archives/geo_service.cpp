/**
 * This script load a road graph from an OpenStreetMap PBF file,
 * save its properties and the contracted form for later reuse
 *
 * COMPILE AND EXECUTE
 * Kafka et Zookeeper doivent être démarrés
 * # Compile:
 * g++ -Ilib/RoutingKit/include -Llib/RoutingKit/lib -std=c++11 ./service/geo_service.cpp -o ./bin/geo_service -lroutingkit -lprotobuf-lite -losmpbf -lz -lboost_serialization  -lrdkafka++
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
#include <thread> 
#include "rapidjson/document.h"
#include "../src/graph/graph.h"
#include "../src/graph/kafka.h"


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

class CustomKafkaConsumer : public KafkaConsumer
{
  KafkaMessageProducer &producer;
  cms::GraphCH &graph;  
  public:  
    using KafkaConsumer::KafkaConsumer;
    CustomKafkaConsumer(
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

          rapidjson::Document document = parse(message);
          if(document.IsObject() == 0)
            return;

          std::string routes;
          std::string date = document["date"].GetString();

          // try to get a route for each unit
          // otherwise send back po1 and pos2 lon and lat
          for (rapidjson::Value::ConstValueIterator itr = document["data"].Begin(); itr != document["data"].End(); ++itr) { // Ok

            if (itr -> HasMember("unit")) { // Ok
              int unit = ( * itr)["unit"].GetInt();
              float lat1 = ( * itr)["pos1"][0].GetFloat();
              float lng1 = ( * itr)["pos1"][1].GetFloat();
              float lat2 = ( * itr)["pos2"][0].GetFloat();
              float lng2 = ( * itr)["pos2"][1].GetFloat();

              bool do_we_have_a_route = false;
              routes = routes + "{\"unit\":" + std::to_string(unit) + ",";
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
                routes = routes + "\"pos1\":[" + std::to_string(lat1) + "," + std::to_string(lng1) + "],\"pos2\":[" + std::to_string(lat2) + "," + std::to_string(lng2) + "]},";

            }
          }

          // Remove the extra ","
          routes.pop_back();
          std::cout << "Response: " << "{\"date\":\"" + date + "\",\"routes\":[" + routes + "]}" << std::endl;
          // Send the message through Kafka
          producer.kafka_message_builder("{\"date\":\"" + date + "\",\"routes\":[" + routes + "]}");
    }
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

    std::string kafka_topic_route_request = "paris_route_request";
    std::string kafka_topic_route_response = "paris_route_response";
    std::string brokers = "localhost:9092";

    /**
     * Build a graph instance
     */
    cms::GraphCH graph;
    get_graph(graph);


	try{

    KafkaMessageProducer producer(brokers, kafka_topic_route_response);
    CustomKafkaConsumer consumer(brokers, kafka_topic_route_request, producer, graph);

    // Constructs new threads and runs them. 
    // Does not block execution.
    std::thread route_service(&CustomKafkaConsumer::listen, // the pointer-to-member
                         consumer,      // the object, could also be a pointer
                         1000); 
    std::thread coverage_service(fonction_deux);

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


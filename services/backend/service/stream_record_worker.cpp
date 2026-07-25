/****************************************************************
This script records the states in PostgreSQL and maintain the current ones in Redis
This script expect to receive messages on a Kafka topic structured as:

{
  serv: <service>       required
  ,date: <datetime>     required
  ,data: [
    {
      uni: [            required
          <unit id>                     not null
          ,<unit category>              null
          ,<unit's parking station>     null
        ]
      ,sta: [            optional   
          <status id>
          ,<is free>
        ]
      ,gp1: [            optional   
          <current latitude>
          ,<current longitude>
        ]
      ,gp2: [            optional
          <destination's latitude>
          ,<destination's longitude>
        ]
      ,int: [            optional
          <intervention>
          ,<intervention category>
        ]
    },{
      uni: [<unit id>,<unit category>,<unit's parking station>]
      ,sta: [<status id>,<is free>]
      ,gp1: [<current latitude>,<current longitude>]
      ,gp2: [<destination's latitude>,<destination's longitude>]
      ,int: [<intervention>,<intervention category>]
    },
    ...
  ]
}

COMPILE AND EXECUTE
Kafka et Zookeeper doivent être démarrés
# Compile:
g++ -Ilib/RoutingKit/include -Llib/RoutingKit/lib -std=c++17 ./service/stream_record_worker.cpp -o ./bin/stream_record_worker -lroutingkit -lprotobuf-lite -losmpbf -lz -lboost_serialization  -lrdkafka++ -lpthread -lredis++

# Launch the generated executable
./bin/stream_record_worker

# Tester en lançant un Kafka producer dans un autre terminal
~/Kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic paris_gps_status
 
****************************************************************/
#include <thread> 
#include <sw/redis++/redis++.h>
#include "rapidjson/document.h"
#include "rapidjson/writer.h"
#include "rapidjson/stringbuffer.h"
#include "../src/kafka.cpp"
#include "../src/utils.cpp"

// Load configuration 
std::map<std::string, std::string> config = load_config_variables_from_file("config.txt");


class RecorderKafkaConsumer : public KafkaConsumer
{
  sw::redis::Redis &redis;
  public:  
    using KafkaConsumer::KafkaConsumer;
    RecorderKafkaConsumer(
      std::string brokers_
      , std::string kafka_topic_
      , sw::redis::Redis &redis_
    ):
      KafkaConsumer(brokers_,kafka_topic_)
      , redis(redis_)
    {};

    void custom_consume(RdKafka::Message* message) {

        std::string database_insert_query = "";
        /*****
         * START checking headers mandatory arguments
         **/
        rapidjson::Document document = parse(message);
        // Check if the message is an object
        if(document.IsObject() == 0) {
            std::cout << "The received message is not an object: ";
            print_rapidjson_document(document);
            return;
        }

        // Check if possess 'date' and 'service' arguments otherwise exit
        if (!document.HasMember("date")
            || !document.HasMember("serv") 
            || document["date"].IsNull() 
            || document["serv"].IsNull()
        )
            return;

        // Store in 'date' and 'service' variables
        std::string date = document["date"].GetString();
        int service = document["serv"].GetInt();
        //std::cout << "Date: " << date << " | " << "Service: " << service << std::endl;
        /**
         * END checking headers mandatory arguments
         *****/

        /*****
         * START updating states in Redis  
         **/
        for (rapidjson::Value::ConstValueIterator itr = document["data"].Begin(); itr != document["data"].End(); ++itr) { 

            std::string unit_id;

            // Check if a unit_id is specified otherwise exit
            if(!itr -> HasMember("uni") || ( * itr)["uni"].IsNull() || !( * itr)["uni"].IsArray() || ( * itr)["uni"][0].IsNull()) {
                std::cout << "No unit id specified" << std::endl;
                break;
            } else
                unit_id = rapidjson_element_to_string(( * itr)["uni"][0]);

            /*****
             * START properties updates
             **/
        
            int unit_category_id, unit_parking_station_id;
            int status_id; bool is_free;
            float current_lat, current_lon;
            float destination_lat, destination_lon;   
            int intervention_id, intervention_category;     

            // Define the Redis key
            std::string base_key = std::to_string(service) + ":" + unit_id;

            if (itr -> HasMember("sta") && !( * itr)["sta"].IsNull() && !( * itr)["sta"][0].IsNull())
                    status_id = ( * itr)["sta"][0].GetInt();

            if (itr -> HasMember("gp1") && !( * itr)["gp1"].IsNull() && !( * itr)["gp1"][0].IsNull() && !( * itr)["gp1"][1].IsNull()) {
                current_lat = ( * itr)["gp1"][0].GetFloat();
                current_lon = ( * itr)["gp1"][1].GetFloat();
            }

            if (itr -> HasMember("gp2") && !( * itr)["gp2"].IsNull() && !( * itr)["gp2"][0].IsNull() && !( * itr)["gp2"][1].IsNull()) {
                destination_lat = ( * itr)["gp2"][0].GetFloat();
                destination_lon = ( * itr)["gp2"][1].GetFloat();
            }

            /*****
             * START a checking to process data only in case of a status or position update
             **/
            bool must_be_recorded = false;
            if (config["WAIT_STATUS_OR_POSITION_UPDATE"] == "true") {
                if (status_id && current_lat && current_lon && destination_lat && destination_lon){      
                    auto val = redis.get(base_key);    // val is of type OptionalString. See 'API Reference' section for details.
                    if (val) { // key exist
                        // Publish if for the given key one information need an update
                        // status or position
                        if (
                            ((!status_id) && std::stoi(redis.get(base_key+":status").value()) != status_id)
                            or ((!current_lat) && current_lat != std::stof(redis.get(base_key+":lat").value())) // round() is trying to limit some little variations
                            or ((!current_lon) && current_lon != std::stof(redis.get(base_key+":lon").value()))
                        )
                        must_be_recorded = true;  
                    }else{
                        must_be_recorded = true;
                    }
                }
            } else {
                must_be_recorded = true;
            }
      
            if(must_be_recorded){

                database_insert_query += "('" + date + "'," + std::to_string(service) + ",'" + unit_id + "',";

                // Start recording on Redis
                redis.set(base_key+":date",date);

                /*****
                 * uni
                 **/   
                // <unit category>              
                if( ( * itr)["uni"].Size() > 1 && !( * itr)["uni"][1].IsNull()) {
                    redis.set(
                        base_key+":unit_category_id"
                        ,std::to_string(( * itr)["uni"][1].GetInt())
                    );
                    database_insert_query += std::to_string(( * itr)["uni"][1].GetInt()) + ",";
                } else 
                    database_insert_query += "null,"; 
                // <unit's parking station>
                if( ( * itr)["uni"].Size() > 2 && !( * itr)["uni"][2].IsNull() ) {
                    redis.set(
                        base_key+":unit_parking_station_id"
                        ,std::to_string(( * itr)["uni"][2].GetInt())
                    );
                    database_insert_query += std::to_string(( * itr)["uni"][2].GetInt()) + ",";
                } else 
                    database_insert_query += "null,"; 

                /*****
                 * sta
                 **/  
                if( itr -> HasMember("sta") && !( * itr)["sta"].IsNull()) {
                    // <status id>
                    if( !( * itr)["sta"][0].IsNull() ) {
                        redis.set(
                            base_key+":status_id"
                            ,std::to_string(( * itr)["sta"][0].GetInt())
                        );
                        database_insert_query += std::to_string(( * itr)["sta"][0].GetInt()) + ",";
                    } else 
                        database_insert_query += "null,"; 

                    // <is free>
                    if( !( * itr)["sta"][1].IsNull() ) {
                        redis.set(
                            base_key+":is_free"
                            ,std::to_string(( * itr)["sta"][1].GetInt())
                        );
                        database_insert_query += std::to_string(( * itr)["sta"][1].GetInt()) + ",";
                    } else 
                        database_insert_query += "null,"; 
                } else 
                    database_insert_query += "null,null,"; 

                /*****
                 * gp1
                 **/  
                if( itr -> HasMember("gp1") && !( * itr)["gp1"].IsNull() && !( * itr)["gp1"][0].IsNull() && !( * itr)["gp1"][1].IsNull()) {
                    redis.set(base_key+":lat",std::to_string(( * itr)["gp1"][0].GetFloat()));
                    redis.set(base_key+":lon",std::to_string(( * itr)["gp1"][1].GetFloat()));
                    database_insert_query += std::to_string(( * itr)["gp1"][0].GetFloat()) + ",";
                    database_insert_query += std::to_string(( * itr)["gp1"][1].GetFloat()) + ",";
                } else 
                    database_insert_query += "null,null,"; 
                
                /*****
                 * gp2
                 **/  
                if( itr -> HasMember("gp2") && !( * itr)["gp2"].IsNull() && !( * itr)["gp2"][0].IsNull() && !( * itr)["gp2"][1].IsNull()) {
                    //
                    database_insert_query += std::to_string(( * itr)["gp2"][0].GetFloat()) + ",";
                    database_insert_query += std::to_string(( * itr)["gp2"][1].GetFloat()) + ",";
                } else 
                    database_insert_query += "null,null,"; 

                /*****
                 * int
                 **/  
                if( itr -> HasMember("int") && !( * itr)["int"].IsNull()) {
                    // <status id>
                    if( !( * itr)["int"][0].IsNull() ) {
                        redis.set(
                            base_key+":intervention_id"
                            ,std::to_string(( * itr)["int"][0].GetInt())
                        );
                        database_insert_query += std::to_string(( * itr)["int"][0].GetInt()) + ",";
                    } else 
                        database_insert_query += "null,"; 
                    // <is free>
                    if( !( * itr)["int"][1].IsNull() ) {
                        redis.set(
                            base_key+":intervention_category"
                            ,std::to_string(( * itr)["int"][1].GetInt())
                        );
                        database_insert_query += std::to_string(( * itr)["int"][1].GetInt()) + ",";
                    } else 
                        database_insert_query += "null,"; 
                } else 
                    database_insert_query += "null,null,";       


                /*****
                 * obj
                 **/  
                // if( itr -> HasMember("obj") && !( * itr)["obj"].IsNull()) {
                //     // <status id>
                //     if( !( * itr)["obj"].IsNull() ) {                      
                //         redis.set(
                //             base_key+":intervention_id"
                //             ,( * itr)["obj"].GetString()
                //         );
                //         database_insert_query += (std::string)( * itr)["obj"].GetString() + "),";
                //     } else 
                //         database_insert_query += "null),"; 
                // } else 
                    database_insert_query += "null),"; 
                // End recording on Redis


    
            }
        }

        if(database_insert_query.length() <= 1)
            return;

        database_insert_query = database_insert_query.substr(0, database_insert_query.size()-1);

        database_insert_query = "INSERT INTO public.main_stream ( \
            datetime \
            , service \
            , unit \
            , unit_category \
            , unit_parking_station \
            , status \
            , is_free \
            , current_latitude \
            , current_longitude \
            , destination_latitude \
            , destination_longitude \
            , intervention \
            , intervention_category \
            , object \
        ) \
        VALUES " + database_insert_query;

        std::string connection = "user=postgres password=qdgjl13579! \
        host=127.0.0.1 port=5432  dbname=data_receiver";

        query_on_postgresql(connection,database_insert_query);

    }
};


int main(int argc, char*argv[])
{
    std::map<std::string, std::string> config = load_config_variables_from_file("../config.txt");

    sw::redis::Redis redis = sw::redis::Redis("tcp://127.0.0.1:6379");

    // Service prefix from env var or CLI arg, default "paris"
    std::string service = "paris";
    if (const char* env = std::getenv("CMS_SERVICE")) service = env;
    if (argc > 1) service = argv[1];

    std::string kafka_topic_main_stream = service + "_gps_status";
    std::string brokers = "localhost:9092";

    std::cout << "[stream_record_worker] service=" << service << " topic=" << kafka_topic_main_stream << std::endl;

	try{

    RecorderKafkaConsumer consumer(brokers, kafka_topic_main_stream, redis);

    // Constructs new threads and runs them. 
    // Does not block execution.
    std::thread record_service(&RecorderKafkaConsumer::listen, // the pointer-to-member
                         consumer,      // the object, could also be a pointer
                         1000); 


    // Do other things...

    // Makes the main thread wait for the new thread to finish execution, therefore blocks its own execution.
    record_service.join();

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


/**
 * This script load a road graph from an OpenStreetMap PBF file,
 * save its properties and the contracted form for later reuse
 *
 * COMPILE AND EXECUTE
 * Kafka et Zookeeper doivent être démarrés
 * # Compile:
 * g++ -Ilib/RoutingKit/include -Llib/RoutingKit/lib -std=c++11 ./service/record_service.cpp -o ./bin/record_service -lroutingkit -lprotobuf-lite -losmpbf -lz -lboost_serialization  -lrdkafka++ -lpthread
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
#include <sw/redis++/redis++.h>
#include "rapidjson/document.h"
#include "rapidjson/writer.h"
#include "rapidjson/stringbuffer.h"
#include "../src/graph/kafka.h"



class CustomKafkaConsumer : public KafkaConsumer
{
  sw::redis::Redis &redis;
  public:  
    using KafkaConsumer::KafkaConsumer;
    CustomKafkaConsumer(
      std::string brokers_
      , std::string kafka_topic_
      , sw::redis::Redis &redis_
    ):
      KafkaConsumer(brokers_,kafka_topic_)
      , redis(redis_)
    {};


    void custom_consume(RdKafka::Message* message) {

        rapidjson::Document document = parse(message);
        if(document.IsObject() == 0)
            return;
        // 3. Stringify the DOM
        rapidjson::StringBuffer buffer;
        rapidjson::Writer<rapidjson::StringBuffer> writer(buffer);
        document.Accept(writer);
    
        // Output {"project":"rapidjson","stars":11}
        std::cout << buffer.GetString() << std::endl;

        //{"date":"2019-01-01T00:02:24","service":"paris","data":[{"unit":3834,"cat":2,"station":256,"free":0,"status":102,"gp1":[48.8373818,2.3437573],"gp2":null}]}
        // date 
        // service
        // unit
        // cat
        // station
        // free
        // status

        // Record to redis


            if (document["date"].IsNull() || document["service"].IsNull())
                return;

            std::string date = document["date"].GetString();
            std::string service = document["service"].GetString();

  
            // Set the message in Redis
            //msg_to_publish = ""          
            for (rapidjson::Value::ConstValueIterator itr = document["data"].Begin(); itr != document["data"].End(); ++itr) { // Ok
                int cat, station, status;
                bool free;
                float lat1, lon1, lat2, lon2;     

                if(( * itr)["unit"].IsNull())
                    break;
                std::string base_key = service + ":" + std::to_string(( * itr)["unit"].GetInt());

                if( !( * itr)["status"].IsNull() )
                    status = ( * itr)["status"].GetInt();

                if( !( * itr)["gp1"].IsNull() ) {
                    lat1 = ( * itr)["gp1"][0].GetFloat();
                    lon1 = ( * itr)["gp1"][1].GetFloat();
                }
                if( !( * itr)["gp2"].IsNull() ) {
                    lat2 = ( * itr)["gp2"][0].GetFloat();
                    lon2 = ( * itr)["gp2"][1].GetFloat();
                }

                //std::cout << base_key << " GetString(\"gp1\") " << ( * itr)["gp1"].GetString() << std::endl;
                //std::cout << base_key << " GetString(\"gp2\") " << ( * itr)["gp2"].GetString() << std::endl;

                bool must_be_recorded = false;
                auto val = redis.get(base_key);    // val is of type OptionalString. See 'API Reference' section for details.
                if (val) { // key exist
                    // Publish if for the given key one information need an update
                    // status or position
                    if (
                        ((!status) && std::stoi(redis.get(base_key+":status").value()) != status)
                        or ((!lat1) && lat1 != std::stof(redis.get(base_key+":lat").value())) // round() is trying to limit some little variations
                        or ((!lon1) && lon1 != std::stof(redis.get(base_key+":lon").value()))
                    )
                    must_be_recorded = true;  
                }else{
                    must_be_recorded = true;
                }

                if(must_be_recorded){

                    
                    // Start recording on Redis
                    redis.set(base_key+":date",date);

                    if( !( * itr)["cat"].IsNull() )
                        redis.set(
                            base_key+":cat"
                            ,std::to_string(( * itr)["cat"].GetInt())
                        );
                    if( !( * itr)["station"].IsNull() )
                        redis.set(
                            base_key+":station"
                            ,std::to_string(( * itr)["station"].GetInt())
                        );
                    if( !( * itr)["free"].IsNull() )
                        redis.set(
                            base_key+":free"
                            ,std::to_string(( * itr)["free"].GetInt())
                        );
                    if( !( * itr)["status"].IsNull() )
                        redis.set(
                            base_key+":status"
                            ,std::to_string(( * itr)["status"].GetInt())
                        );

                    if( !( * itr)["gp1"].IsNull() ) {
                        redis.set(base_key+":lat",std::to_string(lat1));
                        redis.set(base_key+":lon",std::to_string(lon1));
                    }
                    // End recording on Redis


                    // Start recording in PostgreSQL
                    // CHACK THAT: https://www.tutorialspoint.com/postgresql/postgresql_c_cpp.htm

                    // End recording on PostgreSQL
       
                }
            }
        //             // cat
        //         if (itr -> HasMember("cat"))
        //             redis.set(base_key+":cat", ( * itr)["cat"].GetString());
        //         if (itr -> HasMember("station"))
        //             redis.set(base_key+":station", ( * itr)["station"].GetString());
        //         if (itr -> HasMember("free"))
        //             redis.set(base_key+":free", ( * itr)["free"].GetString());
        //         if (itr -> HasMember("status"))
        //             redis.set(base_key+":status", ( * itr)["status"].GetString());
        //         if (itr -> HasMember("lat1"))
        //             redis.set(base_key+":lat1", ( * itr)["lat1"].GetString());
        //         if (itr -> HasMember("lon1"))
        //             redis.set(base_key+":lon1", ( * itr)["lon1"].GetString());
        //         if (itr -> HasMember("lat2"))
        //             redis.set(base_key+":lat2", ( * itr)["lat2"].GetString());
        //         if (itr -> HasMember("lon2"))
        //             redis.set(base_key+":lon2", ( * itr)["lon2"].GetString());
                
  
        //     }    
            
        //     for data in msg_dict['data']:

        //         str_unit = str(data['unit'])
        //         redis_key = service+":mma:"+str_unit

        //         must_be_recorded = False
        //         ##################################
        //         # Check if the information is new (= must be published)
        //         # meaning worth to be publish
        //         if r.exists(redis_key):
        //         # The key exists
        //             # Publish if for the given key one information need an update
        //             # status or position
        //             if (
        //                 (data['status'] is not None and r.hget(redis_key, "status") != data['status'])
        //                 or (data['gp1'][0] is not None and round(float(r.hget(redis_key, "lat")),4) != round(float(data['gp1'][0]), 4)) # round() is trying to limit some little variations
        //                 or (data['gp1'][1] is not None and round(float(r.hget(redis_key, "lng")),4) != round(float(data['gp1'][1]), 4))
        //             ):
        //                 must_be_recorded = True
        //         else:
        //         # The key is new
        //             must_be_recorded = True
        //         # Information checked if new
        //         ##################################

        //         a_message_must_be_recorded = a_message_must_be_recorded or must_be_recorded


        //         if must_be_recorded:
                    
        //             # Will be 

        //             r.hset(redis_key, "date", date)

        //             if data['cat'] is not None:
        //                 r.hset(redis_key, "cat", data['cat'])
        //             else:
        //                 data['cat'] = r.hget(redis_key, "cat")

        //             if data['station'] is not None:
        //                 r.hset(redis_key, "station", data['station'])
        //             else:
        //                 data['station'] = r.hget(redis_key, "station")

        //             if data['status'] is not None:
        //                 r.hset(redis_key, "status", data['status'])
        //             else:
        //                 data['status'] = r.hget(redis_key, "status")

        //             if data['gp1'][0] is not None:
        //                 r.hset(redis_key, "lat", data['gp1'][0])
        //             else:
        //                 data['gp1'][0] = r.hget(redis_key, "lat")

        //             if data['gp1'][1] is not None:
        //                 r.hset(redis_key, "lng", data['gp1'][1])
        //             else:
        //                 data['gp1'][1] = r.hget(redis_key, "lng")

        //             if data['free'] is not None:
        //                 r.hset(redis_key, "free", data['free'])
        //             else:
        //                 data['free'] = r.hget(redis_key, "free")


        //             if data['free'] != 1:
        //                 r.set(redis_key+":coverage", "")

        //             # Do we need recompute the service coverage? 
        //             recompute_service_coverage = (data['free'] == 1 or (r.hget(redis_key, "free") == 1 and data['free'] != 1))
        //             # Publish the new information

                           
        //             msg_to_publish += str_unit+';'+str(data['cat'])+';'+str(data['station'])+';'+str(data['status'])+';'+str(data['gp1'][0])+';'+str(data['gp1'][1])+';'+str(data['free'])+';'+str(int(recompute_service_coverage))              

        //             # Retrieve stored information from Redis
        //             if config.PRINT_MESSAGES == True:
        //                 if config.PRINT_MESSAGES_FULL == True:
        //                     print('Finally a new record: ', msg_to_publish) 
        //                 else:
        //                     print('Finally a new record for: ', str_unit) 
        //         else:

        //             if config.PRINT_MESSAGES == True:
        //                 if config.PRINT_MESSAGES_FULL == True:
        //                     print('Already recorded: ' \
        //                         , str_unit, ';', data['color'], ';',data['gp1'][0],';',data['gp1'][1], ' '
        //                         , r.hget(redis_key, "status"), ';', r.hget(redis_key, "lat"), ';', r.hget(redis_key, "lng"), ' '
        //                         , round(abs(float(data['gp1'][1]) - float(r.hget(redis_key, "lng"))),5), ' '
        //                         , round(abs(float(data['gp1'][0]) - float(r.hget(redis_key, "lat"))),5), ' '
        //                     )
        //                 print('Information already stored for: ', str_unit) 

        //     if a_message_must_be_recorded == True:
        //         r.publish(
        //             config.REDIS_CHANNEL, 
        //             date + ';' + msg_to_publish[:-1])

        // except Exception as e:
        //     print(e)
        //     */

    }
};


int main(int argc, char*argv[])
{

    sw::redis::Redis redis = sw::redis::Redis("tcp://127.0.0.1:6379");
    std::string kafka_topic_main_stream = "paris_gps_status";
    std::string brokers = "localhost:9092";

	try{

    CustomKafkaConsumer consumer(brokers, kafka_topic_main_stream, redis);

    // Constructs new threads and runs them. 
    // Does not block execution.
    std::thread record_service(&CustomKafkaConsumer::listen, // the pointer-to-member
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


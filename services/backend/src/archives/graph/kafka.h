/**
 * # Start Zookeeper and Kafka:
 * export BROKER_IP_ADDRESS=localhost
 * export BROKER_PORT=9092
 * export YOUR_TOPIC_NAME=test_topic
 * 
 * # Start Zookeeper service in a tmux session
 * tmux new -s zookeeper-server-start -d
 * tmux send-keys "~/Kafka/bin/zookeeper-server-start.sh ~/Kafka/config/zookeeper.properties" Enter
 * 
 * # Start Kafka server in a tmux session
 * tmux new -s kafka-server-start -d
 * tmux send-keys "~/Kafka/bin/kafka-server-start.sh ~/Kafka/config/server.properties" Enter
 * 
 * # Dynamic libraries
 * export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/lib
 * # Build
 * g++ --std=c++14 simple_consumer_producer.cpp -o run -lrdkafka++
 * # Run
 * ./run -C -t test_topic -p 0
 * ./run -C -t yaya -b localhost:9092 -p 0
 * 
Usage: ./run [-C|-P] -t <topic> [-p <partition>] [-b <host1:port1,host2:port2,..>]

librdkafka version 1.6.1-37-g1a3827 (0x010601ff, builtin.features "gzip,snappy,ssl,sasl,regex,lz4,sasl_plain,sasl_scram,plugins,sasl_oauthbearer")

 Options:
  -C | -P         Consumer or Producer mode
  -L              Metadata list mode
  -t <topic>      Topic to fetch / produce
  -p <num>        Partition (random partitioner)
  -p <func>       Use partitioner:
                  random (default), hash
  -b <brokers>    Broker address (localhost:9092)
  -z <codec>      Enable compression:
                  none|gzip|snappy|lz4|zstd
  -o <offset>     Start offset (consumer)
  -e              Exit consumer when last message
                  in partition has been received.
  -d [facs..]     Enable debugging contexts:
                  all,generic,broker,topic,metadata,feature,queue,msg,protocol,cgrp,security,fetch,interceptor,plugin,consumer,admin,eos,mock,assignor,conf
  -M <intervalms> Enable statistics
  -X <prop=name>  Set arbitrary librdkafka configuration property
                  Properties prefixed with "topic." will be set on topic object.
                  Use '-X list' to see the full list
                  of supported properties.
  -f <flag>       Set option:
                     ccb - use consume_callback

 In Consumer mode:
  writes fetched messages to stdout
 In Producer mode:
  reads messages from stdin and sends to broker
 */

/*
 * librdkafka - Apache Kafka C library
 *
 * Copyright (c) 2014, Magnus Edenhill
 * All rights reserved.
 * 
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met: 
 * 
 * 1. Redistributions of source code must retain the above copyright notice,
 *    this list of conditions and the following disclaimer. 
 * 2. Redistributions in binary form must reproduce the above copyright notice,
 *    this list of conditions and the following disclaimer in the documentation
 *    and/or other materials provided with the distribution. 
 * 
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE 
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE 
 * ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE 
 * LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR 
 * CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF 
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS 
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN 
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 */

/**
 * Apache Kafka consumer & producer example programs
 * using the Kafka driver from librdkafka
 * (https://github.com/edenhill/librdkafka)
 */

#include <iostream>
#include <sstream>
#include <string>
#include <cstdlib>
#include <cstdio>
#include <csignal>
#include <cstring>
#include <functional>
#include "rapidjson/document.h"

#ifdef _WIN32
#include "../win32/wingetopt.h"
#elif _AIX
#include <unistd.h>
#else
#include <getopt.h>
#endif

/*
 * Typically include path in a real application would be
 * #include <librdkafka/rdkafkacpp.h>
 */
#include <librdkafka/rdkafkacpp.h>


static volatile sig_atomic_t run = 1;
static bool exit_eof = false;

static void sigterm (int sig) {
  run = 0;
}


class LocalDeliveryReportCb : public RdKafka::DeliveryReportCb {
 public:
  void dr_cb (RdKafka::Message &message) {
    std::string status_name;
    switch (message.status())
      {
      case RdKafka::Message::MSG_STATUS_NOT_PERSISTED:
        status_name = "NotPersisted";
        break;
      case RdKafka::Message::MSG_STATUS_POSSIBLY_PERSISTED:
        status_name = "PossiblyPersisted";
        break;
      case RdKafka::Message::MSG_STATUS_PERSISTED:
        status_name = "Persisted";
        break;
      default:
        status_name = "Unknown?";
        break;
      }
    std::cout << "Message delivery for (" << message.len() << " bytes): " <<
      status_name << ": " << message.errstr() << std::endl;
    if (message.key())
      std::cout << "Key: " << *(message.key()) << ";" << std::endl;
  }
};


class ErrorEventCb : public RdKafka::EventCb {
 public:
  void event_cb (RdKafka::Event &event) {
    switch (event.type())
    {
      case RdKafka::Event::EVENT_ERROR:
        if (event.fatal()) {
          std::cerr << "FATAL ";
          run = 0;
        }
        std::cerr << "ERROR (" << RdKafka::err2str(event.err()) << "): " <<
            event.str() << std::endl;
        break;

      case RdKafka::Event::EVENT_STATS:
        std::cerr << "\"STATS\": " << event.str() << std::endl;
        break;

      case RdKafka::Event::EVENT_LOG:
        fprintf(stderr, "LOG-%i-%s: %s\n",
                event.severity(), event.fac().c_str(), event.str().c_str());
        break;

      default:
        std::cerr << "EVENT " << event.type() <<
            " (" << RdKafka::err2str(event.err()) << "): " <<
            event.str() << std::endl;
        break;
    }
  }
};


class KafkaMessageProducer
{
  public:
    std::string brokers; 
    std::string topic;
    RdKafka::Producer *producer;

    // Constructor
    KafkaMessageProducer(std::string brokers, std::string topic) {     // Constructor
      this->brokers = brokers; 
      this->topic = topic;

      // Création d'un objet de configuration
      RdKafka::Conf *conf = RdKafka::Conf::create(RdKafka::Conf::CONF_GLOBAL);

      std::string errstr;

      /* Initialise les bootstrap broker(s) comme une liste comma-separated 
      * de host ou host:port (port par défaut 9092).
      * librdkafka utilisera les bootstrap brokers pour récupérer l'ensemble
      * des brokers du cluster. */

      // Prise en compte des brokers
      //    -> Si erreur: sortie du programme
      if (conf->set("bootstrap.servers", brokers, errstr) != RdKafka::Conf::CONF_OK) {
        std::cerr << errstr << std::endl;
        exit(1);
      }

      /*
      * signal() attrape les évènements imprévus
      * Le premier argument est un entier réprentant le numéro du 
      * signal et le second argument en tant que pointeur vers la
      * fonction de traitement du signal.
      */
      // SIGINT = 4 - Signal de mise en garde.
      signal(SIGINT, sigterm);
      // SIGTERM = 6 - Requête d'arrêt envoyé au programme.
      signal(SIGTERM, sigterm);

      /* Set the delivery report callback.
      * This callback will be called once per message to inform
      * the application if delivery succeeded or failed.
      * See dr_msg_cb() above.
      * The callback is only triggered from ::poll() and ::flush().
      *
      * IMPORTANT:
      * Make sure the DeliveryReport instance outlives the Producer object,
      * either by putting it on the heap or as in this case as a stack variable
      * that will NOT go out of scope for the duration of the Producer object.
      */

      // Définition d'un callback qui sera appelé une fois par message pour informer 
      // si la délivrance du message à réussie ou échouée
      LocalDeliveryReportCb ex_dr_cb;
      // dr_cb : delivery report callback
      if (conf->set("dr_cb", &ex_dr_cb, errstr) != RdKafka::Conf::CONF_OK) {
        std::cerr << errstr << std::endl;
        exit(1);
      }

      /*
      * Création d'un producer instance.
      */
      producer = RdKafka::Producer::create(conf, errstr);
      if (!producer) {
        std::cerr << "Failed to create producer: " << errstr << std::endl;
        exit(1);
      }

      delete conf;
    }


    bool kafka_message_builder(std::string line) {  // Method/function defined inside the class
   
      if (line.empty()) {
        std::cout << "Line empty" << std::endl;
        //producer->poll(0);
        return 0;
      }
      try {  


        /*
        * Send/Produce message.
        * This is an asynchronous call, on success it will only
        * enqueue the message on the internal producer queue.
        * The actual delivery attempts to the broker are handled
        * by background threads.
        * The previously registered delivery report callback
        * is used to signal back to the application when the message
        * has been delivered (or failed permanently after retries).
        */
       /*
        std::cout << "topic: " << topic << std::endl;
        std::cout << "RdKafka::Topic::PARTITION_UA: " << RdKafka::Topic::PARTITION_UA << std::endl;
        std::cout << "RdKafka::Producer::RK_MSG_COPY: " << RdKafka::Producer::RK_MSG_COPY << std::endl;
        std::cout << "const_cast<char *>(line.c_str()): " << const_cast<char *>(line.c_str()) << std::endl;
        std::cout << "line.size(): " << line.size() << std::endl;
        std::cout << "topic: " << topic << std::endl;
        */
        
        retry:
          RdKafka::ErrorCode err =
            producer->produce(
                              /* Topic name */
                              topic,
                              /* Any Partition: the builtin partitioner will be
                              * used to assign the message to a topic based
                              * on the message key, or random partition if
                              * the key is not set. */
                              RdKafka::Topic::PARTITION_UA,
                              /* Make a copy of the value */
                              RdKafka::Producer::RK_MSG_COPY /* Copy payload */,
                              /* Value */
                              const_cast<char *>(line.c_str()), line.size(),
                              /* Key */
                              NULL, 0,
                              /* Timestamp (defaults to current time) */
                              0,
                              /* Message headers, if any */
                              NULL,
                              /* Per-message opaque value passed to
                              * delivery report */
                              NULL);

          if (err != RdKafka::ERR_NO_ERROR) {
            std::cerr << "% Failed to produce to topic " << topic << ": " <<
              RdKafka::err2str(err) << std::endl;

            if (err == RdKafka::ERR__QUEUE_FULL) {
              /* If the internal queue is full, wait for
              * messages to be delivered and then retry.
              * The internal queue represents both
              * messages to be sent and messages that have
              * been sent or failed, awaiting their
              * delivery report callback to be called.
              *
              * The internal queue is limited by the
              * configuration property
              * queue.buffering.max.messages */
              producer->poll(1000/*block for max 1000ms*/);
              goto retry;
            }

          } else {
            std::cerr << "% Enqueued message (" << line.size() << " bytes) " <<
              "for topic " << topic << std::endl;
          }

          /* A producer application should continually serve
          * the delivery report queue by calling poll()
          * at frequent intervals.
          * Either put the poll call in your main loop, or in a
          * dedicated thread, or call it after every produce() call.
          * Just make sure that poll() is still called
          * during periods where you are not producing any messages
          * to make sure previously produced messages have their
          * delivery report callback served (and any other callbacks
          * you register). */
          //producer->poll(0);
          //std::cout << "Après producer->poll(0)" << std::endl;
      }
      catch ( std::exception& ex )
      {
        std::cout << "uncaught exception: " << ex.what() << "\n";
      }

      //std::cout << "On est là" << std::endl;

      return 1;

    };
};



class KafkaConsumer
{
  std::string brokers;
  std::string kafka_topic;
  //KafkaMessageProducer &producer;
  //cms::GraphCH &graph;

  public:
    // Constructor

    KafkaConsumer(
      std::string brokers_
      , std::string kafka_topic_
    ):
      brokers(brokers_)
      , kafka_topic(kafka_topic_)
    {};

    virtual void custom_consume(RdKafka::Message* message) = 0;

/*
    KafkaConsumer(
      std::string brokers_
      , std::string kafka_topic_
      , KafkaMessageProducer &producer_
      , cms::GraphCH &graph_
    ):
      brokers(brokers_)
      , kafka_topic(kafka_topic_)
      , producer(producer_)
      , graph(graph_)
    {};

    void consume(RdKafka::Message* message) {

      rapidjson::Document document;
      //document.SetFloat(0.09f);

      // Parse a RdKafka::Message* to const char*
      const char* parsed_message = parse(message);
      if (parsed_message == "")
        return;
      std::cout << "message: " << parsed_message << std::endl;

      // Build a rapidjson::Document
      document.Parse(parsed_message);

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
      // Send the message through Kafka
      producer.kafka_message_builder("{\"date\":\"" + date + "\",\"routes\":[" + routes + "]}");

    }
*/



    void listen(
              int amount_of_time_to_wait_messages_ms
    )  {


      std::string errstr;
      int32_t partition = 0;
      // Pour un traitement en partant du plus ancien des messages
      //int64_t offset = RdKafka::Topic::OFFSET_BEGINNING; 
      // Pour un traitement sans reprise des anciens des messages
      int64_t offset = RdKafka::Topic::OFFSET_END; 
      int opt;
      int use_ccb = 0;


      /*
      * Instancie les objets de configuration
      */
      RdKafka::Conf *conf = RdKafka::Conf::create(RdKafka::Conf::CONF_GLOBAL);
      RdKafka::Conf *tconf = RdKafka::Conf::create(RdKafka::Conf::CONF_TOPIC);

      /*
      * Défini les propriétés de configuration
      */
      conf->set("metadata.broker.list", brokers, errstr);
      // Déclaration d'un callback en cas d'erreur
      ErrorEventCb ex_event_cb;
      conf->set("event_cb", &ex_event_cb, errstr);

      LocalDeliveryReportCb ex_dr_cb;
      /* Set delivery report callback */
      conf->set("dr_cb", &ex_dr_cb, errstr);
      conf->set("default_topic_conf", tconf, errstr);

      // enable.partition.eof est une propriété de configuration globale (https://docs.confluent.io/3.2.1/clients/librdkafka/CONFIGURATION_8md.html)
      // Emet l'évènement RD_KAFKA_RESP_ERR__PARTITION_EOF à chaque fois qu'un consumer atteint la fin d'une partition. *Type: boolean*
      // RD_KAFKA_RESP_ERR__PARTITION_EOF: A atteint la fin de la file d'attente topic+partition du broker.
      conf->set("enable.partition.eof", "true", errstr);


      /* Permettra d'arrêter la boucle d'invite de commande
      * signal() attrape les évènements imprévus
      * Le premier argument est un entier réprentant le numéro du 
      * signal et le second argument en tant que pointeur vers la
      * fonction de traitement du signal.
      */
      // SIGINT = 4 - Signal de mise en garde.
      signal(SIGINT, sigterm);
      // SIGTERM = 6 - Requête d'arrêt envoyé au programme.
      signal(SIGTERM, sigterm);

      /*
        * Crée un consommateur sur les propriétés de configuration.
        */
      RdKafka::Consumer *consumer = RdKafka::Consumer::create(conf, errstr);
      if (!consumer) {
        std::cerr << "Failed to create consumer: " << errstr << std::endl;
        exit(1);
      }

      std::cout << "% Created consumer " << consumer->name() << std::endl;

      /*
        * Défini le topic à traiter
        */
      RdKafka::Topic *topic = RdKafka::Topic::create(consumer, kafka_topic,
                  tconf, errstr);
      if (!topic) {
        std::cerr << "Failed to create topic: " << errstr << std::endl;
        exit(1);
      }

      /*
        * Défini un consumer pour le topic+partition à l'offset indiqué
        */
      RdKafka::ErrorCode resp = consumer->start(topic, partition, offset);
      if (resp != RdKafka::ERR_NO_ERROR) {
        std::cerr << "Failed to start consumer: " <<
        RdKafka::err2str(resp) << std::endl;
        exit(1);
      }


      /*
      * Consume messages
      */
      while (run) {

          RdKafka::Message *msg = consumer->consume(topic, partition, amount_of_time_to_wait_messages_ms);

          //std::cout << "msg->len(): " << msg->len() << std::endl;
          //std::cout << "msg->payload(): " << msg->payload() << std::endl;
          if (msg->len() != 0)
            this->custom_consume(msg);
            //kafka_message_parser(msg, NULL, kafka_message_consumer, graph);
          delete msg;

          consumer->poll(0);

      }

      /*
      * Stop consumer
      */
      consumer->stop(topic, partition);

      consumer->poll(1000);

      delete topic;
      delete consumer;

      delete conf;
      delete tconf;

      /*
      * Wait for RdKafka to decommission.
      * This is not strictly needed (when check outq_len() above), but
      * allows RdKafka to clean up all its resources before the application
      * exits so that memory profilers such as valgrind wont complain about
      * memory leaks.
      */
      RdKafka::wait_destroyed(5000);


    }


    rapidjson::Document parse(RdKafka::Message* message, void* opaque = NULL) {
      const char* parsed_message;
      rapidjson::Document document;
      //document.SetFloat(0.09f);

       /***
       * Start parsing
       **/
      const RdKafka::Headers *headers;
   
      switch (message->err()) {
        case RdKafka::ERR__TIMED_OUT:
          parsed_message = "";
          break;
 
        case RdKafka::ERR_NO_ERROR:
      
          parsed_message = static_cast<const char *>(message->payload());
          break;

        case RdKafka::ERR__PARTITION_EOF:
          /* Last message */
          if (exit_eof) {
            run = 0;
          }
          parsed_message = "";
          break;

        case RdKafka::ERR__UNKNOWN_TOPIC:
        case RdKafka::ERR__UNKNOWN_PARTITION:
          std::cerr << "Consume failed: " << message->errstr() << std::endl;
          run = 0;
          parsed_message = "";
          break;

        default:
          /* Errors */
          std::cerr << "Consume failed: " << message->errstr() << std::endl;
          run = 0;
          parsed_message = "";
      }
      /**
       * Message parsed
       ***/

      std::cout << "message: " << parsed_message << std::endl;

      // Build a rapidjson::Document
      document.Parse(parsed_message);
  

      return document;

    }


    // const char * parse(RdKafka::Message* message, void* opaque = NULL) {
    //   const RdKafka::Headers *headers;
   
    //   switch (message->err()) {
    //     case RdKafka::ERR__TIMED_OUT:
    //       break;
 
    //     case RdKafka::ERR_NO_ERROR:
    //       /* Real message */
    //       /*
    //       std::cout << "Read msg at offset " << message->offset() << std::endl;
    //       if (message->key()) {
    //         std::cout << "Key: " << *message->key() << std::endl;
    //       }
    //       headers = message->headers();
    //       if (headers) {
    //         std::vector<RdKafka::Headers::Header> hdrs = headers->get_all();
    //         for (size_t i = 0 ; i < hdrs.size() ; i++) {
    //           const RdKafka::Headers::Header hdr = hdrs[i];

    //           if (hdr.value() != NULL)
    //             printf(" Header: %s = \"%.*s\"\n",
    //                   hdr.key().c_str(),
    //                   (int)hdr.value_size(), (const char *)hdr.value());
    //           else
    //             printf(" Header:  %s = NULL\n", hdr.key().c_str());
    //         }
    //       }
    //       */
        
    //       //tests
    //       /*
    //       dada = static_cast<const char *>(message->payload());

    //       std::cout << dada << std::endl;
    //       printf("%.*s\n",
    //         static_cast<int>(message->len()),
    //         static_cast<const char *>(message->payload()));
    //       */

    //       // envoi du message à la fonction de le traiter
    //       // callback(static_cast<const char *>(message->payload()), graph);
    //       return static_cast<const char *>(message->payload());
    //       break;

    //     case RdKafka::ERR__PARTITION_EOF:
    //       /* Last message */
    //       if (exit_eof) {
    //         run = 0;
    //       }
    //       break;

    //     case RdKafka::ERR__UNKNOWN_TOPIC:
    //     case RdKafka::ERR__UNKNOWN_PARTITION:
    //       std::cerr << "Consume failed: " << message->errstr() << std::endl;
    //       run = 0;
    //       break;

    //     default:
    //       /* Errors */
    //       std::cerr << "Consume failed: " << message->errstr() << std::endl;
    //       run = 0;
    //   }
    //   return "";
    // }
};

// void kafka_message_parser(RdKafka::Message* message, void* opaque = NULL, std::function<bool(const char *,cms::GraphCH &)> callback, cms::GraphCH &graph) {
//   const RdKafka::Headers *headers;
//   const char * dada; 
//   switch (message->err()) {
//     case RdKafka::ERR__TIMED_OUT:
//       break;

//     case RdKafka::ERR_NO_ERROR:
//       /* Real message */
//       /*
//       std::cout << "Read msg at offset " << message->offset() << std::endl;
//       if (message->key()) {
//         std::cout << "Key: " << *message->key() << std::endl;
//       }
//       headers = message->headers();
//       if (headers) {
//         std::vector<RdKafka::Headers::Header> hdrs = headers->get_all();
//         for (size_t i = 0 ; i < hdrs.size() ; i++) {
//           const RdKafka::Headers::Header hdr = hdrs[i];

//           if (hdr.value() != NULL)
//             printf(" Header: %s = \"%.*s\"\n",
//                    hdr.key().c_str(),
//                    (int)hdr.value_size(), (const char *)hdr.value());
//           else
//             printf(" Header:  %s = NULL\n", hdr.key().c_str());
//         }
//       }
//       */
     
//       //tests
//       /*
//       dada = static_cast<const char *>(message->payload());

//       std::cout << dada << std::endl;
//       printf("%.*s\n",
//         static_cast<int>(message->len()),
//         static_cast<const char *>(message->payload()));
//       */

//       // envoi du message à la fonction de le traiter
//       callback(static_cast<const char *>(message->payload()), graph);

//       break;

//     case RdKafka::ERR__PARTITION_EOF:
//       /* Last message */
//       if (exit_eof) {
//         run = 0;
//       }
//       break;

//     case RdKafka::ERR__UNKNOWN_TOPIC:
//     case RdKafka::ERR__UNKNOWN_PARTITION:
//       std::cerr << "Consume failed: " << message->errstr() << std::endl;
//       run = 0;
//       break;

//     default:
//       /* Errors */
//       std::cerr << "Consume failed: " << message->errstr() << std::endl;
//       run = 0;
//   }
// }


void string_to_coordinates_vector(const char* message, std::vector<float> &response) {
 
  char delimiter = ',';

    try {

      std::istringstream split(message); 
      for (std::string each; std::getline(split, each, delimiter); response.push_back(std::stof(each)));

      if(response.size() != 4) {
        response.clear();
        throw std::invalid_argument( "(Message invalid) " + (std::string)message);
      }

    }catch(std::exception&err){
        std::cerr << "Stopped on exception: " << err.what() << ", Message: " << message << std::endl;
    }


}


/*
bool kafka_message_consumer(const char * message) {
  
  std::vector<float> splitted_message;

  string_to_coordinates_vector(message, splitted_message);
  if(splitted_message.size() != 0) {
    std::cout << "Process (lat1 lon1 lat2 lon2): " ;
    for (std::vector<float>::const_iterator i = splitted_message.begin(); i != splitted_message.end(); ++i)
      std::cout << *i << ' ';
    std::cout << std::endl;
  }
  return(true);
}
*/

template <typename T>
void kafka_messages_listener(
          const std::string brokers
          , const std::string topic_str
          , int amount_of_time_to_wait_messages_ms
          , T &custom_consumer
)  {


  std::string errstr;
  int32_t partition = 0;
  // Pour un traitement en partant du plus ancien des messages
  //int64_t offset = RdKafka::Topic::OFFSET_BEGINNING; 
  // Pour un traitement sans reprise des anciens des messages
  int64_t offset = RdKafka::Topic::OFFSET_END; 
  int opt;
  int use_ccb = 0;


  /*
   * Instancie les objets de configuration
   */
  RdKafka::Conf *conf = RdKafka::Conf::create(RdKafka::Conf::CONF_GLOBAL);
  RdKafka::Conf *tconf = RdKafka::Conf::create(RdKafka::Conf::CONF_TOPIC);

  /*
   * Défini les propriétés de configuration
   */
  conf->set("metadata.broker.list", brokers, errstr);
  // Déclaration d'un callback en cas d'erreur
  ErrorEventCb ex_event_cb;
  conf->set("event_cb", &ex_event_cb, errstr);

  LocalDeliveryReportCb ex_dr_cb;
  /* Set delivery report callback */
  conf->set("dr_cb", &ex_dr_cb, errstr);
  conf->set("default_topic_conf", tconf, errstr);

  // enable.partition.eof est une propriété de configuration globale (https://docs.confluent.io/3.2.1/clients/librdkafka/CONFIGURATION_8md.html)
  // Emet l'évènement RD_KAFKA_RESP_ERR__PARTITION_EOF à chaque fois qu'un consumer atteint la fin d'une partition. *Type: boolean*
  // RD_KAFKA_RESP_ERR__PARTITION_EOF: A atteint la fin de la file d'attente topic+partition du broker.
  conf->set("enable.partition.eof", "true", errstr);


  /* Permettra d'arrêter la boucle d'invite de commande
   * signal() attrape les évènements imprévus
   * Le premier argument est un entier réprentant le numéro du 
   * signal et le second argument en tant que pointeur vers la
   * fonction de traitement du signal.
   */
  // SIGINT = 4 - Signal de mise en garde.
  signal(SIGINT, sigterm);
  // SIGTERM = 6 - Requête d'arrêt envoyé au programme.
  signal(SIGTERM, sigterm);

  /*
    * Crée un consommateur sur les propriétés de configuration.
    */
  RdKafka::Consumer *consumer = RdKafka::Consumer::create(conf, errstr);
  if (!consumer) {
    std::cerr << "Failed to create consumer: " << errstr << std::endl;
    exit(1);
  }

  std::cout << "% Created consumer " << consumer->name() << std::endl;

  /*
    * Défini le topic à traiter
    */
  RdKafka::Topic *topic = RdKafka::Topic::create(consumer, topic_str,
              tconf, errstr);
  if (!topic) {
    std::cerr << "Failed to create topic: " << errstr << std::endl;
    exit(1);
  }

  /*
    * Défini un consumer pour le topic+partition à l'offset indiqué
    */
  RdKafka::ErrorCode resp = consumer->start(topic, partition, offset);
  if (resp != RdKafka::ERR_NO_ERROR) {
    std::cerr << "Failed to start consumer: " <<
	  RdKafka::err2str(resp) << std::endl;
    exit(1);
  }


  /*
   * Consume messages
   */
  while (run) {

      RdKafka::Message *msg = consumer->consume(topic, partition, amount_of_time_to_wait_messages_ms);

      //std::cout << "msg->len(): " << msg->len() << std::endl;
      //std::cout << "msg->payload(): " << msg->payload() << std::endl;
      if (msg->len() != 0)
        custom_consumer.custom_consume(msg);
        //kafka_message_parser(msg, NULL, kafka_message_consumer, graph);
      delete msg;

      consumer->poll(0);

  }

  /*
   * Stop consumer
   */
  consumer->stop(topic, partition);

  consumer->poll(1000);

  delete topic;
  delete consumer;

  delete conf;
  delete tconf;

  /*
   * Wait for RdKafka to decommission.
   * This is not strictly needed (when check outq_len() above), but
   * allows RdKafka to clean up all its resources before the application
   * exits so that memory profilers such as valgrind wont complain about
   * memory leaks.
   */
  RdKafka::wait_destroyed(5000);


}

// void kafka_messages_listener(
//           const std::string brokers
//           , const std::string topic_str
//           , int amount_of_time_to_wait_messages_ms
//           , std::function<bool(const char *,cms::GraphCH &)> callback
//           , cms::GraphCH &graph
// ) {


//   KafkaConsumer custom_consumer(brokers, topic_str);
//   std::string errstr;
//   int32_t partition = 0;
//   // Pour un traitement en partant du plus ancien des messages
//   //int64_t offset = RdKafka::Topic::OFFSET_BEGINNING; 
//   // Pour un traitement sans reprise des anciens des messages
//   int64_t offset = RdKafka::Topic::OFFSET_END; 
//   int opt;
//   int use_ccb = 0;


//   /*
//    * Instancie les objets de configuration
//    */
//   RdKafka::Conf *conf = RdKafka::Conf::create(RdKafka::Conf::CONF_GLOBAL);
//   RdKafka::Conf *tconf = RdKafka::Conf::create(RdKafka::Conf::CONF_TOPIC);

//   /*
//    * Défini les propriétés de configuration
//    */
//   conf->set("metadata.broker.list", brokers, errstr);
//   // Déclaration d'un callback en cas d'erreur
//   ErrorEventCb ex_event_cb;
//   conf->set("event_cb", &ex_event_cb, errstr);

//   LocalDeliveryReportCb ex_dr_cb;
//   /* Set delivery report callback */
//   conf->set("dr_cb", &ex_dr_cb, errstr);
//   conf->set("default_topic_conf", tconf, errstr);

//   // enable.partition.eof est une propriété de configuration globale (https://docs.confluent.io/3.2.1/clients/librdkafka/CONFIGURATION_8md.html)
//   // Emet l'évènement RD_KAFKA_RESP_ERR__PARTITION_EOF à chaque fois qu'un consumer atteint la fin d'une partition. *Type: boolean*
//   // RD_KAFKA_RESP_ERR__PARTITION_EOF: A atteint la fin de la file d'attente topic+partition du broker.
//   conf->set("enable.partition.eof", "true", errstr);


//   /* Permettra d'arrêter la boucle d'invite de commande
//    * signal() attrape les évènements imprévus
//    * Le premier argument est un entier réprentant le numéro du 
//    * signal et le second argument en tant que pointeur vers la
//    * fonction de traitement du signal.
//    */
//   // SIGINT = 4 - Signal de mise en garde.
//   signal(SIGINT, sigterm);
//   // SIGTERM = 6 - Requête d'arrêt envoyé au programme.
//   signal(SIGTERM, sigterm);

//   /*
//     * Crée un consommateur sur les propriétés de configuration.
//     */
//   RdKafka::Consumer *consumer = RdKafka::Consumer::create(conf, errstr);
//   if (!consumer) {
//     std::cerr << "Failed to create consumer: " << errstr << std::endl;
//     exit(1);
//   }

//   std::cout << "% Created consumer " << consumer->name() << std::endl;

//   /*
//     * Défini le topic à traiter
//     */
//   RdKafka::Topic *topic = RdKafka::Topic::create(consumer, topic_str,
//               tconf, errstr);
//   if (!topic) {
//     std::cerr << "Failed to create topic: " << errstr << std::endl;
//     exit(1);
//   }

//   /*
//     * Défini un consumer pour le topic+partition à l'offset indiqué
//     */
//   RdKafka::ErrorCode resp = consumer->start(topic, partition, offset);
//   if (resp != RdKafka::ERR_NO_ERROR) {
//     std::cerr << "Failed to start consumer: " <<
// 	  RdKafka::err2str(resp) << std::endl;
//     exit(1);
//   }


//   /*
//    * Consume messages
//    */
//   while (run) {

//     RdKafka::Message *msg = consumer->consume(topic, partition, amount_of_time_to_wait_messages_ms);
//     custom_consumer.consume(msg);
//     delete msg;

//     consumer->poll(0);
//   }

//   /*
//    * Stop consumer
//    */
//   consumer->stop(topic, partition);

//   consumer->poll(1000);

//   delete topic;
//   delete consumer;

//   delete conf;
//   delete tconf;

//   /*
//    * Wait for RdKafka to decommission.
//    * This is not strictly needed (when check outq_len() above), but
//    * allows RdKafka to clean up all its resources before the application
//    * exits so that memory profilers such as valgrind wont complain about
//    * memory leaks.
//    */
//   RdKafka::wait_destroyed(5000);


// }

/*
int main (int argc, char **argv) {

  kafka_messages_listener("localhost:9092", "yaya", 1000, kafka_message_consumer);


  return 0;
}
*/
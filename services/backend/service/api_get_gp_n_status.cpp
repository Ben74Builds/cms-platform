/**
   REST endpoint to retrievve current units status and geographical positions

   Build your script
   g++ --std=c++17 ./service/api_get_gp_n_status.cpp -o ./bin/api_get_gp_n_status  -lpistache -lpthread -lredis++ -lhiredis
   Run it
   ./run
   
   In another terminal test your API
   Check if the service is ready
   curl -s http://localhost:9080/ready
   Read a value (GET method)
   curl -s 'http://localhost:9080/get_gp_and_status/1'

   Check Redis keys matching a pattern
   redis-cli KEYS *pattern*

   To kill a specific port on linux do
   lsof -t -i:my_port_number

   @file api_get_gp_n_status.cpp
   @author Benjamin Berhault
*/



#include <string>
#include <unordered_set>
#include <bits/stdc++.h>
#include <algorithm>
#include <unistd.h>
#include <iostream>
#include <cstdlib>
#include <signal.h>

#include <pistache/http.h>
#include <pistache/router.h>
#include <pistache/endpoint.h>
#include <sw/redis++/redis++.h>


/**
 * Signal handler
 *
 * @param signum status code (if is 0 or EXIT_SUCCESS, a successful termination status is returned to the host environment.If is  EXIT_FAILURE, an unsuccessful termination status is returned to the host environment)
 */
void signal_callback_handler(int signum) {
   std::cout << "Caught signal " << signum << std::endl;
   // Terminate program
   exit(signum);
}

/**
 * Split a string by a given delimiter 
 *
 * @param s String to split
 * @param delim Delimiter
 * @return the vector of the splitted string
 */
std::vector<std::string> split (const std::string &s, char delim) {
    std::vector<std::string> result;
    std::stringstream ss (s);
    std::string item;

    while (getline (ss, item, delim)) {
        result.push_back (item);
    }

    return result;
}


/**
 * Simple test to know if the service is working calling: url/ready
 * curl -s http://localhost:9080/ready
 *
 * @param s String to split
 * @param delim Delimiter
 * @return the vector of the splitted string
 */
namespace Generic {

    void handleReady(const Pistache::Rest::Request&, Pistache::Http::ResponseWriter response) {
        response.headers().add<Pistache::Http::Header::AccessControlAllowOrigin>("*");
        response.send(Pistache::Http::Code::Ok, "1\n");
    }

}


class StatsEndpoint {
public:
    explicit StatsEndpoint(Pistache::Address addr)
        : httpEndpoint(std::make_shared<Pistache::Http::Endpoint>(addr))
    { }

    /**
     *
     */
    void init(size_t thr = 2) {
        auto opts = Pistache::Http::Endpoint::options()
            .threads(static_cast<int>(thr));
        httpEndpoint->init(opts);
        setupRoutes();
    }

    /**
     *
     */
    void start() {
        httpEndpoint->setHandler(router.handler());
        httpEndpoint->serve();
    }

private:

    std::shared_ptr<Pistache::Http::Endpoint> httpEndpoint;
    Pistache::Rest::Router router;

    // Setup API routes
    void setupRoutes() {
        using namespace Pistache::Rest;

        // Get and return last units geolocations and status for the given service
        // Information hold in Redis
        // Terminal call: curl -s 'http://localhost:9080/get_gp_and_status/:service'
        Routes::Get(
            router
            ,"/get_gp_and_status/:service"
            ,Routes::bind(&StatsEndpoint::get_all_current_gp_and_status, this)
        );

        // To check if the API is active
        // Terminal call: curl -s 'http://localhost:9080/ready'
        Routes::Get(
            router
            ,"/ready"
            ,Routes::bind(&Generic::handleReady)
        );

    }


    /**
     * For an API request such as http://localhost:9080/get_gp_and_status/:service
     * will return all current units geographical positions and status for a given :service
     * in a JSON message
     * 
     * @param request
     * @param api_response is used to return an API response of the following structure:
     *    [{
     *      'date': '2019-01-01 00:06:59'
     *      , 'serv': 1
     *      , 'data': [
     *          {
     *              'uni': [2589, 2, 244, [1]]
     *              , 'sta': [1, 0]
     *              , 'gp1': [48.8129761, 2.3281774]
     *              , 'gp2': [48.818685, 2.316891]
     *              , 'int': [5961968, 3]
     *          }
     *      ]
     *    },{
     *      'date': '2019-01-01 00:07:00'
     *      , 'serv': 1
     *      , 'data': [
     *          {
     *              'uni': [478, 3, 245, [1]]
     *              , 'sta': [102, 0]
     *              , 'gp1': [48.8995701, 2.2020856]
     *              , 'int': [5960392, 1]
     *          }, {
     *              'uni': [4256, 2, 256, [1]]
     *              , 'sta': [102, 0]
     *              , 'gp1': [48.8373818, 2.3437573]
     *              , 'int': [5963067, 3]
     *          }
     *      ]
     *    }]
     */
    void get_all_current_gp_and_status(const Pistache::Rest::Request& request, Pistache::Http::ResponseWriter api_response) {
        auto redis = sw::redis::Redis("tcp://127.0.0.1:6379");
        std::string service = request.param(":service").as<std::string>();

        std::string json_current_gp_and_status;

        try {

            auto cursor = 0LL;
            auto pattern = service + ":*";
            auto count = 5;
            std::unordered_set<std::string> keys;
            std::string key;
            
            // Retrieve all the redis keys matching the <pattern> in 'keys'
            while (true) {
                cursor = redis.scan(cursor, pattern, count, std::inserter(keys, keys.begin()));

                if (cursor == 0) {
                    break;
                }
            }

            // Will store all redis data in a 2 dimensionnal array such as:
            // data["PS129"]["station"] = "PARM" 
            std::map<std::string,std::map<std::string,std::string>> data;
            // Will store the different dates
            std::set<std::string> dates;

            for (auto key : keys) {
                std::vector<std::string> key_splitted = split(key,':');

                // Skip coverage keys (they are SETs, not strings)
                if (key_splitted[2] == "coverage")
                    continue;

                if (key_splitted[2] == "date")
                    dates.insert(*redis.get(key));
                // insert the data in this 2-dimensional array
                data[key_splitted[1]][key_splitted[2]] = *redis.get(key);
            }

            json_current_gp_and_status = "[";
            bool more_than_one = false;
            for (auto date : dates) {
                json_current_gp_and_status += "{\"date\":\""+date+"\",\"serv\":"+service+",\"data\":[";
                more_than_one = false;
                for (auto unit : data) {
                    if (data[unit.first]["date"] == date) {
                        if(more_than_one)
                            json_current_gp_and_status += ",";

                        json_current_gp_and_status += "{\"uni\":["+unit.first;
                        json_current_gp_and_status += ",";
                        json_current_gp_and_status += (data[unit.first].count("unit_category_id")) ? data[unit.first]["unit_category_id"] : "null";
                        json_current_gp_and_status += ",";
                        json_current_gp_and_status += (data[unit.first].count("unit_parking_station_id")) ? data[unit.first]["unit_parking_station_id"] : "null";

                        if (data[unit.first].count("unit_competences_ids")) json_current_gp_and_status += ",["+data[unit.first]["unit_competences_ids"]+"]";
                        json_current_gp_and_status += "]";

                        if (data[unit.first].count("status_id") or data[unit.first].count("is_free")) {
                            json_current_gp_and_status += ",\"sta\":[";
                            json_current_gp_and_status += (data[unit.first].count("status_id")) ? data[unit.first]["status_id"] : "null";
                            json_current_gp_and_status += ",";
                            json_current_gp_and_status += (data[unit.first].count("is_free")) ? data[unit.first]["is_free"] : "null";
                            json_current_gp_and_status += "]";
                        }

                        if (data[unit.first].count("lat") and data[unit.first].count("lon")) {
                            json_current_gp_and_status += ",\"gp1\":[";
                            json_current_gp_and_status += data[unit.first]["lat"];
                            json_current_gp_and_status += ",";
                            json_current_gp_and_status += data[unit.first]["lon"];
                            json_current_gp_and_status += "]";
                        }

                        if (data[unit.first].count("lat_destination") and data[unit.first].count("lon_destination")) {
                            json_current_gp_and_status += ",\"gp2\":[";
                            json_current_gp_and_status += data[unit.first]["lat_destination"];
                            json_current_gp_and_status += ",";
                            json_current_gp_and_status += data[unit.first]["lon_destination"];
                            json_current_gp_and_status += "]";
                        }

                        if (data[unit.first].count("intervention_id") or data[unit.first].count("intervention_category")) {
                            json_current_gp_and_status += ",\"int\":[";
                            json_current_gp_and_status += (data[unit.first].count("intervention_id")) ? data[unit.first]["intervention_id"] : "null";
                            json_current_gp_and_status += ",";
                            json_current_gp_and_status += (data[unit.first].count("intervention_category")) ? data[unit.first]["intervention_category"] : "null";
                            json_current_gp_and_status += "]";
                        }

                        json_current_gp_and_status += "}";

                        more_than_one = true;
                    }
                }
                json_current_gp_and_status += "]},";
            }
            json_current_gp_and_status = json_current_gp_and_status.substr(0, json_current_gp_and_status.size()-1) + "]";

            api_response.headers().add<Pistache::Http::Header::AccessControlAllowOrigin>("*");
            api_response.send(Pistache::Http::Code::Ok, json_current_gp_and_status);

        } catch (const sw::redis::Error &err) {
            // Handle exceptions.
            std::cerr << "Redis error: " << err.what() << std::endl;
            api_response.headers().add<Pistache::Http::Header::AccessControlAllowOrigin>("*");
            api_response.send(Pistache::Http::Code::Ok, "[]");
        }     
    }

};

int main(int argc, char *argv[]) {

   // Register a ctrl-c (SIGINT) signal handler
    signal(SIGINT, signal_callback_handler);

    Pistache::Port port(9080);

    int thr = 1;

    if (argc >= 2) {
        port = static_cast<uint16_t>(std::stol(argv[1]));

        if (argc == 3)
            thr = std::stoi(argv[2]);
    }

    Pistache::Address addr(Pistache::Ipv4::any(), port);

    std::cout << "Cores = " << Pistache::hardware_concurrency() << std::endl;
    std::cout << "Using " << thr << " thread(s)" << std::endl;

    StatsEndpoint stats(addr);

    stats.init(thr);
    stats.start();
    
    
    return EXIT_SUCCESS;
}
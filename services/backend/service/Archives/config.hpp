//config.hpp
#ifndef config_hpp
#define config_hpp
namespace config {
    const bool PRINT_MESSAGES = true;
    const unsigned THRESHOLD = 300; // In milliseconds
    const std::string SERVICE = "paris";
    const std::string PATH_TO_THE_PREBUILD_GRAPH = "./data/backup/paris";

    //Redis config
    const std::string REDIS_HOST = "localhost";
    const std::string REDIS_PORT = "6379";
    const std::string REDIS_PASSWORD = "";
    const std::string REDIS_CHANNEL_GPS_AND_UNITS_STATUS = SERVICE + "_gps_status";
    const std::string REDIS_CHANNEL_COVERAGE_UPDATE = SERVICE + "_capacity_response";
    //const std::string REDIS_CHANNEL_COVERAGE_UPDATE = SERVICE + "_immediate_response";
    const int REDIS_MESSAGE_LENGTH = 6;
}
#endif
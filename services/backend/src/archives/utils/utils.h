#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <map>
#include <array>
#include <math.h>
#include <cmath> 
#include <unordered_set>
#include "rapidjson/document.h"
#include "rapidjson/writer.h"
#include "rapidjson/stringbuffer.h"

#define earthRadiusKm 6371.0
#include <pqxx/pqxx> 

void cout_message(const std::string&msg){
	std::cout << msg << std::endl;
}

void press_enter_to_continue() 
{ 
  std::cout<<"Press [Enter] to continue...";
  std::cin.ignore();
} 

std::string microseconds_to_readable_time_cout(long long microseconds_time) 
{ 
    long long microseconds = (long long) (microseconds_time) % 1000 ;
    long long milliseconds = (long long) (microseconds_time / 1000) % 1000 ;
    long long seconds = (long long) (microseconds_time / 1000000) % 60 ;
    long long minutes = (long long) ((microseconds_time / (1000000*60)) % 60);
    // long long hours   = (long long) ((duree_en_microsec / (1000000*60*60)) % 24);

	return std::to_string(minutes) + " min " + std::to_string(seconds) + " sec " + std::to_string(milliseconds) + " msec " + std::to_string(microseconds) + " µs";
}

template<class T>
void print_unordered_set(std::unordered_set<T> const &s)
{
    std::copy(s.begin(),
            s.end(),
            std::ostream_iterator<T>(std::cout, " "));
}

template<class T>
T deg2rad(T deg) {
  return (deg * M_PI / 180);
}

//  This function converts radians to decimal degrees
template<class T>
T radians_to_degrees(T rad) {
  return (rad * 180 / M_PI);
}

/**
 * Returns the distance between two points on the Earth.
 * Direct translation from http://en.wikipedia.org/wiki/Haversine_formula
 * @param lat1d Latitude of the first point in degrees
 * @param lon1d Longitude of the first point in degrees
 * @param lat2d Latitude of the second point in degrees
 * @param lon2d Longitude of the second point in degrees
 * @return The distance between the two points in kilometers
 */
template<class T>
T coordinates_to_distance(T lat1d, T lon1d, T lat2d, T lon2d) {
  T lat1r, lon1r, lat2r, lon2r, u, v;
  lat1r = deg2rad(lat1d);
  lon1r = deg2rad(lon1d);
  lat2r = deg2rad(lat2d);
  lon2r = deg2rad(lon2d);
  u = sin((lat2r - lat1r)/2);
  v = sin((lon2r - lon1r)/2);
  return 2.0 * earthRadiusKm * asin(sqrt(u * u + cos(lat1r) * cos(lat2r) * v * v));
}

template<class T>
T round(T var) 
{ 
    // 37.66666 * 100 =3766.66 
    // 3766.66 + .5 =3767.16    for rounding off value 
    // then type cast to int so value is 3767 
    // then divided by 100 so the value converted into 37.67 
    T value = (int)(var * 100 + .5); 
    return (T)value / 100; 
}

void print_rapidjson_document(rapidjson::Document &document) {
  rapidjson::StringBuffer strbuf;
  strbuf.Clear();

  rapidjson::Writer<rapidjson::StringBuffer> writer(strbuf);
  document.Accept(writer);

  std::cout << "Message: " << strbuf.GetString() << std::endl;
};

template <class T>
std::string rapidjson_element_to_string(T &document,const char *param){
    if(document[param].IsString())
        return document[param].GetString();
    else if(document[param].IsInt())
        return std::to_string(document[param].GetInt());
    else if(document[param].IsFloat())
        return std::to_string(document[param].GetFloat());
    else if(document[param].IsDouble())
        return std::to_string(document[param].GetDouble());
    else
        return "";
    
} 


template<typename T>
std::string stringify_rapidjson_object(const T& o)
{
    rapidjson::StringBuffer strbuf;
    strbuf.Clear();

    rapidjson::Writer<rapidjson::StringBuffer> writer(strbuf);
    o.Accept(writer);

    return strbuf.GetString();
}


template <class T>
std::string rapidjson_element_to_string(T &el){
    if(el.IsString())
        return el.GetString();
    else if(el.IsInt())
        return std::to_string(el.GetInt());
    else if(el.IsFloat())
        return std::to_string(el.GetFloat());
    else if(el.IsDouble())
        return std::to_string(el.GetDouble());
    else
        return "";
    
} 


std::map<std::string, std::string> load_config_variables_from_file(std::string filename) {
    std::ifstream file( filename );
    std::map<std::string, std::string> config { };

    if ( file )
    {
        std::stringstream buffer;

        buffer << file.rdbuf();

        std::string line;

        while( std::getline(buffer, line) )
        {
            std::istringstream is_line(line);
            std::string key;
            if( std::getline(is_line, key, '=') )
            {
                std::string value;
                if( std::getline(is_line, value) ) 
                config[key] = value;
                std::cout << "key: " << key << " | " << "value: " << value << std::endl;
            }
        }
        file.close();
    }
    return config;
}

int query_on_postgresql(std::string connection_string, std::string query) {

   try {

      //auto start = std::chrono::high_resolution_clock::now();
      
      pqxx::connection C(connection_string);
      if (C.is_open()) {
         std::cout << "Opened database successfully: " << C.dbname() << std::endl;
      } else {
         std::cout << "Can't open database" << std::endl;
         return 1;
      }
      pqxx::work txn{C};
      txn.exec0(query);

      // Make our change definite.
      txn.commit();

      //auto elapsed = std::chrono::high_resolution_clock::now() - start;
      //std::cout << std::chrono::duration_cast<std::chrono::microseconds>(elapsed).count() << " microseconds" << std::endl;

   } catch (const std::exception &e) {
      std::cerr << e.what() << std::endl;
      return 1;
   }

   return 0;   
}
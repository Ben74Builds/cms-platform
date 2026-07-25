/**
 * This script allow you to choose a road graph to load from different preprocessed
 * OpenStreetMap PBF files, to compute the capacity response for every way according 
 * the given threshold, the number of units available randomly dispatched and export 
 * this information in a GeoJSON file
 * 
 * PREREQUISITE
 * To have at least one precomputed graph in a subdirectory of the ./data/backup directory.
 * One can generate it with the ./test/pbf_to_contracted_graph.cpp script. 
 *
 * COMPILE AND EXECUTE
 *
 * # Compile:
 * g++ -Ilib/RoutingKit/include -Llib/RoutingKit/lib -std=c++11 ./test/benchmark_capacity_response.cpp -o ./bin/benchmark_capacity_response -lroutingkit -lprotobuf-lite -losmpbf -lz -lboost_serialization -lstdc++fs
 * 
 * # Add needed shared libraries to the environment variable LD_LIBRARY_PATH:
 * export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:./lib/RoutingKit/lib:/usr/local/lib64:/usr/local/lib
 * 
 * # Launch the generated executable
 * ./bin/benchmark_capacity_response
 */

#include <dirent.h>
#include "../src/graph.cpp"

cms::GraphCH graph;

/**
 * Get the list of directories in the given PATH.
 *
 * @param PATH is the path from where to list directories.
 * @return The path for the choosen directory.
 */
std::string select_a_directory(std::string PATH)
{

    std::vector<std::string> repository;
    DIR *dir = opendir(PATH.c_str());
    struct dirent *entry = readdir(dir);
    int i = 0;

    // Print and memorize the list of directories for the given PATH 
    while (entry != NULL)
    {
        std::string str(entry->d_name);

        if ((entry->d_type == DT_DIR) && (str != ".") && (str != "..")) {
            printf("[%d] %s\n", i, entry->d_name);
            repository.push_back(entry->d_name);
            i++;
        }
        entry = readdir(dir);
    }

    closedir(dir);

    unsigned value_checked = 1;
    std::string value;

    cout_message("\nSelect an area to benchmark the capacity response computation time: ");
    std::getline( std::cin, value );

    if ( !value.empty() ) {
        std::istringstream stream( value );
        stream >> value_checked;
    }

    // Return the choosen directory 
    return repository[value_checked];

}

int main(int argc, char*argv[])
{
    try {

        std::string working_directory;

        if (argc > 1) {
            working_directory = std::string(argv[1]);
        } else {
          working_directory = "./data/backup";
        }

        std::string choosen_subdirectory = select_a_directory(working_directory);
        std::string path_to_data_files = working_directory + "/" + choosen_subdirectory;

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

        // Build the index to quickly map latitudes and longitudes
        RoutingKit::GeoPositionToNode map_geo_position(graph.latitude, graph.longitude);


        while(true){

            cout_message("\n\n*** Initialization of the capacity coverage assessment ***");

            // default number of unit available
            unsigned source_count = 70;
            cout_message("Number of units deployed randomly on the road graph [default = " + std::to_string(source_count) + "]: ");

            std::string input_source_count;
            std::getline( std::cin, input_source_count );
            if ( !input_source_count.empty() ) {
              std::istringstream stream( input_source_count );
              stream >> source_count;
            }

            // default threshold (in seconds) under which we want estimate the capacity coverage 
            unsigned threshold = 300;
            cout_message("Time (seconds) under which the coverage will be evaluated [default = " + std::to_string(threshold) + "]: ");

            std::string input_threshold;
            std::getline( std::cin, input_threshold );
            if ( !input_threshold.empty() ) {
                std::istringstream stream( input_threshold );
                stream >> threshold;
            }

            std::vector<unsigned> source_list(source_count);

            // Random selection of nodes as starting points for the units available
            cout_message("Random selection of positions of " + std::to_string(source_count) + " intervention units");
            for(unsigned i=0; i<source_count; ++i)
            	source_list[i] = rand() % graph.ch.node_count();

            // Compute the capacity coverage
            graph.capacity_coverage(source_list, threshold);

            cout_message("*** Start exporting the capacity coverage in a GeoJSON file ***");

            long long start_time = RoutingKit::get_micro_time();

            // construction de l'export 
            graph.export_geojson_capacity_coverage("./data/geojson/" + choosen_subdirectory + "_geojson_capacity_coverage.json");

            cout_message("GeoJSON export made in " +  microseconds_to_readable_time_cout(RoutingKit::get_micro_time() - start_time));

        }

    }catch(std::exception&err){
        std::cerr << "Stopped on exception : " << err.what() << std::endl;
        return 1;
    }

	return 0;
}


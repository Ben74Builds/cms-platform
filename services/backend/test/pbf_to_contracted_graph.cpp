/**
 * This script load a road graph from an OpenStreetMap PBF file,
 * save its properties and the contracted form for later reuse
 *
 * COMPILE AND EXECUTE
 *
 * # Compile:
 * g++ -Ilib/RoutingKit/include -Llib/RoutingKit/lib -std=c++17 ./test/pbf_to_contracted_graph.cpp -o ./bin/pbf_to_contracted_graph -lroutingkit -lprotobuf-lite -losmpbf -lz -lboost_serialization
 * 
 * # Add needed shared libraries to the environment variable LD_LIBRARY_PATH:
 * export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:./lib/RoutingKit/lib:/usr/local/lib64:/usr/local/lib
 * 
 * # Launch the generated executable
 * ./bin/pbf_to_contracted_graph ./data/pbf/andorra-latest.osm.pbf
 */

#include <sys/stat.h>

#include "../src/graph.cpp"

static std::string DEFAULT_DESTINATION_FOLDER = "./data/backup";

int findLastIndex(std::string& str, char x) 
{ 
    int index = -1; 
    for (int i = 0; i < str.length(); i++) 
        if (str[i] == x) 
            index = i; 
    return index; 
}

int main(int argc, char*argv[])
{
	// Instruction for use
	if (argc < 2) {
		std::cerr << "\nUsage: " << argv[0] << " <PBF file> <destination folder>\n\n";
		std::cerr << "\t<destination folder> is optional the default value being: " << DEFAULT_DESTINATION_FOLDER << "\n\n";
		exit(1);
	}

	try{

		std::string	pbf_file, destination_folder, destination_subfolder;
		pbf_file = argv[1];

		if (argc > 2) {
	  		destination_folder = argv[2];
		} else {
			// If no destination folder is passed binaries will be stored in subdirectory to this location
			destination_folder = DEFAULT_DESTINATION_FOLDER;
		}

		// extract a name from the given file to define the path where to store the graph
		int first = findLastIndex(pbf_file, '/');
		int last = pbf_file.find(".osm.pbf");
		destination_subfolder = destination_folder + pbf_file.substr(first,last-first);
		// remove '-latest' for the folder to create
		std::string sub = "-latest";
		std::string::size_type foundpos = destination_subfolder.find(sub);
		if ( foundpos != std::string::npos )
			destination_subfolder.erase(destination_subfolder.begin() + foundpos, destination_subfolder.begin() + foundpos + sub.length());

		// create the subdirectory if do not exist
		int result = mkdir(destination_subfolder.c_str(), 0777);

		cms::GraphCH graph;

		// Load the file in Graph instance
		graph.load_from_pbf(pbf_file);
		// Save graph properties
		graph.save_graph_to_a_binary_file("graph.dat",destination_subfolder);
		// Build the contracted graph
		graph.build_contraction_hierarchy();
		// Save the contracted form of the Graph
		graph.save_contraction_hierarchy("ch.dat",destination_subfolder);

	}catch(std::exception&err){
		std::cerr << "Stopped on exception : " << err.what() << std::endl;
		return 1;
	}

	return 0;
}


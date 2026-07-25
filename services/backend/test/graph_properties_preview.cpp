/**
 * This script load a road graph from an OpenStreetMap PBF file,
 * save its properties and the contracted form for later reuse
 *
 * COMPILE AND EXECUTE
 *
 * # Compile:
 * g++ -Ilib/RoutingKit/include -Llib/RoutingKit/lib -std=c++11 ./test/graph_properties_preview.cpp -o ./bin/graph_properties_preview -lroutingkit -lprotobuf-lite -losmpbf -lz -lboost_serialization
 * 
 * # Add needed shared libraries to the environment variable LD_LIBRARY_PATH:
 * export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:./lib/RoutingKit/lib:/usr/local/lib64:/usr/local/lib
 * 
 * # Launch the generated executable
 * ./bin/graph_properties_preview ./data/pbf/andorra-latest.osm.pbf
 */
#include "../src/graph.cpp"

void graph_properties_preview(cms::Graph &graph) {

	printf("\n*** GRAPH PROPERTIES PREVIEW:*** \n\n");

	(!graph.first_out.empty()) 			? printf("graph.first_out size: %u graph.first_out[0] : %u \n", graph.first_out.size(), graph.first_out[0]) 			: printf("graph.first_out empty!!\n");
	(!graph.head.empty()) 				? printf("graph.head size: %u graph.head[0] : %u \n", graph.head.size(), graph.head[0]) 					: printf("graph.head empty!!\n");
	(!graph.tail.empty()) 				? printf("graph.tail size: %u graph.tail[0] : %u \n", graph.tail.size(), graph.tail[0]) 					: printf("graph.tail empty!!\n");
	(!graph.way.empty()) 				? printf("graph.way size: %u graph.way[0] : %u \n", graph.way.size(), graph.way[0]) 						: printf("graph.way empty!!\n");
	(!graph.geo_distance.empty()) 		? printf("graph.geo_distance size: %u graph.geo_distance[0] : %u \n", graph.geo_distance.size(), graph.geo_distance[0]) 	: printf("graph.geo_distance empty!!\n");
	(!graph.latitude.empty()) 			? printf("graph.latitude size: %u graph.latitude[0] : %f \n", graph.latitude.size(), graph.latitude[0]) 			: printf("graph.latitude empty!!\n");
	(!graph.longitude.empty()) 			? printf("graph.longitude size: %u graph.longitude[0] : %f \n", graph.longitude.size(), graph.longitude[0]) 			: printf("graph.longitude empty!!\n");
	(!graph.travel_time.empty()) 		? printf("graph.travel_time size: %u graph.travel_time[0] : %u \n", graph.travel_time.size(), graph.travel_time[0])		: printf("graph.travel_time empty!!\n");
	(!graph.way_speed.empty()) 			? printf("graph.way_speed size: %u graph.way_speed[0] : %u \n", graph.way_speed.size(), graph.way_speed[0]) 			: printf("graph.way_speed empty!!\n");
	(!graph.way_name.empty()) 			? printf("graph.way_name size: %u graph.way_name[5] : %s \n", graph.way_name.size(), graph.way_name[5].c_str()) 			: printf("graph.way_name empty!!\n");
	(!graph.way_osmid.empty()) 			? printf("graph.way_osmid size: %u graph.way_osmid[0] : %lu \n", graph.way_osmid.size(), graph.way_osmid[0]) 		: printf("graph.way_osmid empty!!\n");
	(!graph.ways_osm.empty()) 			? printf("graph.ways_osm size: %u graph.ways_osm[0] : %lu \n", graph.ways_osm.size(), graph.ways_osm[0]) 			: printf("graph.ways_osm empty!!\n");
	(!graph.osmwayid_to_idx.empty()) 	? printf("graph.osmwayid_to_idx size: %u graph.osmwayid_to_idx[graph.ways_osm[0]] : %u \n" , graph.osmwayid_to_idx.size()
		, graph.osmwayid_to_idx[graph.ways_osm[0]]) : printf("graph.osmwayid_to_idx empty!!\n");
	(!graph.osmwayid_to_idx.empty()) 	? printf("graph.get_nodes_from_way(graph.osmwayid_to_idx[graph.way_osmid[graph.way[0]]]) : [%s] \n"
		, graph.get_nodes_from_way(graph.osmwayid_to_idx[graph.way_osmid[graph.way[0]]]).c_str()) 			: printf("graph.get_nodes_from_way empty!!\n");

	printf("Internal way identifier graph.osmwayid_to_idx[graph.way_osmid[graph.way[0]]] : %u \n", graph.osmwayid_to_idx[graph.way_osmid[graph.way[0]]]);
	printf("OSM way identifier graph.way_osmid[graph.way[0]] : %u \n", graph.way_osmid[graph.way[0]]);

	printf("\ngraph.node_count : %u \n", graph.node_count);

	printf("\n*** \n");

}	

int main(int argc, char*argv[])
{
	try{

		std::string	pbf_file, destination_folder;
		pbf_file = argv[1];

		if (argc > 2) {
	  		destination_folder = argv[2];
		} else {
			destination_folder = "./data/backup";
		}

		cms::Graph graph;
		graph.load_from_pbf(pbf_file);

		graph_properties_preview(graph);
		graph.export_graph_properties_to_csv(destination_folder);

	}catch(std::exception&err){
		std::cerr << "Stopped on exception : " << err.what() << std::endl;
		return 1;
	}

	return 0;
}


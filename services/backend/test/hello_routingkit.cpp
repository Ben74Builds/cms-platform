#include <routingkit/osm_simple.h>
#include <routingkit/contraction_hierarchy.h>
#include <routingkit/inverse_vector.h>
#include <routingkit/timer.h>
#include <routingkit/geo_position_to_node.h>
#include <iostream>
using namespace RoutingKit;
using namespace std;

int main(){
	// Load a car routing graph from OpenStreetMap-based data
	auto graph = simple_load_osm_car_routing_graph_from_pbf("./data/pbf/paris-latest.osm.pbf");
	auto tail = invert_inverse_vector(graph.first_out);

	// Build the shortest path index
	auto ch = ContractionHierarchy::build(
		graph.node_count(), 
		tail, graph.head, 
		graph.travel_time
	);

	// Build the index to quickly map latitudes and longitudes
	GeoPositionToNode map_geo_position(graph.latitude, graph.longitude);

	// Besides the CH itself we need a query object. 
	ContractionHierarchyQuery ch_query(ch);

	// Use the query object to answer queries from stdin to stdout
	float latitude, longitude;
	while(cin >> latitude >> longitude){
		unsigned node = map_geo_position.find_nearest_neighbor_within_radius(latitude, longitude, 1000).id;
		if(node == invalid_id){
			cout << "No node within 1000m from source position" << endl;
			continue;
		}


		cout << "Node "<< node << " | Latitude: "<< latitude << " ; Longitude: " << longitude << endl;

	}
}
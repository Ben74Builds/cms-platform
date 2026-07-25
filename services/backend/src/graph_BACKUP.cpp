#include <boost/archive/text_oarchive.hpp>
#include <boost/archive/text_iarchive.hpp>
#include <boost/serialization/vector.hpp>
#include <boost/serialization/utility.hpp>
#include <boost/serialization/unordered_map.hpp>
#include <boost/serialization/complex.hpp>  
#include <boost/serialization/bitset.hpp>   
#include <boost/utility/binary.hpp>

#include <routingkit/geo_position_to_node.h>
#include <routingkit/osm_profile.h>
#include <routingkit/contraction_hierarchy.h>
#include <routingkit/osm_graph_builder.h>
#include <routingkit/vector_io.h>
#include <routingkit/timer.h>
#include <routingkit/tag_map.h>
#include <routingkit/id_mapper.h>
#include <routingkit/bit_vector.h>

#include "../lib/rapidjson/include/rapidjson/writer.h"
#include "../lib/rapidjson/include/rapidjson/stringbuffer.h"

#include <sstream>
#include <bits/stdc++.h> // std::unordered_multimap
#include <iostream>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>
#include <numeric>      // std::iota
#include <unordered_map>

#include "osmpbfreader.cpp"
#include "utils.cpp"
 
namespace cms {

    class Way {
    public:
        unsigned way_idx;
        unsigned weight = 0; // either :
        unsigned geo_distance = 0;
        // unsigned response_capacity = 0;  // number of units able to be on under the defined time limit
        // unsigned immediate_response = 0; // time in seconds for a first unit arrival
        std::string geometry;
    };

	/**
	 * The <code>Graph</code> class represents a road graph
	 */
	class Graph {
	  public:
		
		// Routing graph structure defined by the RoutingKit
		RoutingKit::OSMRoutingGraph rk_graph;
		/**
		 * Set references/alias for RoutingKit::OSMRoutingGraph struct parameters to allow
		 * calls from a third-party script just with "graph.way" and not "graph.rk_graph.way"
		 * But in here we will keep rk_graph.way
		 */
		std::vector<unsigned>& first_out 				= rk_graph.first_out; 
		std::vector<unsigned>& head 					= rk_graph.head;
		std::vector<unsigned>& way 						= rk_graph.way;
		std::vector<unsigned>& geo_distance 			= rk_graph.geo_distance;
		std::vector<float>& latitude 					= rk_graph.latitude;
		std::vector<float>& longitude 					= rk_graph.longitude;
		std::vector<bool>& is_arc_antiparallel_to_way 	= rk_graph.is_arc_antiparallel_to_way;
		std::vector<unsigned>& forbidden_turn_from_arc 	= rk_graph.forbidden_turn_from_arc;
		std::vector<unsigned>& forbidden_turn_to_arc 	= rk_graph.forbidden_turn_to_arc;
		//std::vector<unsigned>& first_modelling_node 	= rk_graph.first_modelling_node;
		//std::vector<float>& modelling_node_latitude 	= rk_graph.modelling_node_latitude;
		//std::vector<float>& modelling_node_longitude 	= rk_graph.modelling_node_longitude;
		// Other non OSMRoutingGraph parameters retrieve from the RoutingKit 
		std::vector<uint32_t>travel_time;
		std::vector<uint32_t>way_speed;
		std::vector<std::string>way_name;
		std::vector<uint64_t>way_osmid;
		std::vector<unsigned>node_order;												
		std::vector<unsigned>tail;	
		unsigned node_count;																										
		unsigned arc_count;		

		unsigned road_network_length = 0;		
		unsigned rnl_not_covered = 0;
		unsigned rnl_covered_by_one_unit = 0;
		unsigned rnl_covered_by_more_than_one_unit = 0;									

		// To retrieve OSM parameters not accessible with RoutingKit we pass by another script
	    osmpbfreader::Routing opr_graph; 										
	    // OSM node, Node object:<number of units passing by, lat, lon>
		std::unordered_map<uint64_t, osmpbfreader::Node>& opr_nodes = opr_graph.nodes;
		const std::vector< std::pair<uint64_t, uint64_t> >& opr_edges = opr_graph.edges();	
	    std::vector< std::vector<uint64_t> >& opr_ways_idx = opr_graph.ways; 				
	   	std::vector<uint64_t>& ways_osm = opr_graph.ways_osm;

	    std::unordered_map<uint64_t, uint64_t> osmwayid_to_idx;

	    /**
		 * Load a backup file from in a Graph instance the backup previously backup file
		 *
		 * @param graph Graph instance in which graph properties will be loaded.
		 * @param pbf_file .osm.pbf file from where to load graph properties.
		 */
		void load_from_pbf(std::string pbf_file)
	    {

			long long start_time = RoutingKit::get_micro_time();

			auto mapping = RoutingKit::load_osm_id_mapping_from_pbf(
				pbf_file,
				nullptr,
				[&](uint64_t osm_way_id, const RoutingKit::TagMap&tags){
					return is_osm_way_used_by_cars(osm_way_id, tags, cout_message);
				},
				cout_message,
				false // all_modelling_nodes_are_routing_nodes
			);

			unsigned routing_way_count = mapping.is_routing_way.population_count();
			this->way_speed.resize(routing_way_count);
			this->way_name.resize(routing_way_count);
			this->way_osmid.resize(routing_way_count);

			this->rk_graph = RoutingKit::load_osm_routing_graph_from_pbf(
				pbf_file,
				mapping,
				[&](uint64_t osm_way_id, unsigned routing_way_id, const RoutingKit::TagMap&way_tags){
					this->way_speed[routing_way_id] = get_osm_way_speed(osm_way_id, way_tags, cout_message);
					this->way_name[routing_way_id] = get_osm_way_name(osm_way_id, way_tags, cout_message);
					this->way_osmid[routing_way_id] = osm_way_id;
					return get_osm_car_direction_category(osm_way_id, way_tags, cout_message);
				},
				nullptr,
				cout_message, 
				false, // file_is_ordered_even_though_file_header_says_that_it_is_unordered
				/****
				 * OSMRoadGeometry::uncompressed permet de charger les données des paramètres suivants :
				 *	- first_modelling_node
				 *  - modelling_node_latitude 
				 *  - modelling_node_longitude 
				 *****/
				RoutingKit::OSMRoadGeometry::none // OSMRoadGeometry geometry_to_be_extracted
			);

			this->arc_count  = this->rk_graph.arc_count();
			this->travel_time = this->geo_distance;
			// Calcul des temps de parcours des ways en secondes à la limite de vitesse
			for(unsigned a=0; a<this->arc_count; ++a){
				this->travel_time[a] *= 3600; // 18000;
				this->travel_time[a] /= this->way_speed[this->way[a]];
				//travel_time[a] /= 5;
			}
			this->tail = RoutingKit::invert_inverse_vector(this->first_out);

			this->node_count = this->rk_graph.node_count();

			long long end_time = RoutingKit::get_micro_time();

			cout_message("Graph loading for RoutingKit took " +  microseconds_to_readable_time_cout(end_time - start_time) + " microseconds.");

			start_time = RoutingKit::get_micro_time();

			osmpbfreader::read_osm_pbf(pbf_file, this->opr_graph);
		   
		    // Création d'un vecteur renvoyant le way pour un index donné
		    // map_osmid_to_idx[ways_osm[99]] = 99;
		    for (uint64_t i = 0; i < this->opr_graph.ways_osm.size(); i++){
		        this->osmwayid_to_idx[this->opr_graph.ways_osm[i]] = i;
		    }

			// PBFreader();		

			end_time = RoutingKit::get_micro_time();
			
			cout_message("Graph loading for osmpbfreader took " +  microseconds_to_readable_time_cout(end_time - start_time) + " microseconds.");

	    	cout_message("Graph full properties loaded!");

	    }

	    /**
		 * Returns a list of nodes ramdomly choose
		 *
		 * @param values Container whose values are summed.
		 * @return sum of `values`, or 0.0 if `values` is empty.
		 */
	    void load_from_binary(std::string filename)
	    {
	        // create and open an archive for input
	        std::ifstream ifs(filename, std::ios::binary);
	        boost::archive::text_iarchive ia(ifs);
	        // read class state from archive
	        ia >> *this;
	        // archive and stream closed when destructors are called

			// à déplacer où le graphe est construit
			for (unsigned i = 0; i < this->rk_graph.geo_distance.size(); ++i)
			{
				this->road_network_length += this->rk_graph.geo_distance[i];
			}
			this->rnl_not_covered = this->road_network_length;
	    }	

	    /**
		 * Export in a file the given simple property of the Graph
		 */
		template<class T>
		void export_routing_graph_element(std::string file, std::vector<T>& graph_property)
		{
		    std::ofstream output_file(file);
		    std::ostream_iterator<T> output_iterator(output_file, "\n");
		    std::copy(graph_property.begin(), graph_property.end(), output_iterator);	
		}

	    /**
		 * Export in different csv files different properties of the Graph
		 */
	    void export_graph_properties_to_csv(std::string destination_folder)
	    {

			/*** Properties from RoutingKit ***/
			export_routing_graph_element(destination_folder + "first_out.csv", rk_graph.first_out);
			export_routing_graph_element(destination_folder + "head.csv", rk_graph.head);
			export_routing_graph_element(destination_folder + "way.csv", rk_graph.way);
			export_routing_graph_element(destination_folder + "geo_distance.csv", rk_graph.geo_distance);
			export_routing_graph_element(destination_folder + "latitude.csv", rk_graph.latitude);
			export_routing_graph_element(destination_folder + "longitude.csv", rk_graph.longitude);
			export_routing_graph_element(destination_folder + "is_arc_antiparallel_to_way.csv", rk_graph.is_arc_antiparallel_to_way);
			export_routing_graph_element(destination_folder + "forbidden_turn_from_arc.csv", rk_graph.forbidden_turn_from_arc);
			export_routing_graph_element(destination_folder + "forbidden_turn_to_arc.csv", rk_graph.forbidden_turn_to_arc);
			//export_routing_graph_element(destination_folder + "first_modelling_node.csv", rk_graph.first_modelling_node);
			//export_routing_graph_element(destination_folder + "modelling_node_latitude.csv", rk_graph.modelling_node_latitude);
			//export_routing_graph_element(destination_folder + "modelling_node_longitude.csv", rk_graph.modelling_node_longitude);
			export_routing_graph_element(destination_folder + "travel_time.csv", travel_time);
			export_routing_graph_element(destination_folder + "way_speed.csv", way_speed);
			export_routing_graph_element(destination_folder + "way_name.csv", way_name);
			export_routing_graph_element(destination_folder + "way_osmid.csv", way_osmid);
			export_routing_graph_element(destination_folder + "tail.csv", tail);
			/*** Properties from osmpbfreader ***/
			//export_routing_graph_element(destination_folder + "nodes.csv", opr_graph.nodes);
			//export_routing_graph_element(destination_folder + "ways.csv", opr_graph.ways);
			//export_routing_graph_element(destination_folder + "ways_osm.csv", opr_graph.ways_osm);
			/*** Other property ***/
			//export_routing_graph_element(destination_folder + "osmwayid_to_idx.csv", this->osmwayid_to_idx);
		}

	    // Allow serialization to access non-public data members.
	    friend class boost::serialization::access;
	 
	    /**
		 * Needed for the save_graph_to_a_binary_file function
		 */
	    template<class Archive>
	    void serialize(Archive & ar, const unsigned int version)
	    {
		    // When the class Archive corresponds to an output archive, the
		    // & operator is defined similar to <<.  Likewise, when the class Archive
		    // is a type of input archive the & operator is defined similar to >>.
			ar & rk_graph.first_out;
			ar & rk_graph.head;
			ar & rk_graph.way;
			ar & rk_graph.geo_distance;
			ar & rk_graph.latitude;
			ar & rk_graph.longitude;
			ar & rk_graph.is_arc_antiparallel_to_way;
			ar & rk_graph.forbidden_turn_from_arc;
			ar & rk_graph.forbidden_turn_to_arc;
			//ar & rk_graph.first_modelling_node;
			//ar & rk_graph.modelling_node_latitude;
			//ar & rk_graph.modelling_node_longitude;
			ar & travel_time;
			ar & way_speed;
			ar & way_name;
			ar & way_osmid;
			ar & node_count;										
			ar & arc_count;
			ar & tail;			
	      	ar & opr_graph.nodes; 
	      	ar & opr_graph.ways;   
	      	ar & opr_graph.ways_osm;
	      	ar & osmwayid_to_idx;
	    }

	    /**
		 * Save the graph to a binary file
		 */
	    void save_graph_to_a_binary_file(std::string filename, const std::string& destination_folder)
	    {

	    	// Create an output archive
	      	std::ofstream ofs(destination_folder +'/'+filename, std::ios::binary);
	      	boost::archive::text_oarchive ar(ofs);
	      	// write class instance to archive
	      	ar << *this;

			cout_message("Graph saved at: " + destination_folder+'/'+filename);	
		}

	    /**
		 * Returns a string of nodes composing the given way:
		 * [[latitude,longitude],[latitude,longitude],...,[latitude,longitude]]
		 *
		 * @param values Container whose values are summed.
		 * @return sum of `values`, or 0.0 if `values` is empty.
		 */

		std::string get_nodes_from_way(uint64_t way_idx)
		{

	        std::string nodes_json_string = "";
	        for(size_t i = 0; i < opr_graph.ways[way_idx].size(); i++){

	            nodes_json_string += "[";
	            nodes_json_string += std::to_string(opr_graph.nodes[opr_graph.ways[way_idx][i]].lat_m);
	            nodes_json_string += ",";
	            nodes_json_string += std::to_string(opr_graph.nodes[opr_graph.ways[way_idx][i]].lon_m);
	            nodes_json_string += "]";
	            if(i < opr_graph.ways[way_idx].size() - 1)
	                nodes_json_string += ",";
	        }

	        return nodes_json_string;

		}





		std::vector<std::pair<double,double>> get_nodes_from_way_into_vec(uint64_t way_idx)
		{

	        std::vector<std::pair<double,double>> way_nodes;
	        for(size_t i = 0; i < opr_graph.ways[way_idx].size(); i++){

				way_nodes.push_back( std::make_pair( opr_graph.nodes[opr_graph.ways[way_idx][i]].lat_m, opr_graph.nodes[opr_graph.ways[way_idx][i]].lon_m ) );
	        }

	        return way_nodes;

		}

		double get_geo_distance_from_way(uint64_t way_idx)
		{

	        float distance = 0;
	        for(size_t i = 0; i < opr_graph.ways[way_idx].size() - 1; i++){
				distance += coordinates_to_distance( \
					opr_graph.nodes[opr_graph.ways[way_idx][i]].lat_m, \
					opr_graph.nodes[opr_graph.ways[way_idx][i]].lon_m, \
					opr_graph.nodes[opr_graph.ways[way_idx][i+1]].lat_m, \
					opr_graph.nodes[opr_graph.ways[way_idx][i+1]].lon_m \
				);
	        }
	        return distance;
		}


	    /**
		 * Returns a list of nodes ramdomly choose
		 *
		 * @param values Container whose values are summed.
		 * @return sum of `values`, or 0.0 if `values` is empty.
		 */
		std::vector<unsigned> get_X_random_nodes(unsigned number_of_nodes)
		{

			std::vector<unsigned> random_nodes_list(number_of_nodes);

			for(unsigned i=0; i < number_of_nodes; ++i)
				random_nodes_list[i] = rand() % (node_count - 1);

			return random_nodes_list;

		}

	};

	/**
	 * The <code>GraphCH</code> struct extends a Graph abilities to build and query 
	 * a contraction hierarchy
	 */
	class GraphCH : public Graph 
	{ 
	  public:
		RoutingKit::ContractionHierarchy ch;
		RoutingKit::ContractionHierarchyQuery ch_query;

		std::vector<unsigned> capacity_coverage_node;
		std::vector<unsigned> capacity_coverage_way;
		RoutingKit::BitVector node_bit_vector;
		RoutingKit::BitVector way_bit_vector;
		std::vector<unsigned> target_list;
		RoutingKit::GeoPositionToNode map_geo_position;

		GraphCH(void) :
			node_bit_vector(this->node_count)
			,way_bit_vector(this->osmwayid_to_idx.size())
			,target_list(this->rk_graph.latitude.size())
			,map_geo_position(this->rk_graph.latitude, this->rk_graph.longitude)
		{ };

	    /**
		 * Returns a list of nodes ramdomly choose
		 */
		void build_contraction_hierarchy() {

			cout_message("Building the contraction hierarchy");
			long long start_time = RoutingKit::get_micro_time();

			ch = RoutingKit::ContractionHierarchy::build(
				this->node_count, 
				this->tail, 
				this->rk_graph.head, 
				this->travel_time);

			long long end_time = RoutingKit::get_micro_time();
			cout_message("Contraction hierarchy built in " +  microseconds_to_readable_time_cout(end_time - start_time) + " microseconds.");
		}

	    /**
		 * Save a build graph contraction hierarchy.
		 * 
		 * @prerequisite build_contraction_hierarchy should have been executed first.
		 */
		void save_contraction_hierarchy(std::string ch_file, const std::string& destination_folder) {		
			
			ch.save_file(destination_folder+'/'+ch_file);
			cout_message("Contraction hierarchy saved at: " + destination_folder+'/'+ch_file);		
		}

	    /**
		 * Load a prebuild graph contraction hierarchy.
		 */
		void load_contraction_hierarchy(std::string ch_file) {		

			ch = RoutingKit::ContractionHierarchy::load_file(ch_file);
			cout_message("Contraction hierarchy loaded from: " + ch_file);		

		}

	    /**
		 * Mark all ways fully reachable (head to tail) from a given source node under a defined
		 * time threshold time threshold in way_bit_vector.
		 *
		 * @prerequisite build_contraction_hierarchy should have been executed first.
		 */
		void unit_coverage(RoutingKit::BitVector& way_bit_vector, unsigned source, unsigned threshold = 300){ 

			cout_message("Assess all reachable ways for a unit from the node: " + std::to_string(source) + " under " + std::to_string(threshold) + " seconds");

			threshold = threshold * 1000;
			// bit vector du nombre de noeuds dont le graphe est constitué

			std::iota(target_list.begin(), target_list.end(), 0); 		
			ch_query.reset().pin_targets(target_list);
			node_bit_vector.reset_all();
			way_bit_vector.reset_all();

			cout_message("graph.cpp ligne 454");
			std::vector<unsigned> distances_to_targets = ch_query.reset_source().add_source(source).run_to_pinned_targets().get_distances_to_targets();
			// assess for each node if it could be reach under the defined threshold		
			for (unsigned i = 0; i < node_count; ++i)
			{
				if (distances_to_targets[i] < threshold)
					node_bit_vector.set(i, 1);	
			}
			cout_message("graph.cpp ligne 462");
			// assess for each way if it could be reach under the defined threshold 
			// (a way is covered if both extrimity node can be reach under the defined threshold)		
			for (unsigned i = 0; i < this->rk_graph.head.size(); ++i)
			{
				if(node_bit_vector.is_set(this->rk_graph.head[i]) && node_bit_vector.is_set(this->tail[i])) {
					way_bit_vector.set(this->rk_graph.way[i], 1);
				}
			}
			cout_message("graph.cpp ligne 470");
		}

		void unit_coverage_on_nodes(RoutingKit::BitVector& node_bit_vector, unsigned source, unsigned threshold = 300){ 

			cout_message("Assess all reachable ways for a unit from the node: " + std::to_string(source) + " under " + std::to_string(threshold) + " seconds");
			cout_message("graph.cpp ligne 477");
			threshold = threshold * 1000;
			//
			cout_message("graph.cpp ligne 481");
			std::iota(target_list.begin(), target_list.end(), 0); 
			cout_message("graph.cpp ligne 483");
					
			cout_message("graph.cpp ligne 485");	
			ch_query.reset().pin_targets(target_list);
			cout_message("graph.cpp ligne 487");
			node_bit_vector.reset_all();
			cout_message("graph.cpp ligne 489");
			std::vector<unsigned> distances_to_targets = ch_query.reset_source().add_source(source).run_to_pinned_targets().get_distances_to_targets();
			// assess for each node if it could be reach under the defined threshold		
			for (unsigned i = 0; i < node_count; ++i)
			{
				if (distances_to_targets[i] < threshold)
					node_bit_vector.set(i, 1);	
			}
			cout_message("graph.cpp ligne 497");

		}

	    /**
		 * Compute for all ways the number of units able to fully cover them under a defined
		 * time threshold time threshold in way_bit_vector.
		 *
		 * @prerequisite build_contraction_hierarchy should have been executed first.
		 */
		void capacity_coverage(std::vector<unsigned>& source_list, unsigned threshold = 300){ 

			long long start_time;
			long long end_time;

			threshold = threshold * 1000;

			std::iota(target_list.begin(), target_list.end(), 0); 
			std::fill(capacity_coverage_node.begin(), capacity_coverage_node.end(), 0); 
			std::fill(capacity_coverage_way.begin(), capacity_coverage_way.end(), 0); 
			ch_query.reset().pin_targets(target_list);

			cout_message("Start computing the coverage capacity for a " + std::to_string(threshold/1000) + " seconds coverage");

			// Compute the graph nodes capacity coverage
			start_time = RoutingKit::get_micro_time();
			
			for(auto s:source_list){
				std::vector<unsigned> distances_to_targets = ch_query.reset_source().add_source(s).run_to_pinned_targets().get_distances_to_targets();
				for (unsigned i = 0; i < node_count; ++i)
				{
					if (distances_to_targets[i] < threshold)
						// increment the number units able to reach this node under the define threshold
						capacity_coverage_node[i]++;
				}
			}

			// Compute the graph ways capacity coverage
			for (unsigned i = 0; i < this->arc_count; ++i)
			{
				capacity_coverage_way[i] = (capacity_coverage_node[this->rk_graph.head[i]] + capacity_coverage_node[this->tail[i]]) / 2;
			}

			cout_message("\nLa couverture maximale d'un tronçon routier est de : ");
			cout_message(*max_element(capacity_coverage_way.begin(),capacity_coverage_way.end()) + " unité(s) (atteignable sous " + std::to_string(threshold / 1000) + " secondes à la limite de vitesse)");
			cout_message("COUVERTURE CALCULEE EN : " + microseconds_to_readable_time_cout(RoutingKit::get_micro_time() - start_time) + "\n\n");

		}
		
        /**
		* Export the capacity coverage under a GeoJSON format.
		* "id" parameter rely on the number of units able to reach the following geometries.
		*
		* Export example:
		* {
		*  	"type": "FeatureCollection",
		*  	"features": [
		*   	{
		*      		"type": "Feature",
		*      		"id": 0,
		*      		"geometry": {
		*        		"type": "MultiLineString",
		*        		"coordinates": [
		*          			[[42.5401763,1.7193809],[42.5400935,1.7193021],[42.5398745,1.7190934]],
		*          			[[42.45149,1.4498784],[...
		*         	"properties": {...},
        *	   		"title": "Example Feature"
        *		},{
      	*			"type": "Feature",
      	*			...
      	*
		* @prerequisite capacity_coverage should have been processed first.
      	*/
		void export_geojson_capacity_coverage(std::string destination_file)	{

			std::unordered_multimap<unsigned,uint64_t> capacity_coverage_way_map;
			unsigned id, number_of_units, number_of_linestrings, number_of_points, max_coverage_capacity;

			// Group ways by number of units able to reach them for the time threshold constraint
			for (uint64_t i = 0; i < this->arc_count; ++i) {
				capacity_coverage_way_map.insert(std::pair<unsigned,uint64_t>(capacity_coverage_way[i],i));
			}

			// Highest number of units a way could be reached for the set time threshold constraint
			max_coverage_capacity = *max_element(capacity_coverage_way.begin(),capacity_coverage_way.end());

		    rapidjson::StringBuffer s;
		    // For pretty printing in place 
		    // rapidjson::PrettyWriter<StringBuffer> writer(s);
		    rapidjson::Writer<rapidjson::StringBuffer> writer(s); 		    	
		    
		    writer.StartObject();               // JSON root 
		    writer.Key("type");                     // "type":"FeatureCollection",
		    writer.String("FeatureCollection");      
		    writer.Key("features");                 // "features":
		    writer.StartArray();                    // [

		    for (unsigned i = 0; i < max_coverage_capacity; i++) { // 

		        writer.StartObject();                       // {
		        writer.Key("type");                             // "type":"Feature",
		        writer.String("Feature");  
		        writer.Key("id");                               // "id":1,
		        writer.Uint(i);
		        writer.Key("geometry");                         // "geometry":{
		        writer.StartObject(); 
		        writer.Key("type");                                 // "type":"MultiLineString",
		        writer.String("MultiLineString"); 
		        writer.Key("coordinates");                          // "coordinates":
		        writer.StartArray();                                // [

		        auto its = capacity_coverage_way_map.equal_range(i);
				for (auto it = its.first; it != its.second; ++it) {

					writer.StartArray();			// [
					
					for(unsigned j = 0; j < opr_graph.ways[this->osmwayid_to_idx[this->way_osmid[this->rk_graph.way[it->second]]]].size(); j++){
						
						writer.StartArray();			// [
						// Set a 1.11cm accuracy
				    	writer.SetMaxDecimalPlaces(7); 
				    	writer.Double(opr_graph.nodes[opr_graph.ways[this->osmwayid_to_idx[this->way_osmid[this->rk_graph.way[it->second]]]][j]].lat_m);
				    	writer.Double(opr_graph.nodes[opr_graph.ways[this->osmwayid_to_idx[this->way_osmid[this->rk_graph.way[it->second]]]][j]].lon_m);

				    	writer.EndArray(); 	

				    }

				    writer.EndArray(); 					 // ]

				}

		        writer.EndArray();                                // ] // end of coordinates
		        writer.EndObject();                             // } // end of geometry
		        writer.Key("properties");                         // "properties":{
		        writer.StartObject(); 
		        writer.Key("number_of_units");
		        writer.Uint(i);
		        writer.EndObject();                             // } // end of properties  
		        writer.Key("title");                             // "title":"Road segments reachable by id number of units",
		        std::string title_value = std::to_string(i) + " units are able to reach those ways under the time constraint";
				const char * title_value_formatted = title_value.c_str();
		        writer.String(title_value_formatted);         
		        writer.EndObject();                         // }

		    }
		    
		    writer.EndArray();                      // ] // end of features
		    writer.EndObject();                     // }

		    // Output in a file
		    std::ofstream output_file_stream;
		    output_file_stream.open (destination_file);
		    output_file_stream << s.GetString();
		    output_file_stream.close();
		
			cout_message("Capacity coverage exported in the " + destination_file + " GeoJSON file");
		}


	    /**
		 * Returns a string of nodes composing the given route:
		 * [[latitude,longitude],[latitude,longitude],...,[latitude,longitude]]
		 *
		 * @param values Container whose values are summed.
		 * @return sum of `values`, or 0.0 if `values` is empty.
		 */

		std::string get_route_lat_lon_nodes(float source_lat,float source_lon,float target_lat,float target_lon)
		{
			// Build the index to quickly map latitudes and longitudes
			unsigned source = map_geo_position.find_nearest_neighbor_within_radius(source_lat, source_lon, 1000).id;
			unsigned target = map_geo_position.find_nearest_neighbor_within_radius(target_lat, target_lon, 1000).id;

			if(source == RoutingKit::invalid_id || target == RoutingKit:: invalid_id){
				std::cerr << "Unable to calculate route with source: [" << source_lat << "," << source_lon << "] and target: [" << target_lat << "," << target_lon << "]" << std::endl;
				return "";
			}
	
			// bit vector du nombre de noeuds dont le graphe est constitué		
			ch_query.reset().add_source(source).add_target(target).run();
			node_bit_vector.reset_all();
			// way_bit_vector.reset_all();
			// assess for each node if it could be reach under the defined threshold		

			auto path = ch_query.get_node_path();

			std::string route_polyline = "[";
			int i = 0;
			for(uint64_t x:path) {
				route_polyline += "[" + std::to_string(rk_graph.latitude[x]) + "," + std::to_string(rk_graph.longitude[x]) + "]";
				if(i < path.size() - 1)
					route_polyline += ",";
				i += 1;
			}
			route_polyline += "]";

			return route_polyline;

		}
	};
}
	    
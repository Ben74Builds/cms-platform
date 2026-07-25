/**
 * Batch Road Distance Computation
 *
 * Reads departure/destination coordinates from the response_metrics table,
 * computes actual road distances using the Contraction Hierarchy,
 * and updates the table with road_distance_m and road_travel_time_sec.
 *
 * Usage:
 *   ./bin/batch_road_distances <graph_path> [db_host] [db_name] [db_user] [db_password]
 *
 * Example:
 *   ./bin/batch_road_distances ./data/backup/paris localhost ems postgres postgres
 */

#include <string>
#include <sstream>
#include <iostream>
#include <vector>
#include <numeric>
#include <pqxx/pqxx>
#include "../src/graph.cpp"

static const unsigned BATCH_SIZE = 5000;

int main(int argc, char* argv[])
{
    std::string graph_path = (argc > 1) ? argv[1] : "./data/backup/paris";
    std::string db_host = (argc > 2) ? argv[2] : "127.0.0.1";
    std::string db_name = (argc > 3) ? argv[3] : "ems";
    std::string db_user = (argc > 4) ? argv[4] : "postgres";
    std::string db_password = (argc > 5) ? argv[5] : "postgres";

    std::cout << "[batch_road_distances] graph=" << graph_path
              << " db=" << db_host << "/" << db_name << std::endl;

    // Load graph and contraction hierarchy
    cms::GraphCH graph;
    std::cout << "Loading road graph..." << std::endl;
    graph.load_from_binary(graph_path + "/graph.dat");
    std::cout << "Loading contraction hierarchy..." << std::endl;
    graph.load_contraction_hierarchy(graph_path + "/ch.dat");
    graph.adjust_property_sizes();
    std::cout << "Graph loaded: " << graph.node_count << " nodes, "
              << graph.arc_count << " arcs" << std::endl;

    // Connect to PostgreSQL
    std::string conn_str = "host=" + db_host + " dbname=" + db_name
                         + " user=" + db_user + " password=" + db_password;
    pqxx::connection conn(conn_str);

    // Add road_distance_m and road_travel_time_sec columns if not present
    {
        pqxx::work txn(conn);
        try {
            txn.exec("ALTER TABLE response_metrics ADD COLUMN road_distance_m integer");
            std::cout << "Added column road_distance_m" << std::endl;
        } catch (...) {
            // Column already exists
        }
        try {
            txn.exec("ALTER TABLE response_metrics ADD COLUMN road_travel_time_sec integer");
            std::cout << "Added column road_travel_time_sec" << std::endl;
        } catch (...) {}
        txn.commit();
    }

    // Count total rows to process
    unsigned total_rows = 0;
    {
        pqxx::work txn(conn);
        auto r = txn.exec1("SELECT COUNT(*) FROM response_metrics WHERE road_distance_m IS NULL");
        total_rows = r[0].as<unsigned>();
        txn.commit();
    }
    std::cout << "Rows to process: " << total_rows << std::endl;

    if (total_rows == 0) {
        std::cout << "Nothing to do." << std::endl;
        return 0;
    }

    // Prepare CH query
    std::vector<unsigned> target_list(graph.node_count);
    std::iota(target_list.begin(), target_list.end(), 0);

    unsigned processed = 0;
    unsigned errors = 0;
    unsigned route_not_found = 0;

    while (processed < total_rows) {
        pqxx::work txn(conn);

        // Fetch a batch of rows without road distance
        auto rows = txn.exec(
            "SELECT ctid, departure_lat, departure_lon, intervention_lat, intervention_lon "
            "FROM response_metrics "
            "WHERE road_distance_m IS NULL "
            "LIMIT " + std::to_string(BATCH_SIZE)
        );

        if (rows.empty()) break;

        for (const auto& row : rows) {
            auto ctid = row[0].as<std::string>();
            float dep_lat = row[1].as<float>();
            float dep_lon = row[2].as<float>();
            float int_lat = row[3].as<float>();
            float int_lon = row[4].as<float>();

            try {
                // Find nearest graph nodes
                unsigned source = graph.map_geo_position.find_nearest_neighbor_within_radius(
                    dep_lat, dep_lon, 2000).id;
                unsigned target = graph.map_geo_position.find_nearest_neighbor_within_radius(
                    int_lat, int_lon, 2000).id;

                if (source == RoutingKit::invalid_id || target == RoutingKit::invalid_id) {
                    // No road node nearby — mark as 0 to skip in future runs
                    txn.exec(
                        "UPDATE response_metrics SET road_distance_m = 0, road_travel_time_sec = 0 "
                        "WHERE ctid = '" + ctid + "'"
                    );
                    route_not_found++;
                    continue;
                }

                // Run CH query
                graph.ch_query.reset().add_source(source).add_target(target).run();
                unsigned travel_time_ms = graph.ch_query.get_distance();

                if (travel_time_ms == RoutingKit::inf_weight) {
                    txn.exec(
                        "UPDATE response_metrics SET road_distance_m = 0, road_travel_time_sec = 0 "
                        "WHERE ctid = '" + ctid + "'"
                    );
                    route_not_found++;
                    continue;
                }

                // Get the path to compute road distance
                auto path = graph.ch_query.get_node_path();
                unsigned road_distance = 0;
                for (size_t i = 0; i + 1 < path.size(); ++i) {
                    // Find arc between path[i] and path[i+1]
                    unsigned u = path[i];
                    for (unsigned a = graph.first_out[u]; a < graph.first_out[u + 1]; ++a) {
                        if (graph.head[a] == path[i + 1]) {
                            road_distance += graph.geo_distance[a];
                            break;
                        }
                    }
                }

                unsigned travel_time_sec = travel_time_ms / 1000;

                txn.exec(
                    "UPDATE response_metrics SET road_distance_m = " + std::to_string(road_distance) +
                    ", road_travel_time_sec = " + std::to_string(travel_time_sec) +
                    " WHERE ctid = '" + ctid + "'"
                );

            } catch (std::exception& e) {
                // Mark as processed to avoid retrying
                txn.exec(
                    "UPDATE response_metrics SET road_distance_m = -1, road_travel_time_sec = -1 "
                    "WHERE ctid = '" + ctid + "'"
                );
                errors++;
            }
        }

        txn.commit();
        processed += rows.size();

        if (processed % 10000 < BATCH_SIZE) {
            float pct = 100.0f * processed / total_rows;
            std::cout << "[" << (int)pct << "%] Processed " << processed << "/" << total_rows
                      << " (errors: " << errors << ", no route: " << route_not_found << ")" << std::endl;
        }
    }

    std::cout << "\nDone! Processed " << processed << " dispatches."
              << " Errors: " << errors << ", No route: " << route_not_found << std::endl;

    // Print summary stats
    {
        pqxx::work txn(conn);
        auto r = txn.exec1(
            "SELECT "
            "  COUNT(*) as total, "
            "  ROUND(AVG(road_distance_m) FILTER (WHERE road_distance_m > 0)) as avg_dist, "
            "  ROUND(AVG(road_travel_time_sec) FILTER (WHERE road_travel_time_sec > 0)) as avg_time, "
            "  ROUND(AVG(response_time_sec) FILTER (WHERE road_distance_m > 0)) as avg_actual "
            "FROM response_metrics"
        );
        std::cout << "Total: " << r[0].as<int>()
                  << ", Avg road distance: " << r[1].as<int>() << "m"
                  << ", Avg CH travel time: " << r[2].as<int>() << "s"
                  << ", Avg actual response: " << r[3].as<int>() << "s" << std::endl;
        txn.commit();
    }

    return 0;
}

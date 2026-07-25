/**
 * GPU-Accelerated Coverage Computation
 *
 * Provides CUDA-accelerated kernels for the CMS backend's most compute-intensive
 * operations on Paris-scale graphs (300k+ nodes, 700k+ arcs):
 *
 *   1. Distance thresholding: marks reachable nodes from CH query distances
 *   2. Way coverage marking: checks head/tail reachability for all arcs in parallel
 *   3. Batch capacity: accumulates multi-source coverage counts on GPU
 *
 * All functions have CPU fallback when GPU is unavailable.
 * The C API allows linking from g++-compiled code without nvcc.
 */

#ifndef GPU_COVERAGE_H
#define GPU_COVERAGE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize GPU with graph topology data (call once after graph loading).
 * Uploads head[], tail[], way[] arrays to GPU global memory for reuse.
 *
 * @param head      Target node ID for each arc
 * @param tail      Source node ID for each arc
 * @param way       Way/segment index for each arc
 * @param arc_count Number of directed arcs
 * @param way_count Number of distinct ways/segments
 * @param node_count Number of nodes
 * @return 0 on success, -1 if no CUDA GPU available
 */
int gpu_init(const unsigned* head, const unsigned* tail, const unsigned* way,
             unsigned arc_count, unsigned way_count, unsigned node_count);

/**
 * Free all GPU resources. Call at shutdown.
 */
void gpu_cleanup(void);

/**
 * Check if GPU was successfully initialized.
 * @return 1 if GPU is ready, 0 otherwise
 */
int gpu_is_available(void);

/**
 * GPU-accelerated fused operation: threshold distances + mark covered ways.
 * Replaces two sequential CPU loops:
 *   1. for(i < node_count) if(distances[i] < threshold) node_bv.set(i)
 *   2. for(i < arc_count) if(node_bv[head[i]] && node_bv[tail[i]]) way_bv.set(way[i])
 *
 * @param distances      Distance array from CH query (node_count elements)
 * @param threshold      Reachability threshold in milliseconds
 * @param node_bv_out    Output node BitVector data (uint64_t words, ceil(node_count/64))
 * @param node_bv_words  Number of uint64_t words in node_bv_out
 * @param way_bv_out     Output way BitVector data (uint64_t words, ceil(way_count/64))
 * @param way_bv_words   Number of uint64_t words in way_bv_out
 */
void gpu_fused_coverage(const unsigned* distances, unsigned threshold,
                        uint64_t* node_bv_out, unsigned node_bv_words,
                        uint64_t* way_bv_out, unsigned way_bv_words);

/**
 * GPU-accelerated distance thresholding only (for unit_coverage_on_nodes).
 * Sets bit i in node_bv if distances[i] < threshold.
 *
 * @param distances      Distance array from CH query (node_count elements)
 * @param threshold      Reachability threshold in milliseconds
 * @param node_bv_out    Output node BitVector data
 * @param node_bv_words  Number of uint64_t words in node_bv_out
 */
void gpu_threshold_nodes(const unsigned* distances, unsigned threshold,
                         uint64_t* node_bv_out, unsigned node_bv_words);

/**
 * GPU-accelerated batch capacity coverage.
 * For each source's distance array, increments capacity_node[i] for reachable nodes.
 * Then computes way capacity as average of head/tail node capacities.
 *
 * @param distances_batch  Array of distance arrays (num_sources * node_count unsigned values, flattened)
 * @param num_sources      Number of source units
 * @param threshold        Reachability threshold in milliseconds
 * @param capacity_node    Output: per-node coverage count (node_count elements)
 * @param capacity_way     Output: per-arc coverage (arc_count elements, avg of head+tail)
 */
void gpu_batch_capacity(const unsigned* distances_batch, unsigned num_sources,
                        unsigned threshold,
                        unsigned* capacity_node, unsigned* capacity_way);

#ifdef __cplusplus
}
#endif

#endif /* GPU_COVERAGE_H */

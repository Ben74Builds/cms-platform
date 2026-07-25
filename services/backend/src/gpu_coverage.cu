/**
 * GPU-Accelerated Coverage Computation - CUDA Implementation
 *
 * Kernels for CMS backend coverage operations on Paris-scale graphs.
 * Designed for GTX 1650 SUPER (4GB VRAM, 1280 CUDA cores, Turing arch).
 *
 * Memory layout:
 *   - Graph topology (head/tail/way) persists in GPU global memory (~10MB for Paris)
 *   - Per-query data (distances, bit vectors) transferred each call (~2MB round-trip)
 *   - Total GPU memory usage: ~15MB (trivial for 4GB VRAM)
 */

#include "gpu_coverage.h"
#include <cuda_runtime.h>
#include <stdio.h>
#include <string.h>

/* =========================================================================
 * GPU State (persistent across calls)
 * ========================================================================= */

static struct {
    unsigned* d_head;
    unsigned* d_tail;
    unsigned* d_way;
    unsigned  arc_count;
    unsigned  way_count;
    unsigned  node_count;
    int       initialized;

    /* Reusable device buffers (allocated once, reused per query) */
    unsigned* d_distances;
    uint64_t* d_node_bv;
    uint64_t* d_way_bv;
    unsigned  node_bv_words;
    unsigned  way_bv_words;

    /* Batch capacity buffers */
    unsigned* d_capacity_node;
    unsigned* d_capacity_way;
} gpu_state = {0};


/* =========================================================================
 * CUDA Kernels
 * ========================================================================= */

/**
 * Kernel 1: Distance thresholding
 * For each node, set its bit in node_bv if distance < threshold.
 * One thread per node.
 */
__global__ void kernel_threshold_nodes(
    const unsigned* __restrict__ distances,
    unsigned threshold,
    uint64_t* node_bv,
    unsigned node_count)
{
    unsigned i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= node_count) return;

    if (distances[i] < threshold) {
        /* Set bit i: word = i/64, bit = i%64 */
        atomicOr((unsigned long long*)&node_bv[i >> 6], 1ULL << (i & 63));
    }
}

/**
 * Kernel 2: Way coverage marking
 * For each arc, check if both head and tail nodes are set in node_bv.
 * If so, set the corresponding way bit in way_bv.
 * One thread per arc.
 */
__global__ void kernel_mark_ways(
    const unsigned* __restrict__ head,
    const unsigned* __restrict__ tail,
    const unsigned* __restrict__ way,
    const uint64_t* __restrict__ node_bv,
    uint64_t* way_bv,
    unsigned arc_count)
{
    unsigned i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= arc_count) return;

    unsigned h = head[i];
    unsigned t = tail[i];

    /* Check if both head and tail nodes are reachable */
    int head_set = (node_bv[h >> 6] >> (h & 63)) & 1;
    int tail_set = (node_bv[t >> 6] >> (t & 63)) & 1;

    if (head_set && tail_set) {
        unsigned w = way[i];
        atomicOr((unsigned long long*)&way_bv[w >> 6], 1ULL << (w & 63));
    }
}

/**
 * Kernel 3: Batch capacity increment
 * For one source's distances, increment capacity_node[i] for all reachable nodes.
 * One thread per node.
 */
__global__ void kernel_capacity_increment(
    const unsigned* __restrict__ distances,
    unsigned threshold,
    unsigned* capacity_node,
    unsigned node_count)
{
    unsigned i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= node_count) return;

    if (distances[i] < threshold) {
        atomicAdd(&capacity_node[i], 1);
    }
}

/**
 * Kernel 4: Way capacity from node capacity
 * capacity_way[i] = (capacity_node[head[i]] + capacity_node[tail[i]]) / 2
 * One thread per arc.
 */
__global__ void kernel_capacity_ways(
    const unsigned* __restrict__ head,
    const unsigned* __restrict__ tail,
    const unsigned* __restrict__ capacity_node,
    unsigned* capacity_way,
    unsigned arc_count)
{
    unsigned i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= arc_count) return;

    capacity_way[i] = (capacity_node[head[i]] + capacity_node[tail[i]]) / 2;
}


/* =========================================================================
 * Host API Implementation
 * ========================================================================= */

#define BLOCK_SIZE 256

#define CUDA_CHECK(call) do {                                           \
    cudaError_t err = (call);                                           \
    if (err != cudaSuccess) {                                           \
        fprintf(stderr, "[GPU] CUDA error in %s: %s\n",                \
                __func__, cudaGetErrorString(err));                     \
        return;                                                         \
    }                                                                   \
} while(0)

#define CUDA_CHECK_INIT(call) do {                                      \
    cudaError_t err = (call);                                           \
    if (err != cudaSuccess) {                                           \
        fprintf(stderr, "[GPU] CUDA error in %s: %s\n",                \
                __func__, cudaGetErrorString(err));                     \
        return -1;                                                      \
    }                                                                   \
} while(0)


int gpu_init(const unsigned* head, const unsigned* tail, const unsigned* way,
             unsigned arc_count, unsigned way_count, unsigned node_count)
{
    /* Check for CUDA device */
    int device_count = 0;
    cudaError_t err = cudaGetDeviceCount(&device_count);
    if (err != cudaSuccess || device_count == 0) {
        fprintf(stderr, "[GPU] No CUDA device found, falling back to CPU\n");
        return -1;
    }

    /* Print GPU info */
    cudaDeviceProp prop;
    cudaGetDeviceProperties(&prop, 0);
    fprintf(stdout, "[GPU] Using %s (%d cores, %zu MB VRAM)\n",
            prop.name, prop.multiProcessorCount * 128, prop.totalGlobalMem / (1024*1024));

    gpu_state.arc_count = arc_count;
    gpu_state.way_count = way_count;
    gpu_state.node_count = node_count;
    gpu_state.node_bv_words = (node_count + 63) / 64;
    gpu_state.way_bv_words = (way_count + 63) / 64;

    /* Allocate and upload graph topology (persistent) */
    size_t arc_bytes = arc_count * sizeof(unsigned);
    CUDA_CHECK_INIT(cudaMalloc(&gpu_state.d_head, arc_bytes));
    CUDA_CHECK_INIT(cudaMalloc(&gpu_state.d_tail, arc_bytes));
    CUDA_CHECK_INIT(cudaMalloc(&gpu_state.d_way, arc_bytes));

    CUDA_CHECK_INIT(cudaMemcpy(gpu_state.d_head, head, arc_bytes, cudaMemcpyHostToDevice));
    CUDA_CHECK_INIT(cudaMemcpy(gpu_state.d_tail, tail, arc_bytes, cudaMemcpyHostToDevice));
    CUDA_CHECK_INIT(cudaMemcpy(gpu_state.d_way, way, arc_bytes, cudaMemcpyHostToDevice));

    /* Allocate reusable per-query buffers */
    CUDA_CHECK_INIT(cudaMalloc(&gpu_state.d_distances, node_count * sizeof(unsigned)));
    CUDA_CHECK_INIT(cudaMalloc(&gpu_state.d_node_bv, gpu_state.node_bv_words * sizeof(uint64_t)));
    CUDA_CHECK_INIT(cudaMalloc(&gpu_state.d_way_bv, gpu_state.way_bv_words * sizeof(uint64_t)));

    /* Allocate capacity buffers */
    CUDA_CHECK_INIT(cudaMalloc(&gpu_state.d_capacity_node, node_count * sizeof(unsigned)));
    CUDA_CHECK_INIT(cudaMalloc(&gpu_state.d_capacity_way, arc_count * sizeof(unsigned)));

    gpu_state.initialized = 1;

    size_t total_gpu_mem = 3 * arc_bytes                                   /* head, tail, way */
                         + node_count * sizeof(unsigned)                   /* distances */
                         + gpu_state.node_bv_words * sizeof(uint64_t)      /* node_bv */
                         + gpu_state.way_bv_words * sizeof(uint64_t)       /* way_bv */
                         + node_count * sizeof(unsigned)                   /* capacity_node */
                         + arc_count * sizeof(unsigned);                   /* capacity_way */
    fprintf(stdout, "[GPU] Initialized: %u nodes, %u arcs, %u ways (%.1f MB GPU memory)\n",
            node_count, arc_count, way_count, total_gpu_mem / (1024.0 * 1024.0));

    return 0;
}


void gpu_cleanup(void)
{
    if (!gpu_state.initialized) return;

    cudaFree(gpu_state.d_head);
    cudaFree(gpu_state.d_tail);
    cudaFree(gpu_state.d_way);
    cudaFree(gpu_state.d_distances);
    cudaFree(gpu_state.d_node_bv);
    cudaFree(gpu_state.d_way_bv);
    cudaFree(gpu_state.d_capacity_node);
    cudaFree(gpu_state.d_capacity_way);

    memset(&gpu_state, 0, sizeof(gpu_state));
    fprintf(stdout, "[GPU] Cleaned up\n");
}


int gpu_is_available(void)
{
    return gpu_state.initialized;
}


void gpu_fused_coverage(const unsigned* distances, unsigned threshold,
                        uint64_t* node_bv_out, unsigned node_bv_words,
                        uint64_t* way_bv_out, unsigned way_bv_words)
{
    if (!gpu_state.initialized) return;

    unsigned nc = gpu_state.node_count;
    unsigned ac = gpu_state.arc_count;

    /* Upload distances to GPU */
    CUDA_CHECK(cudaMemcpy(gpu_state.d_distances, distances,
                          nc * sizeof(unsigned), cudaMemcpyHostToDevice));

    /* Clear bit vectors on GPU */
    CUDA_CHECK(cudaMemset(gpu_state.d_node_bv, 0, gpu_state.node_bv_words * sizeof(uint64_t)));
    CUDA_CHECK(cudaMemset(gpu_state.d_way_bv, 0, gpu_state.way_bv_words * sizeof(uint64_t)));

    /* Kernel 1: threshold distances -> node bit vector */
    unsigned grid_nodes = (nc + BLOCK_SIZE - 1) / BLOCK_SIZE;
    kernel_threshold_nodes<<<grid_nodes, BLOCK_SIZE>>>(
        gpu_state.d_distances, threshold, gpu_state.d_node_bv, nc);

    /* Sync: kernel 2 depends on kernel 1 output */
    CUDA_CHECK(cudaDeviceSynchronize());

    /* Kernel 2: mark covered ways from node bit vector */
    unsigned grid_arcs = (ac + BLOCK_SIZE - 1) / BLOCK_SIZE;
    kernel_mark_ways<<<grid_arcs, BLOCK_SIZE>>>(
        gpu_state.d_head, gpu_state.d_tail, gpu_state.d_way,
        gpu_state.d_node_bv, gpu_state.d_way_bv, ac);

    CUDA_CHECK(cudaDeviceSynchronize());

    /* Download results to host */
    unsigned copy_node_words = (node_bv_words < gpu_state.node_bv_words) ? node_bv_words : gpu_state.node_bv_words;
    unsigned copy_way_words = (way_bv_words < gpu_state.way_bv_words) ? way_bv_words : gpu_state.way_bv_words;

    CUDA_CHECK(cudaMemcpy(node_bv_out, gpu_state.d_node_bv,
                          copy_node_words * sizeof(uint64_t), cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(way_bv_out, gpu_state.d_way_bv,
                          copy_way_words * sizeof(uint64_t), cudaMemcpyDeviceToHost));
}


void gpu_threshold_nodes(const unsigned* distances, unsigned threshold,
                         uint64_t* node_bv_out, unsigned node_bv_words)
{
    if (!gpu_state.initialized) return;

    unsigned nc = gpu_state.node_count;

    CUDA_CHECK(cudaMemcpy(gpu_state.d_distances, distances,
                          nc * sizeof(unsigned), cudaMemcpyHostToDevice));

    CUDA_CHECK(cudaMemset(gpu_state.d_node_bv, 0, gpu_state.node_bv_words * sizeof(uint64_t)));

    unsigned grid_nodes = (nc + BLOCK_SIZE - 1) / BLOCK_SIZE;
    kernel_threshold_nodes<<<grid_nodes, BLOCK_SIZE>>>(
        gpu_state.d_distances, threshold, gpu_state.d_node_bv, nc);

    CUDA_CHECK(cudaDeviceSynchronize());

    unsigned copy_words = (node_bv_words < gpu_state.node_bv_words) ? node_bv_words : gpu_state.node_bv_words;
    CUDA_CHECK(cudaMemcpy(node_bv_out, gpu_state.d_node_bv,
                          copy_words * sizeof(uint64_t), cudaMemcpyDeviceToHost));
}


void gpu_batch_capacity(const unsigned* distances_batch, unsigned num_sources,
                        unsigned threshold,
                        unsigned* capacity_node, unsigned* capacity_way)
{
    if (!gpu_state.initialized) return;

    unsigned nc = gpu_state.node_count;
    unsigned ac = gpu_state.arc_count;

    /* Clear capacity accumulators on GPU */
    CUDA_CHECK(cudaMemset(gpu_state.d_capacity_node, 0, nc * sizeof(unsigned)));

    unsigned grid_nodes = (nc + BLOCK_SIZE - 1) / BLOCK_SIZE;

    /* Process each source: upload distances, run increment kernel */
    for (unsigned s = 0; s < num_sources; ++s) {
        const unsigned* src_distances = distances_batch + (size_t)s * nc;

        CUDA_CHECK(cudaMemcpy(gpu_state.d_distances, src_distances,
                              nc * sizeof(unsigned), cudaMemcpyHostToDevice));

        kernel_capacity_increment<<<grid_nodes, BLOCK_SIZE>>>(
            gpu_state.d_distances, threshold, gpu_state.d_capacity_node, nc);
    }

    CUDA_CHECK(cudaDeviceSynchronize());

    /* Compute way capacity from node capacity */
    unsigned grid_arcs = (ac + BLOCK_SIZE - 1) / BLOCK_SIZE;
    kernel_capacity_ways<<<grid_arcs, BLOCK_SIZE>>>(
        gpu_state.d_head, gpu_state.d_tail,
        gpu_state.d_capacity_node, gpu_state.d_capacity_way, ac);

    CUDA_CHECK(cudaDeviceSynchronize());

    /* Download results */
    CUDA_CHECK(cudaMemcpy(capacity_node, gpu_state.d_capacity_node,
                          nc * sizeof(unsigned), cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(capacity_way, gpu_state.d_capacity_way,
                          ac * sizeof(unsigned), cudaMemcpyDeviceToHost));
}

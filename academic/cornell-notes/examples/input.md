# Memory Hierarchy & CPU Caches

Modern computer architectures rely on a hierarchy of memory storage systems to balance access latency, capacity, and manufacturing cost.

## Cache Organization

CPU caches sit between the processor registers and main memory (DRAM). They temporarily store frequently accessed instructions and data.

Cache hits occur when requested data resides in cache memory, resulting in sub-nanosecond to few-nanosecond access latency. Conversely, a cache miss incurs a costly trip across the memory bus to DRAM, which takes 50-100 nanoseconds.

### Cache Mapping Techniques

There are three primary cache placement policies:

- Direct Mapped: Each memory block maps to exactly one cache line. Simple and fast, but prone to conflict misses.
- Fully Associative: A memory block can be placed in any cache line. Eliminates conflict misses, but requires expensive parallel comparator hardware.
- Set Associative: A compromise where cache is divided into sets, each containing $N$ ways (e.g. 8-way set associative).

| Cache Level | Typical Size | Typical Latency | Location |
| :--- | :--- | :--- | :--- |
| L1 Cache | 32 KB - 64 KB per core | 1 - 2 ns (4-5 cycles) | On-chip (Core) |
| L2 Cache | 512 KB - 1 MB per core | 3 - 5 ns (12-14 cycles) | On-chip (Core) |
| L3 Cache | 16 MB - 64 MB shared | 10 - 20 ns (40-60 cycles) | On-chip (Shared) |
| Main DRAM | 16 GB - 128 GB | 60 - 100 ns | Off-chip DIMMs |

## Cache Locality & Performance Optimization

Software developers can dramatically improve application throughput by respecting hardware locality principles:

1. **Temporal Locality**: If a memory location is accessed once, it is likely to be accessed again in the near future (e.g., loop variables, frequently called helper functions).
2. **Spatial Locality**: If a memory location is accessed, adjacent memory locations are likely to be accessed soon (e.g., sequential array iterations).

Consider the following row-major matrix multiplication optimization in C:

```c
// Good spatial locality (row-major order in C)
for (int i = 0; i < N; i++) {
    for (int j = 0; j < N; j++) {
        sum += matrix[i][j];
    }
}
```

Traversing column-first (`matrix[j][i]`) causes stride misses on every iteration once the matrix exceeds cache size.

For further reading, see the [Computer Systems: A Programmer's Perspective Reference](https://csapp.cs.cmu.edu/).

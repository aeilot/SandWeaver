# Benchmark guidance

- Keep original observations and separate new results from historical JSON.
- Record image, workload, sample count, warmup, and timing boundaries. Compare the same environment across mechanism arms.
- Keep cold preparation, warm handoff, and end-to-end completion distinct.
- The checked-in microbenchmark is a local trusted experiment. Avoid presenting it as production isolation or end-to-end agent performance.

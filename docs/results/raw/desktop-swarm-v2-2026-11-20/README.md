# 容器桌面 swarm 与虚拟机基线的第二轮原始数据（2026-11-20）

这是 [characterization.md](../../../characterization.md) 中"第二轮：逐进程采样"一段的原始输出。宿主、镜像、轨迹（`pilot.json`）和实验网格与[第一轮](../desktop-swarm-2026-11-19/README.md)相同，所用 OSWorld 代码与第一轮是同一份检出（`osworld-commit.txt` 从第一轮复制），只是加了更细的采样。

- `swarm/n{4,8,16}-{always,freeze,freeze-reclaim}/`：[desktop-swarm.py](../../../../benchmarks/desktop-swarm.py) 的输出，`--host-interval 0.5 --process-interval 0.5`。
  - `result.json`：配置、每个实例每一步的计时、冻结、解冻和回收数据，`epoch_ns`，以及采样器自身的统计（`profiler`）。
  - `samples.jsonl.gz`：宿主每 0.5 s 一行（内存、CPU/内存/IO 的 PSI、`/proc/vmstat` 中的缺页和 refault 计数、各容器 cgroup 的 CPU、内存、`memory.stat` 计数、PSI、`io.stat`），每 30 s 一次各容器 PSS。
  - `procs.jsonl.gz`：每 0.5 s 一行，各容器内每个进程的 CPU 时间、缺页数和 RSS，由 [procs.py](../../../../sandweaver/procs.py) 采集，只记录有变化的进程。
- `phase1/<应用域>/`：[osworld-replay.py](../../../../benchmarks/osworld-replay.py) 的输出，`--sample 0.1 --guest-procs 0.25 --idle-tail 120`。
  - `result.json`：逐步数据、空闲期汇总，以及客户机时钟探测（`guest_probe_start`、`guest_probe_end`）。
  - `samples.jsonl.gz`：容器 cgroup 的 100 ms 采样。
  - `guest-procs.jsonl.gz`：客户机内每 0.25 s 的逐进程采样，第一行是 `clk_tck` 和页大小。
- 同名 `.log` 是运行日志。

`.jsonl` 文件以 gzip 压缩保存，汇总和画图脚本会自动读取 `.gz`。时间戳是采集机上的单调时钟纳秒，客户机采样用的是客户机墙钟。回放前后各做一次时钟探测，每次往返 7–35 ms，但两次得到的偏移相差 0.13–1.5 s，说明客户机时钟在回放期间有漂移；[summarize-procs.py](../../../../benchmarks/summarize-procs.py) 在两次探测之间线性插值，漂移不线性的部分仍是误差。没有收录截图（`*.png`）和 OSWorld 任务缓存。

重新生成汇总和图：

```
python3 benchmarks/summarize-desktop-swarm.py docs/results/raw/desktop-swarm-v2-2026-11-20/swarm --json
python3 benchmarks/summarize-thaw-cost.py docs/results/raw/desktop-swarm-v2-2026-11-20/swarm/n*-*/
python3 benchmarks/summarize-procs.py docs/results/raw/desktop-swarm-v2-2026-11-20/phase1/*/
python3 benchmarks/plot-desktop-swarm-v2.py docs/results/raw/desktop-swarm-v2-2026-11-20 docs/figures/desktop-swarm-v2-2026-11-20
```

三者合在一起的输出见 [desktop-swarm-v2-summary.json](../../desktop-swarm-v2-summary.json)。

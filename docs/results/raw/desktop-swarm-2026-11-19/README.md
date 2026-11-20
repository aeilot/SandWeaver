# 容器桌面 swarm 与虚拟机基线的原始数据（2026-11-19）

这是 [characterization.md](../../../characterization.md) 中"虚拟机基线，无争用"和"容器桌面 swarm"两段的原始输出，采集于 GCP `n2-highmem-4`（`sw-desktop`）。

- `swarm/n{4,8,16}-{always,freeze,freeze-reclaim}/`：[desktop-swarm.py](../../../../benchmarks/desktop-swarm.py) 的输出。
  - `result.json`：配置、镜像 ID、内核，以及每个实例每一步的计时、冻结、解冻和回收数据。
  - `samples.jsonl`：宿主每秒一行的采样（内存、PSI、CPU、各容器 cgroup，每 30 s 一次 PSS）。
  - 同名 `.log` 是运行日志。
- `phase1/<应用域>/`：[osworld-replay.py](../../../../benchmarks/osworld-replay.py) 的输出。
  - `result.json`：逐步数据和空闲期汇总。
  - `samples.jsonl`：容器 cgroup 的 100 ms 采样。
- `pilot.json`：选用的 9 条轨迹（OSWorld-Verified 中 Claude Sonnet 4.5 50 步上限的运行）。
- `osworld-commit.txt`：所用 OSWorld 代码的 commit。

时间戳是采集机上的单调时钟纳秒。路径是采集机上的路径。

没有收录每个 swarm 实例最后一张截图（`final-*.png`），它们仍在 `sw-desktop` 的磁盘上。

重新生成汇总：

```
python3 benchmarks/summarize-desktop-swarm.py docs/results/raw/desktop-swarm-2026-11-19/swarm --json
```

输出应与 [desktop-swarm-summary.json](../../desktop-swarm-summary.json) 一致。

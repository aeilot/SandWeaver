# Agent 会话资源与状态的 characterization 方案

状态：**设计提案，部分实施**。worker 侧采样器和扩展后的边界快照已实现并通过冒烟测试（见“插桩”）；已用按记录等待回放的方式完成 10 条轨迹的无 API 试点（见“无 API 试点”）。DeepSeek Flash 实时运行尚未开始，token 字段核对仍待 OpenRouter 凭据。现有真实轨迹只有 [DeepSeek Flash 观测报告](agent-observation.md) 中的 1 次运行（14.328 s 租约，6 次模型调用）。

## 为什么先做 characterization

[研究交接](handoff.md) 的核心问题是依赖恢复成本是否会改变回收决策，这一点尚无数据。已有证据也提示风险：humanize 小包挂载比离线重装只省约 166 ms，而模型等待通常为秒级；[固定容量重放](research.md#算法复现与固定容量重放) 在 2/4、4/8 无抖动场景下三种策略的恢复 P95 相同。

候选方向包括推理与 sandbox 联合调度、状态感知回收、依赖恢复、sandbox 复用完整性、云桌面的渲染和内存密度。它们依赖同一批未知量：会话各阶段占着什么资源、实际用了什么、释放后会丢掉什么、恢复要付多少。本方案用一轮插桩的真实运行同时回答这些问题，再据此选题。

## 研究问题

| RQ | 问题 | 服务的候选方向 |
|---|---|---|
| RQ1 阶段结构 | 模型等待、工具执行、用户等待的时长分布，每批工具数量，到达是否成簇 | 全部 |
| RQ2 占用与使用 | 每个阶段 sandbox 的 CPU、匿名内存、page cache、磁盘写入：占用量与实际使用量 | 联合调度、内存密度 |
| RQ3 状态依赖 | 进入模型等待时若释放 worker 会丢失的状态：后台进程、监听端口、`/tmp`、环境变量、overlay 写层大小与内容类别、依赖增量 | 状态感知回收、复用完整性 |
| RQ4 恢复成本 | 在该边界释放后恢复到可继续工作的成本：重装、重启服务、重新构建 | 依赖恢复、联合调度 |
| RQ5 GPU 侧占用 | 工具执行期间每个会话的 KV cache 占用，按 token 数乘所选模型每 token KV 字节数估算 | 联合调度 |
| RQ6 跨会话重叠 | 任务间依赖重叠（lockfile 相似度），以及写入共享缓存的比例 | 依赖缓存、复用完整性 |

RQ5 是估算值，不是推理服务端实测。OpenRouter 不暴露服务端 KV 驻留，需要自建 vLLM 或 SGLang 才能实测。

**每 token KV 字节数（估算，未经服务端验证）。** 依据官方 [DeepSeek-V4-Flash `config.json`](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash/raw/main/config.json)：43 层，单个共享 KV 头，`head_dim` 512，每层有 128 token 的滑动窗口；`compress_ratios` 中 20 层为 4、20 层为 128、3 层为 0（只有滑动窗口）；压缩比为 4 的层另有 `index_head_dim` 128 的索引键。按 vLLM 和 LMCache 使用的 fp8 KV（每维 1 字节，忽略缩放因子）计算：

- 随上下文增长的部分约为 20 × (512 + 128) / 4 + 20 × 512 / 128 ≈ 3.3 KB/token；按 bf16 计约翻倍；
- 与长度无关的滑动窗口部分约为 43 × 128 × 512 B ≈ 2.8 MB/序列。

例如 50k token 的会话约占 165 MB 加 2.8 MB。供应商实际使用的精度和缓存策略未知，结果只能作为量级参考。

## 决策图

核心图以每个模型等待边界为一个点：横轴为该次等待时长，纵轴为在此刻释放后的恢复成本（RQ4）。按 RQ3 着色为“可安全释放”和“存在活状态”。

| 观察结果 | 解读 | 后续方向 |
|---|---|---|
| 多数点远低于对角线且可安全释放 | 回收本身不是难题 | 看 RQ5；若 KV 占用远大于 sandbox 占用，转向推理与 sandbox 联合调度 |
| 大量点存在活状态 | 安全释放边界是主问题 | 状态感知回收，RQ3 的状态分类本身构成贡献 |
| 大量点接近或高于对角线 | 恢复成本足以影响决策 | 继续“恢复成本指导回收”主线 |

对角线只是直观参照。是否值得回收还取决于竞争强度，后续需用重放量化。

## 插桩

**客户端（已有）。** [trace.py](../sandweaver/trace.py) 已记录模型和工具区间，`Trace.model_usage` 已从响应中提取 prompt、completion、cache read/write token 和供应商费用。本轮只需核对 DeepSeek Flash 经 OpenRouter 时这些字段是否非空；上次观测中 SDK 的 `usage_to_metrics` 为空。

**Worker 侧采样器（已实现，未经大规模运行）。**

- [sampler.py](../sandweaver/sampler.py) 在宿主机上按固定周期读取 worker 容器 cgroup v2 的 `cpu.stat`、`memory.current`、`memory.stat`（anon、file、shmem）和 `io.stat`。采样器不进入租约，不会在待释放状态里留下进程或文件。
- 粒度是 worker 容器的 cgroup，不是租约。当前租约只是 worker 内的 PID 和 mount namespace，没有独立 cgroup；一个 worker 同一时刻只承载一个租约，因此容器 cgroup 近似租约，但同时计入 worker 自身的 `sleep` 和已解压 basis 的 page cache。分析时以首条命令前的样本为基线。
- 时间戳用 `time.monotonic_ns()`，与回放和 trace 客户端在同一主机上共用时钟，无需偏移。
- 边界快照由调度器的 `inspect` 产生，现包含：租约内进程名、这些进程监听的 TCP 端口（按 socket inode 匹配 `/proc/net/tcp{,6}`）、写层文件数和字节数、两级路径前缀，以及写层字节按 `python_packages`、`node_modules`、`package_cache`、`build_output`、`tmp`、`other` 的分类。只记录路径类别与大小，不读文件内容。
- 回放脚本以 `--sample SECONDS` 开启采样，逐命令记录 CPU、I/O 增量和内存峰值，原始样本写入 `samples.jsonl`。
- 依赖增量（`pip freeze` 差异、lockfile 差异）尚未实现。

**首次试测（1 条轨迹，仅验证工具链）。** `jqlang__jq-2598` 的 DeepSeek 3.2 轨迹前 12 步，session 策略，100 ms 周期：实测平均周期 0.100 s，单次读取约 0.48 ms（约占 0.5% 个核），28 个样本无错误。worker cgroup 的 `memory.current` 约 710 MB，其中 anon 只有 0.4 到 3 MB，其余主要是 basis 的 file 页。这说明按 `memory.current` 统计的“占用”会被 page cache 主导，RQ2 必须分开报告 anon 与 file。单样本不足以支持任何分布结论。

## 无 API 试点：按记录等待回放（2026-11-15）

**方法。** 不调用在线模型。回放 10 条 SWE-bench Multilingual 上 DeepSeek 3.2（mini-swe-agent v2）的公开轨迹，覆盖 9 种语言：laravel、tokio、jq、axios、rubocop、lombok、caddy、fmt、vue、redis。每一步前按轨迹记录的模型等待时长原样休眠（`--wait-scale 1`，不设上限），session 策略全程持有租约，采样周期 100 ms。命令和顺序来自轨迹，agent 不会对环境差异做出反应。机器为 `gpu-wsl`；试点期间全量回放同时运行，命令耗时可能偏大，CPU 时间与内存受影响较小。汇总见 [characterization-pilot-results.json](../benchmarks/characterization-pilot-results.json)，由 [summarize-characterization.py](../benchmarks/summarize-characterization.py) 生成。

**采样器。** 10 次运行共 126,438 个样本，无读取错误，实测周期 0.100 s，单次读取 0.39 到 0.47 ms。

| RQ | 指标 | 结果 |
|---|---|---|
| RQ1 | 回放的等待与执行总时长 | 等待 11,105 s，执行 1,415 s，执行占 11.3% |
| RQ1 | 单次等待（725 个边界） | p50 7.9 s，p90 33.0 s，最大 189 s |
| RQ2 | 等待期间 worker CPU 利用率 | p50 0.3%，p90 0.7%，最大 1.4% |
| RQ2 | 等待期间 anon 内存峰值 | p50 2.7 MB，最大 10.5 MB |
| RQ2 | 等待期间 file 页峰值 | p50 422 MB，p90 877 MB，最大 1.32 GB |
| RQ2 | 命令期间 anon 内存峰值 | p50 2.7 MB，p90 68 MB，最大 1.58 GB |
| RQ3 | 等待开始时的租约状态 | 725 个边界中 288 个无可丢失状态，206 个仅有写层文件，231 个有活进程（其中 8 个有监听端口） |
| RQ3 | 有活进程的等待时长占比 | 5,811 s / 11,105 s（52%） |
| RQ3 | 写层大小 | p50 188 B，p90 306 MB，最大 508 MB（caddy 的 Go 模块缓存，归入 `package_cache`） |

**观察。**

- 等待期间 sandbox 几乎不用 CPU，anon 内存只有几 MB，但命令期间峰值可达 1.58 GB（MB、GB 均按 2 的幂计）。按峰值预留时，大部分租约时间里资源闲置。
- `memory.current` 主要由 basis 的 file 页构成，可回收，不能直接当作占用。
- 活进程不是少数情况：redis（`redis-server`、测试进程，端口 6379）、vue（`esbuild`、`vitest`、`node`）、axios（`node`、`tail`）、caddy（`go`）都在等待开始时留下进程。按等待时长计，超过一半的空闲时间带着活状态。
- 按“决策图”一节，这一结果支持把“状态感知回收”作为候选方向；恢复成本（RQ4）尚未测量，决策图的纵轴仍缺失。

**限制。** 10 条轨迹，同一模型提交；等待时长来自原始云端运行，不是本机推理；活进程只记录进程名，未区分仍有用的服务和遗留进程；worker cgroup 包含 worker 自身进程和 basis page cache。

**恢复成本（离线）。** 对每个边界快照，在新 worker 上从干净状态执行恢复，计时到下一条验证命令通过。恢复手段分别测：本地 wheel 或缓存重装、恢复会话私有已装目录、挂载共享只读环境、重启后台服务。这一步不进入实时路径，不影响 RQ1、RQ2 的测量。

**隐私。** 按 [相关工作与研究计划](research.md#agent-行为与前端信号) 的约定，调度轨迹默认只记录标识、阶段、耗时和计数，原始提示词、命令输出和凭据不入库。快照中的文件内容只记录路径类别与大小。

## 工作负载

- 模型：OpenRouter DeepSeek Flash（`deepseek/deepseek-v4-flash`），按仓库约定不替换。
- 约 50 个任务，三类：
  1. 真实 Python 仓库修复任务，带真实依赖，候选来源为 SWE-bench Lite；
  2. 需要常驻开发服务器的 web 任务；
  3. 需要安装、升级或回退依赖的任务。
- 外部校验：用 [FreeInference Agentic Trace](https://huggingface.co/datasets/harvardMadsys/freeinference_agentic_trace) 的请求间隔检查 RQ1 分布的代表性。用户等待无法由单 agent 任务测得，只能由该数据补充。
- 云桌面方向（渲染与编码开销、桌面内存）放到第二期，候选负载为 OSWorld 子集，不与本轮混合。

## 排期与验收

| 阶段 | 内容 | 完成标准 |
|---|---|---|
| 第 1 周 | 实现 worker 侧采样器，10 个任务试点 | 采样开销可接受；各边界快照可与客户端区间对齐；token 字段非空 |
| 第 2 周 | 扩展到约 50 个任务，离线测恢复成本 | 产出决策图、状态分类表、RQ1/RQ2/RQ5 分布，并据此选定方向 |

## 风险与限制

- SWE-bench 镜像多为 x86-64。实验机 `gpu-wsl`（WSL2 Arch Linux，x86-64，12 vCPU，约 7.9 GB 内存，有 `/dev/kvm`）已可用，并已在其上回放 SWE-bench Multilingual 轨迹（见 [SWE-bench Multilingual](swe-bench-multilingual.md)）。内存较小，大型构建任务需串行运行。
- 单模型、单 agent 框架、约 50 个任务，结论只适用于该组合。
- 模型客户端耗时含网络和 SDK，不等于服务端推理时间。
- RQ5 为估算；RQ4 的恢复成本依赖本机缓存状态，冷热缓存需分别报告。
- 本方案不评估跨租户安全隔离，复用完整性只记录可观测的残留状态。

# 运行与验证

安装和启动命令见仓库根目录 README。调度器只需要 Python 3.11+ 和可用的 Docker daemon。OpenHands 客户端使用 `.[agent]`，锁定 SDK 1.59.0，已用 Python 3.12 验证。默认镜像 `sandweaver-demo:local` 由仓库 Dockerfile 构建。示例包含一个装好 humanize 的虚拟环境 `/project/.venv`。

- 建议用专用 workspace root 并为每个任务提供自己的目录。当前运行镜像需要提供 `unshare`、`mount`、`nsenter`、`setpriv`、`chroot`、`find`、`chown` 和基础 Debian shell 工具。
- 租约内命令以 root 运行并保留文件权限相关的 capabilities，新建文件在宿主上暂时属于 root。连接关闭时调度器把它们 chown 回工作区目录的属主。会话进行中从宿主侧修改这些文件需要等会话结束。详见[信任和恢复边界](architecture.md#信任和恢复边界)。
- WSL2 上没有打开的 `wsl.exe` 会话时，发行版会被关闭，Docker 随之停止。长时间实验前保持一个会话，或调整 `.wslconfig` 的 `vmIdleTimeout`。

### 运行任务镜像时的调度器选项

`sandweaver serve` 的默认值保持原型行为。运行 SWE-bench 等任务镜像时按需打开：

| 选项 | 默认 | 用途 |
|---|---|---|
| `--workspace-mount PATH` | `/workspace` | 租约内工作区的挂载点。官方 SWE-bench 镜像用 `/testbed`。 |
| `--exec-timeout S` | 60 | 单条命令超过该时间视为卡死，淘汰 worker。长构建需要调大；需要模拟命令超时时，在命令里用 `timeout` 截断，而不是依赖这个值。 |
| `--state-size SIZE` | `512m` | 租约写层的 tmpfs 大小。`disk` 改用 Docker 匿名卷，写层不占内存，worker 删除时一并删除。 |
| `--network none\|bridge` | `none` | `bridge` 允许租约访问外网，用于下载依赖，会扩大隔离边界。 |
| `--proc` | 关 | 每个租约挂载自己的 procfs，cargo、node 和较老的 `setpriv`（如 Ubuntu 22.04 的 util-linux 2.37）需要它。`/proc/sys` 等保持只读，敏感项被遮蔽，见[信任和恢复边界](architecture.md#信任和恢复边界)。 |

### 回放公开 SWE-bench 轨迹

[replay-swebench.py](../benchmarks/replay-swebench.py) 在 SandWeaver 上按原顺序回放一条 mini-swe-agent 轨迹，不调用模型。数据目录默认是 `~/sandweaver-data`，需要包含数据集 parquet 和 `trajs/<submission>/<instance>.traj.json`，见 [SWE-bench Multilingual 回放基准](swe-bench-multilingual.md#公开轨迹样本第二轮)。脚本依赖 `pyarrow`，评分脚本还需要 `swebench`，两者都装在分析环境里，不进入调度器环境。

```bash
python benchmarks/replay-swebench.py --instance jqlang__jq-2598 --policy batch --evaluate
python benchmarks/grade-swebench.py ~/sandweaver-runs/<run-id>
```

- `--policy session` 全程持有一个租约；`batch` 每步之后归还 worker，下一步重新领用。
- 每条命令按原轨迹用 `bash -lc` 在 `/testbed` 执行，带原轨迹的环境变量和超时（默认 60 s，`--cap 0` 不截断）。
- 工作区是镜像内 `/testbed` 的 root 属主副本，和原容器一致；结束后用临时容器删除，`--keep` 保留。
- 每步记录退出码与原轨迹的对比、领用和归还耗时，以及 `inspect` 得到的租约状态。`--sample 0.1` 另在宿主机上按 100 ms 读取 worker 容器的 cgroup，逐命令记录 CPU、I/O 增量和内存峰值，原始样本写入运行目录的 `samples.jsonl`（见 [characterization 方案](characterization.md#插桩)）。最终 diff 与原轨迹提交的补丁对比，忽略子模块的 dirty 标记。`--evaluate` 在新租约中运行官方 eval 脚本，评分脚本用 SWE-bench 自带的日志解析器判定。
- `sandweaver --socket … status` 查看总量、租出和空闲数量。命令行 `run` 每次创建一个租约；需要跨多条命令保留临时状态时，使用 agent 客户端，或使用 scheduler 模块的 `connect()` 发多个 `exec`。
- `sandweaver-agent --smoke-command …` 可多次指定，用 SDK 工具接口跑固定命令，不请求模型。真实 agent 用 `--prompt`，宿主环境提供模型和密钥。状态默认写到 `~/.local/state/sandweaver`，可用 `--state-dir` 调整。
- `python tests/smoke.py` 验证实际 Docker 和 OpenHands SDK 链路。应先安装项目和 agent extra，构建示例镜像。脚本也接受已存在的同类镜像标签作为参数。

### 在专用机器上重跑全量回放

2026-11-16 的[全量回放](swe-bench-multilingual.md#全量回放全程持租与每步归还2026-11-16sandweaver-实测)在 `gpu-wsl` 上和 OSWorld 混跑，每条只跑一次，没有采样。本节是在一台专用 Linux 机器上重跑的步骤（计划，尚未执行）。

[replay-swebench-all.py](../benchmarks/replay-swebench-all.py) 用 `--variant` 给一组回放配置命名，用 `--repeats` 重复，并把 `--cap`、`--sample`、`--wait-scale`、`--wait-cap` 传给单条回放。索引按（任务、提交、策略、变体、重复序号）去重，中断后重新执行同一命令即可续跑。同一变体名若用不同参数再跑会被拒绝。每个变体用单独的运行目录，`summarize-characterization.py` 会读取目录下的全部 `result.json`。

**准备。** 需要 cgroup v2 和 Docker，Python ≥ 3.11，分析环境装 `pyarrow` 与 `swebench`（5.x）。数据目录从 `gpu-wsl` 的 `~/sandweaver-data` 整体复制，包含数据集 parquet、`trajs/` 和 `analysis/`。parquet 的 sha256 记录在 [swebench-ml-selection.json](../benchmarks/swebench-ml-selection.json)，复制后应核对。先跑 `python tests/smoke.py`，再用一条轨迹核对采样器能读到 worker 的 cgroup：

```bash
python benchmarks/replay-swebench.py --instance jqlang__jq-2598 --policy batch --evaluate --sample 0.1
```

**变体。** 建议按以下顺序串行运行，避免互相干扰：

| 变体 | 命令参数 | 次数 | 回答的问题 |
|---|---|---:|---|
| `base` | `--repeats 3 --sample 0.1` | 351 × 2 × 3 | 评分翻转和退出码分歧的方差；每条命令的 CPU 与内存 |
| `uncapped` | `--cap 0 --sample 0.1` | 351 × 2 | 去掉 60 s 截断后的真实构建时长；调度器的 `--exec-timeout` 仍为 3600 s |
| `wait` | `--wait-scale 1 --sample 0.1 --policies session` | 351 | 按记录的模型等待回放，测空闲期间占用和边界状态（RQ1–RQ3） |

```bash
python benchmarks/replay-swebench-all.py --variant base --repeats 3 --sample 0.1 --runs-dir ~/sandweaver-runs/base
python benchmarks/replay-swebench-all.py --variant uncapped --cap 0 --sample 0.1 --runs-dir ~/sandweaver-runs/uncapped
python benchmarks/replay-swebench-all.py --variant wait --wait-scale 1 --sample 0.1 --policies session --runs-dir ~/sandweaver-runs/wait
```

时长：`wait` 按 [无 API 试点](characterization.md#无-api-试点按记录等待回放2026-11-15) 的 10 条 DeepSeek 轨迹平均约 21 分钟一条（等待加执行），351 条串行约 5 天；其他模型的等待长短不同，这只是量级。`base` 和 `uncapped` 的时长没有可靠记录，先看前几十次的 `wall_s` 再估算。重复是最外层循环，中途停下时已有的结果覆盖每条轨迹各一次。

**汇总。**

```bash
python benchmarks/summarize-swebench-replay.py --index ~/sandweaver-runs/base/index.jsonl --variant base --output base-summary.json
python benchmarks/summarize-swebench-replay.py --index ~/sandweaver-runs/uncapped/index.jsonl --variant uncapped --output uncapped-summary.json
python benchmarks/summarize-characterization.py ~/sandweaver-runs/wait --output wait-summary.json --points wait-boundaries.csv
```

多次重复时，`across_repeats` 给出各项计数的最小、最大和均值，`grade_flips` 列出每个翻转出现在几次重复中，`flaky_resolution` 列出同一策略下评分不稳定的轨迹。只有在全部重复中都出现的翻转才能归因于策略。

### 按工具批次领用 worker

`sandweaver-agent --batch-leases` 为实验模式。会话连接期间持续独占工作区。首条 shell 命令领用 worker，同一轮的工具命令复用该租约。下一次模型请求前归还 worker，后续工具到达时再领用。项目文件和保存在工作区内的缓存可以随会话恢复。

使用此选项时，调用方需要确认任务在模型请求之间只依赖工作区内的文件和缓存，且没有需要保留的后台进程或未完成操作。其他任务使用默认的全会话持租。`--smoke-command` 在此模式下把每条命令视作一个批次，可用来验证工作区文件跨批次保留。

`sandweaver-agent --demand-leases` 也适用于上述任务。模型等待期间，调度器保留当前执行环境，并允许满池时等待领用的任务触发回收。若恢复先于回收，原会话继续使用当前租约。回收一旦开始，恢复需要等清理完成后重新领用。两种实验模式都持续保留工作区预留。

从仓库根目录复现机制对照。OpenHands 对照需要 `.[agent]`，使用本机模拟模型端点。Rust 对照需要预先拉取指定镜像，构建阶段使用 Cargo 离线模式。

```bash
PYTHONPATH=. python benchmarks/worker-handover-cleanup.py --rounds 30 --output /tmp/worker-handover-cleanup.json
PYTHONPATH=. python benchmarks/worker-batch-profile.py --rounds 12 --output /tmp/worker-batch-profile.json
PYTHONPATH=. python benchmarks/worker-batch-profile.py --rust-cache --image rust:1.85-slim-bookworm --rounds 12 --output /tmp/worker-rust-cache.json
PYTHONPATH=. python benchmarks/openhands-batch-leases.py --rounds 9 --output /tmp/openhands-demand-leases.json
```

指标口径和已保存样本见 [worker 复用实验](worker-reuse.md)。

### Agent 时间线

`sandweaver-agent --observe` 会在本次会话的状态目录生成 `trace.jsonl`，记录租约请求、shell 往返耗时和 SDK 事件类型。沿用原有 `--prompt` 或 `--smoke-command` 参数。轨迹使用单调时钟，不记录命令、提示词或工具输出。SDK 自身的 conversation 持久化记录仍按原行为保存。

从仓库根目录运行 `PYTHONPATH=. python benchmarks/observe-agent.py --state-dir /tmp/sandweaver-observation`，可在临时工作区完成三个固定 SDK 工具调用并保存轨迹。需要已安装 agent extra 和本地 demo 镜像。该流程验证依赖、生成小程序并执行断言，无模型请求。

在装有 matplotlib 的分析环境中运行 `python benchmarks/plot-agent-trace.py TRACE_PATH --output /tmp/agent-timeline.png` 生成时间线。租约请求包含客户端往返和任务空间准备，shell 区间包含执行及通信。轨迹从客户端打开记录文件开始，尚未覆盖 Python 启动和 SDK 导入。空白区间暂不分类，不能据此判断模型推理、CPU 空闲或后台进程是否可销毁。启用观测时，模型客户端 completion/responses 调用另记为 llm_call，包含 SDK 内部处理、网络和重试时间；它不能单独测出供应商实际推理耗时。

新轨迹还通过 `span` 关联三种补充事件：

| 事件 | 字段与计时范围 |
|---|---|
| `llm_usage` | 模型响应提供的输入、输出、缓存读取和写入 token 数，以及响应提供的美元费用。缺失字段省略，零值保留。失败请求或 SDK 重试的账单无法从该事件还原。 |
| `scheduler_timing` | `claim_ns` 包含服务端验证、等待、可能的 worker 创建和任务视图准备。`pool_wait_ns` 是其中等待池容量的条件变量耗时，含唤醒后重新拿锁的时间，不含首次拿锁或创建 worker。`exec_ns` 包含服务端 Docker 命令及其进程开销。调度器在成功返回时提供这些字段。 |
| `command_result` | 退出码及 stdout、stderr 的 UTF-8 字节数。轨迹不保存输出文本。 |
| `lease_state` | 每次归还或停放 worker 前，调度器的只读 `inspect` 记录租约 PID namespace 内除 init 外的进程名，这些进程监听的 TCP 端口，以及 OverlayFS 写层的文件数、字节数、whiteout 数、按两级路径前缀汇总的字节数（取最大的 20 项）和按内容类别（`python_packages`、`node_modules`、`package_cache`、`build_output`、`tmp`、`dev`、`other`）汇总的字节数。这些就是归还时会被销毁的状态；工作区内的文件不在写层中。只记进程名和路径前缀，不记命令行和文件内容。探测失败时返回 `inspect_failed`，不影响租约。 |

真实模型修复任务可运行 `PYTHONPATH=. python benchmarks/observe-model-agent.py --state-dir /tmp/sandweaver-deepseek-observation`。宿主环境须已安全配置 `LLM_API_KEY`，脚本固定使用 OpenRouter DeepSeek V4 Flash，最多 8 次迭代、每次 2048 输出 token、一次请求尝试，产生付费调用。此脚本不用于普通 smoke；密钥不写入代码或参数，scheduler 子进程不继承相关密钥变量。

直接使用 agent CLI 时，可设置 `--max-iterations`、`--max-output-tokens`、`--llm-attempts`；默认分别为 12、由 SDK 决定、5。`--llm-attempts 1` 表示 SDK 不重试。迭代和输出限制不是账单硬上限，使用前明确模型和任务范围。

| 现象 | 优先检查 |
|---|---|
| 找不到或无法连接 socket | 等待 scheduler 打印 Ready；核对路径、属主和本机进程访问权限 |
| 镜像找不到 | 构建默认镜像或指定本地已有的兼容镜像 |
| Worker did not start task | 看返回的启动日志，检查 Linux daemon 的 OverlayFS、namespace 支持、工具版本和工作区挂载 |
| 工作区被拒绝 | 核对解析后的实际路径，并确认没有相同或父子工作区的活跃租约 |
| Pool is full | 看现有租约是否按时归还，以及 `--max` 是否匹配并发 |
| 安装命令访问不了外网 | 当前 worker 关闭外部网络，把依赖放进构建好的镜像 |
| 临时目录空间不够 | 当前写层位于有上限的 tmpfs，持久产物应放在工作区 |

集成测试和基准会启动并删除本地 Docker 容器。先用专用目录和测试镜像运行。退出 scheduler 使用 Ctrl-C 或 SIGTERM。若出现异常退出，先识别对应实例的容器再清理。

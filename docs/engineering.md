# 工程化路线：研究方向不成立时的备选

本文是一份**设计提案**，不是已完成的工作。它回答一个问题：如果 [characterization](characterization.md) 的结果不支持任何一个研究方向，SandWeaver 能否作为一个工程项目继续，需要补什么。文中“现状”一节的每条描述都对应仓库当前代码（`b061a2e`）；“路线”一节全部是未实现的计划。

## 何时启用这条路线

研究主线的判断依据是 characterization 的决策图：横轴为模型等待时长，纵轴为在该边界释放后的恢复成本（RQ4），按 RQ3 的状态着色。目前纵轴尚未测量，因此**现在还不能下结论说研究没有机会**。

建议在以下任一情况出现时启用本路线：

- 约 50 个任务的 RQ4 测完后，绝大多数边界恢复成本远低于等待时长，且安全释放边界容易判定。此时“回收”在研究上不构成难题，但它正好说明简单策略在工程上可直接落地。
- 状态分类和恢复成本与已有工作（Sandman、Kubernetes Agent Sandbox、aShare、Aries、Crab 等，见 [相关工作](research.md#最接近的先例)）差异不足以支撑论文贡献。

两条路线不互斥：工程化补齐的 API、计量和测试同样能提高后续实验的可信度。

## 为什么作为工程项目仍有价值

以下数据来自 [无 API 试点](characterization.md#无-api-试点按记录等待回放2026-11-15)。工作负载：10 条 SWE-bench Multilingual 上 DeepSeek 3.2（mini-swe-agent v2）的公开轨迹，按记录的模型等待时长原样休眠，session 策略全程持有租约，worker cgroup 采样周期 100 ms，机器 `gpu-wsl`。限制：样本少、单模型、等待来自原始云端运行、cgroup 粒度是整个 worker 而非租约。

- **租约大部分时间闲置。** 等待 11,105 s，执行 1,415 s，执行只占 11.3%。等待期间 worker CPU 利用率 p50 为 0.3%，anon 内存峰值 p50 为 2.7 MB；命令期间 anon 峰值最高 1.58 GB。按峰值给每个 agent 固定一台沙盒，资源大多空置。
- **但不能一律释放。** 725 个等待边界中 231 个带活进程（8 个有监听端口），按时长计占等待时间的 52%。redis、vitest、esbuild、go 等进程在等待开始时仍在运行。

这两点合起来就是一个工程产品的需求：一个能在单机上多路复用 agent 沙盒、并且知道何时可以安全回收的调度器。SandWeaver 的写层丢弃、park/resume 和 `inspect` 已经覆盖了核心机制。

**定位（未经对比测试）。** 单机或少量主机、不依赖 Kubernetes 的 coding agent 沙盒池。与 Kubernetes Agent Sandbox 的 WarmPool/Claim 相比，目标场景是没有集群的本机评测、个人开发机和小型 CI 机器；候选差异是 worker 内 OverlayFS 写层的快速重置，而不是重建 Pod。两者的启动与重置延迟尚未在同一硬件上比较，不能作为卖点宣称。

## 现状盘点（已实现）

| 能力 | 实现位置 | 说明 |
|---|---|---|
| Warm worker 池，按需扩容，空闲超时回收 | [scheduler.py](../sandweaver/scheduler.py) `Pool.spawn`、`maintain` | `--min`、`--max`、`--idle-seconds` |
| 独占工作区租约 | `Pool.reserve`、`check_workspace` | 一个工作区同时只属于一个连接 |
| 每租约私有写层与 PID namespace | `START`、`RESET` 脚本 | 写层放在 tmpfs（`--state-size`）或匿名卷（`disk`） |
| 重置失败即退役 worker | `Pool.release` | fail closed，符合仓库约定 |
| Park/resume 与有上限的恢复宽限 | `Pool.park`、`acquire(resuming=True)` | 池满时可回收被 park 的 worker |
| 租约状态探测 | `inspect` 操作、`summarize_lease_state` | 进程名、监听端口、写层大小与分类，不读文件内容 |
| Worker cgroup 采样 | [sampler.py](../sandweaver/sampler.py) | 从宿主机读 cgroup v2，不进入租约 |
| OpenHands 接入 | [agent.py](../sandweaver/agent.py) | 可选依赖，调度器本身不依赖它 |
| 回放与评分工具 | [benchmarks](../benchmarks) | SWE-bench Multilingual 轨迹回放、汇总 |

## 工程差距（已对照代码核实）

1. **一个调度器只服务一个镜像。** `Pool.__init__` 只接受一个 `image`，启动时 `docker export` 成 `basis.tar`，每个新 worker 再整体解压一次（上限 900 s）。多镜像需要多个调度器实例和互不相交的工作区根。
2. **池锁内执行耗时的 Docker 操作。** `acquire` 在持有 `self.lock` 时调用 `spawn()`；`maintain` 在锁内执行 `spawn()`、`remove()`、`retire()`。大镜像解压可能持锁数分钟，期间 `status`、`release`、其他 `acquire` 全部阻塞。`acquire` 的排队上限是固定 30 s，可能短于一次 spawn。
3. **协议只在本机可用，无鉴权。** 换行分隔的 JSON，跑在权限 `0600` 的 Unix socket 上（`serve`）。操作只有 `status`、`reserve`、`claim`、`exec`、`inspect`、`park`、`release`。租约绑定在连接上，连接断开即释放。
4. **`exec` 是一次性缓冲执行。** `Pool.run` 等命令结束后整体返回 stdout/stderr，没有流式输出、交互式 shell、文件上传下载或取消。超时即退役整个 worker。
5. **租约没有资源限制。** `spawn` 的 `docker run` 未设 `--cpus`、`--memory`、`--pids-limit`；租约也没有独立 cgroup，采样只能到 worker 粒度。
6. **Worker 需要较高权限。** `docker run` 带 `--cap-add SYS_ADMIN` 和 `--security-opt seccomp=unconfined`；Docker 报告启用 AppArmor 时，再加 `--security-opt apparmor=unconfined`。README 已声明仅适用于可信本地任务，未针对恶意多租户做过验证。
7. **调度器状态只在内存中。** 租约、预留和 park 表都在 `Pool` 对象里，容器名前缀每次随机。调度器进程异常退出后，已有容器不会被接管或清理。
8. **部分参数未暴露。** `resume_grace_ms` 只能在代码里设置，`serve` 的命令行没有对应参数。
9. **测试与发布。** 只有 Docker 集成 smoke（[smoke.py](../tests/smoke.py)）和一个 mock Docker 的单元测试文件（[test_retirement.py](../tests/test_retirement.py)），仓库没有 CI 配置，未发布到包索引。
10. **可观测性。** 只有 `status` 返回 total/leased/idle 三个计数；采样结果写入 JSONL，没有指标接口。

## 路线（提案，未实现）

每个阶段都应保留仓库的两条约束：独占工作区租约，以及 worker 重置失败时 fail closed。

### 阶段 0：稳定现有内核（约 1 周）

- 把 `spawn`、`remove`、`retire` 移到锁外：锁内只做记账（预留一个“正在启动”的槽位），Docker 调用在锁外完成后再回写。验收：大镜像 spawn 期间 `status` 和 `release` 的延迟不随 spawn 时长增长。
- `acquire` 的排队上限改为可配置，并区分“池满排队”和“正在 spawn”。
- 暴露 `--resume-grace-ms`。
- 调度器启动时按固定标签（而非随机前缀）找到并清理上次遗留的容器。
- 加 GitHub Actions：无 Docker 的单元测试每次提交跑；Docker smoke 在有 Docker 的 runner 上跑。

### 阶段 1：可被其他 agent 框架使用（约 2 到 3 周）

- 在 Unix socket 协议之外提供 HTTP API（可选 TCP 监听 + token 鉴权），保留现有 JSON 操作语义并写成版本化的协议文档。
- `exec` 增加流式输出、取消和后台进程句柄；增加文件读写操作，避免 agent 侧必须通过 bind mount 访问工作区。
- 提供轻量 Python 客户端，并给 OpenHands 之外至少一个框架（如 mini-swe-agent，仓库已有其轨迹回放经验）写适配。
- 验收：用新接口重跑 SWE-bench Multilingual 回放，结果与现有 `replay-swebench.py` 的评分一致。

### 阶段 2：多镜像与资源治理（约 3 到 4 周）

- 一个调度器管理多个镜像池，按 `claim` 请求中的镜像路由，全局 worker 上限加每镜像上下限。
- basis 不再每个 worker 解压一份：在宿主机解压一次，以只读方式挂入 worker 作为 OverlayFS lower。需验证与现有写层重置和 `restore_owner` 的兼容性。
- 每个 worker 设置 CPU、内存、PID 上限；评估为每个租约建子 cgroup，使采样与计量到租约粒度。
- 用 RQ3 的状态分类做默认回收策略：无可丢失状态的 park 立即可回收；只有写层文件的按恢复成本排序；有活进程或监听端口的最后回收。策略参数和数据依据需在文档中标注出处。

### 阶段 3：运维与安全（持续）

- 调度器状态持久化（SQLite 即可），重启后接管仍在运行的 worker，或安全地全部退役。
- 提供 Prometheus 指标：池大小、排队时延、spawn/reset/reclaim 耗时、退役原因、每租约资源使用。
- 安全加固评估：最小化 capability、自定义 seccomp profile、rootless Docker，以及 gVisor 或 Kata 作为可选 runtime。在完成独立评估前，文档继续声明“未验证恶意多租户隔离”。

## 不在本路线内

- Kubernetes 支持。需要集群时，Kubernetes Agent Sandbox 是更直接的选择。
- 托管服务或多主机调度。先把单机做稳，多主机留到有实际需求时再议。
- 推理与沙盒联合调度、KV 估算等仍属研究问题，留在 [characterization](characterization.md) 和 [research](research.md)。

## 风险

- 现有数据只有 10 条轨迹，“租约大多闲置”的结论需要 50 个任务的数据确认后才适合对外表述。
- 修改池锁、basis 挂载和写层重置都属于生命周期改动，按仓库约定每次需跑 Docker 集成 smoke。
- 同类工程方案已经存在且有社区，SandWeaver 的差异点（单机、写层快速重置、状态感知回收）需要用同硬件对比数据支撑，否则难以说明为什么要用它。

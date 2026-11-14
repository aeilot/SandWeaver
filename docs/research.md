# 相关工作与研究计划

## 最接近的先例

- **Sandman** 已做 coding agent 训练和评测中的跨任务 Pod 复用。它在归还后检查状态、撤销可恢复的变化并复查，其余情况换新 Pod。论文附录的同批测试里，普通复用有 64/787 次错误评分，经检查的复用有 0/787 次。SandWeaver 的候选区别在于，从一开始把写入和任务进程限制在可丢弃的执行视图内。两者的延迟数据不可直接比较。[Sandman](https://arxiv.org/html/2610.39711v1)
- **Kubernetes Agent Sandbox** 是 sandbox 生命周期的直接系统基线。它支持常驻、有持久卷的 suspend/resume，以及通过 WarmPool/Claim 领取预热 Pod。RL 示例另有 Git 重置、进程与临时目录清理。KEDA 示例以 claim 到达率调整预热池大小。[概览](https://agent-sandbox.sigs.k8s.io/docs/) · [暂停与恢复](https://agent-sandbox.sigs.k8s.io/docs/use-cases/examples/mcp-server-sandbox/) · [RL 复用策略](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/examples/agent-sandbox-rl/docs/strategies.md) · [KEDA](https://agent-sandbox.sigs.k8s.io/docs/use-cases/examples/keda-scale-to-zero/)
- **aShare** 已明确提出跨 agent 重新分配空闲 sandbox，并用离线划分和在线延迟感知调度实现原型。全文对照见下节。[aShare](https://link.springer.com/chapter/10.1007/978-981-92-4805-6_13)
- **Aries** 实现了轨迹观测框架，按工具轨迹和计费模型估算不同保活时间下的快照与恢复成本。它把执行状态与资源分离列作未来工作。与 AgentSysBench 的对照见[下文](#agentsysbench-与-aries空转刻画和卸载成本)。[Aries §4.3、§5.3](https://arxiv.org/html/2607.29069)
- **Firepool** 主要调度 agent 和 RL 的 GPU 容量。Pod 是其执行沙盒，跨调用方可由预热 Pod 接手 GPU，原 Pod 按策略保留或淘汰。其原调用方保护、按队列扩缩容和容量预算可作为算法参照。**CAS** 已在 OpenWhisk 研究利用即将可用的容器，以及按生命周期选择新建或淘汰。通用的等待、回收与扩缩容已有先例。[Firepool §5–7、附录 A.3](https://arxiv.org/html/2611.10832) · [CAS](https://doi.org/10.1002/spe.3016)
- **SAND** 在 serverless 中用常驻应用沙箱和单独函数进程摊销启动成本。**Function REWIND** 在容器复用时恢复初始状态。[SAND](https://www.usenix.org/conference/atc18/presentation/akkus) · [Function REWIND](https://www.usenix.org/system/files/atc24-song.pdf)
- **Crab** 按 agent 轮次观察系统副作用，选择文件、进程或完整 checkpoint。**CUA-Sandbox** 则以私有状态 capsule 和共享运行时支持 computer-use 训练。二者都是状态分类和复用的重要先例。[Crab](https://arxiv.org/html/2604.28138v1) · [CUA-Sandbox](https://arxiv.org/html/2609.32750v1)
- **SpecBox** 用流式模型输出和历史轨迹提前准备环境。**DSec** 在 agent 训练中组合独立版本环境层并按需加载。**SWE-MiniSandbox** 缓存仓库和依赖环境。更早的 **Nix、SOCK、Slacker** 分别覆盖不可变包环境、包感知预热和镜像按需拉取。[SpecBox](https://arxiv.org/html/2607.23933v1) · [DSec](https://arxiv.org/html/2609.22978v1) · [SWE-MiniSandbox](https://proceedings.mlr.press/v306/yuan26l.html) · [Nix](https://edolstra.github.io/pubs/nspfssd-lisa2004-final.pdf) · [SOCK](https://www.usenix.org/conference/atc18/presentation/oakes) · [Slacker](https://www.usenix.org/conference/fast16/technical-sessions/presentation/harter)

## aShare 全文与依赖相关先例

aShare（APPT 2026，pp. 189–202）把工具与模型调用拆成显式工作流节点，调度器保存工作流状态。依赖冲突图在离线阶段分组，在线阶段对兼容计算沙盒做 first-fit + EDF，所有队列都无法满足截止时间时新建沙盒。论文描述请求前重置和新进程执行，评估聚焦资源、延迟与开销。§3.3–3.4 没有展开会话中途安装、升级后的重新分组和依赖淘汰，§5 没有系统验证跨不可信租户隔离。[aShare](https://doi.org/10.1007/978-981-92-4805-6_13)

| 工作或基线 | 策略及适用范围 |
|---|---|
| Base | 每请求独占沙盒。AgentCore、E2B 是论文讨论的系统实例。 |
| OWL / Gsight | 按性能干扰安排沙盒共置。OWL 是 aShare 实验基线，Gsight 是相关工作。[OWL](https://www.cse.ust.hk/~weiwa/papers/owl-socc2022.pdf) · [Gsight](https://sc21.supercomputing.org/proceedings/tech_paper/tech_paper_pages/pap533.html) |
| StepConf / Aquatope | 按阶段配置资源或预热。aShare 的 StepConf 对照也拆分工具与模型节点，共享限于同一 agent。Aquatope 属于相关工作。[StepConf](https://fangmingliu.github.io/files/INFOCOM22-serverless.pdf) · [Aquatope](https://people.csail.mit.edu/delimitrou/papers/2023.asplos.aquatope.pdf) |
| TrEnv-X | 清理后复用底层执行环境，切换函数专属依赖，并共享只读内存模板。它是执行环境重分配的先例。[TrEnv-X §4–5](https://arxiv.org/html/2509.09525v2) |
| SOCK / RainbowCake / DSec | 分别覆盖安装与导入缓存、按层保活和共享、独立版本环境层。coding 会话动态更新依赖后，如何将版本恢复与租约决策联动，仍需用相应负载评估。[SOCK](https://www.usenix.org/conference/atc18/presentation/oakes) · [RainbowCake](https://scholarsmine.mst.edu/comsci_facwork/1497/) · [DSec](https://arxiv.org/html/2609.22978) |
| SWE-MiniSandbox / MEnvAgent | 前者缓存已准备环境，后者用补丁适配已验证的历史环境。环境复现研究发现声明和实际安装之间的差异最大，lockfile 适合作为匹配线索，运行时变化仍需观测。[SWE-MiniSandbox](https://arxiv.org/abs/2602.11210) · [MEnvAgent](https://arxiv.org/html/2601.22859) · [环境可复现性](https://arxiv.org/html/2610.00425) |

aShare 测了摘要、SQL 问答和旅行规划。Poisson 负载以独占延迟加 5%、10%、15% 设 SLO，报告相对 Base、OWL、StepConf 平均资源节省 92.9%、35.9%、36.8%。按 AgentCore 计费估算则比同样拆分的 StepConf 贵 1.9%–5.6%。Azure 实验使用来自 72 个应用的依赖配置，仍由三种工作流提供负载。SandWeaver 的观察单位是仍会恢复的 OpenHands shell 会话，工作区独占，构建缓存可以跨 worker 保留。回收的代价会落到后续恢复请求上。

### 算法复现与固定容量重放

按论文算法 2 实现的小例子里，三个同时到达的请求在独占、FIFO 截止时间检查和 EDF 下分别用 3、2、1 个沙盒，均满足截止时间。给扩容路径加入 15 ms 启动成本后，20 ms 的紧急请求会在 35 ms 完成，超过 30 ms 截止时间。这是伪代码假设的合成检验，论文集群实验尚未复现。

另以固定容量比较 eager FIFO、aShare 启发的 EDF 和按需保留。每场景 100 个种子，每会话两批工具，首批完成后起算等待。模型参数为 reset 46 ms、准备 107 ms、每批就绪到完成预算 300 ms。EDF 放不下时按最小总超期入队，原论文在这里扩容。下表为恢复 P95（ms），仅用于说明模型内的行为。

| Worker / 会话 | 等待抖动 | FIFO | EDF | 按需 |
|---|---:|---:|---:|---:|
| 2 / 2 | 0 ms | 247 | 276 | 140 |
| 2 / 4 | 0 ms | 436 | 436 | 436 |
| 4 / 8 | 0 ms | 421 | 421 | 422 |
| 4 / 8 | 450 ms | 286 | 299 | 297 |

按需组在 2 / 2 保住 200 次原租约，2 / 4 和 4 / 8 无抖动时均未保住。这组实验的恢复时刻随各策略首批完成时间变化，隔离、依赖变化和真实 Docker 负载也未模拟，不能用于给原系统排名。[重放脚本](../benchmarks/ashare-policy-replay.py) · [结果摘要](results/ashare-policy-replay-summary.json)

## AgentSysBench 与 ARIES：空转刻画和卸载成本

两篇都已刻画 agent 沙盒的空转，并各自评估了一种释放方式。下表数字取自两篇的 arXiv HTML 版，SandWeaver 尚未复现其中任何一项。[AgentSysBench](https://arxiv.org/abs/2608.15127) · [ARIES](https://arxiv.org/html/2607.29069)

| | AgentSysBench | ARIES（SoCC '26） |
|---|---|---|
| 受控负载 | 10 个应用，含 Mini-SWE、Codex、Claude Code、WebAgent 和 GUIAgent | OpenHands、Hermes Agent、OpenClaw，运行 SWE-Bench Pro、Terminal-Bench 2 和 DeepResearch Bench |
| 生产轨迹 | 24 小时，178,799 个会话，其中 coding agent 35,037 个（§7） | 一个 8 小时工作日，100 多个沙盒的分钟级 CPU 与内存采样 |
| 空转 | coding 会话执行时间的中位数占生命周期 20%，空档多在 1–10 分钟（§7.1） | CPU 空闲超过 80%，内存空闲超过 50%（§4.3） |
| 释放方式的结果 | 模型调用超过固定阈值后卸载沙盒，下一步工具前恢复。Mini-SWE 上平均内存降 4.6×，峰值降 2.1×，延迟增加不到 0.5%（§8.3） | 每次工具调用后拆除沙盒，实例成本降 65%，快照存取使客户总成本升到常驻基线的 4.9×（§4.3） |
| 证据性质 | 受控实验，只覆盖组件间的短空档。原文未说明卸载用的是快照、swap 还是分层，也未单独报告恢复延迟 | 按 AWS Lambda MicroVM 定价对工具轨迹做解析回放，没有实测部署。理想系统省 3× 是估算 |

其他相关观察：

- AgentSysBench 的沙盒峰值内存中位数约 0.8 GB，编译和单元测试时单会话工作集可达 28 GB。论文指出这类瞬时页面无需进入 checkpoint（§4.3）。
- AgentSysBench 把终端上下文列为空转期间持有的正确性关键状态，Codex 另有文件系统改动、已装依赖和进程元数据。
- GUIAgent 的桌面沙盒占执行时间 70% 以上。两篇的生产轨迹都没有覆盖桌面类负载。
- ARIES §5.3 把执行状态与资源分离列为未解问题：哪些状态必须驻留，哪些可以外置或重建，以及调整、挂起和迁移时如何保持一致。

### 对 SandWeaver 的含义

以下是据此修正的研究定位，均为待验证的判断。

- **场景。** 主线收在云上交互式 coding agent。沙盒在模型调用期间空转，SandWeaver 用 worker 池循环接力，交接路径不做 checkpoint 与 resume。四项研究问题不变，见[执行容量与依赖管理](lease-and-dependencies.md#四项研究问题)。
- **空转本身已有刻画。** 两篇和 FreeInference 轨迹已覆盖空转比例与空档分布，SandWeaver 引用这些结果，不把它列为贡献。
- **“恢复太慢”需要重新立论。** AgentSysBench 报告的卸载延迟开销不到 0.5%，ARIES 的 4.9× 是定价模型下的费用。池循环相对卸载的候选优势有三点：交接时没有快照写入和存储成本，worker 可以跨会话共享，以及峰值内存。三点都需要在同一负载上实测对照。
- **候选贡献是回答 ARIES §5.3 的问题。** 在真实轨迹上测每个批次边界留下的写层文件和进程，后续批次实际读取了多少，并据此区分可丢弃、可重建和必须驻留的状态。已有的 `lease_state` 探测只记录归还时的状态量，后续读取尚未测量。
- **常驻 shell 是待解决的状态。** 当前 `exec` 每条命令新开 shell，当前目录和环境变量不延续，与 mini-swe-agent 一致。Codex、Claude Code 这类 harness 使用常驻 shell，放弃 resume 后需要显式记录并重建终端上下文，或保留原租约。
- **云电脑作为边界负载。** 桌面和浏览器的状态主要在进程内存，沙盒在会话中的空转也更少。它是独立的新问题，本项目先把它放进刻画实验作对照，用来界定池循环的适用范围。

### 复现顺序

1. 复现 AgentSysBench 的模型调用期间卸载，扩展到构建密集、带后台服务和常驻 shell 的任务，检验低延迟开销是否仍成立，并补测捕获成本与峰值内存。
2. 用本项目的轨迹复现 ARIES 的保活时间成本回放，加入采用实测交接成本的池循环。
3. 做状态活性刻画，负载包括 coding、浏览器和桌面操作、带常驻服务的开发任务。

## 主线：何时准备环境，何时扩池和缩池

在同等资源预算下，coding agent 按工具批次复用 worker 能否正确恢复工作？集中恢复时，保留原租约、等待即将释放的 worker、回收其他等待会话的 worker，以及扩容，分别在什么条件下能提高吞吐或降低尾延迟？跨会话复用已有直接先例。候选贡献是量化亚秒级恢复竞争下，工作区与构建缓存的恢复成本怎样改变这些决策，并实现可验证的调度策略。

当前实现是可比较的基线。启动时导出单一镜像的基础文件树，预热到 `--min`；请求到达时若没有空闲 worker，就按需创建，最多到 `--max`；超过下限的 worker 空闲达到 `--idle-seconds` 后回收。下面的分阶段准备和自适应容量策略是待验证的设计。

### 下一轮调度策略与评估

现有按需策略在满池时回收最早标记的 worker。150 ms 等待场景的 9 轮中有 3 轮发生第二次回收。第一组新对照固定容量，比较当前策略、优先保护已就绪的原会话，以及额外给恢复请求有界等待的版本。调度器比较已开始 reset 或启动的容量、队首等待时间、近期启动与换绑耗时。等待超过上限后重新决策，给新任务保留公平机会。剩余模型等待时长只作为后续预测输入，提前知道实际等待的策略只能作为理想上界。[当前实测](worker-reuse.md#openhands-租约策略对照)

随后在同等 CPU、内存与存储预算下比较扩缩容。队列持续积压且预计新 worker 能在积压消化前就绪时扩池。把启动中和回收中的 worker 计入未来容量，避免重复扩容。超出热池下限的 worker 持续空闲后缩池。先验证单租约 worker 的排空与缩池；同一个 worker 同时运行多个活跃租约需要另测资源竞争和隔离。按 agent 特征选策略时，先用已完成工具批次、等待历史、环境兼容性和已测缓存恢复成本。

逐步提高到达率、会话数和恢复集中度，固定同一批真实工具轨迹。记录成功完成的任务数、吞吐、队列和会话 P95、worker-seconds、CPU、内存、磁盘 I/O 与 inode。另用真实 `sandboxd` 做同步恢复/错峰恢复与连接复用/新建连接的交叉对照，拆出 TCP 建连、RPC 首响应和进程启动。Rust 库改动、缓存淘汰和后台进程恢复各有独立对照。下载动态归还也需用修正后的原子发布路径重测。

外部比较使用同一 OpenHands 轨迹，对照 Kubernetes Agent Sandbox 的常驻与持久卷 suspend/resume，并另测 WarmPool 新会话供给。统一计到首条验证命令完成，同时记录 Claim Ready 和补池占用。先前本机 Kubernetes API 拒绝连接，暂无实测。跨租户隔离及干净 microVM 模板启动单独验证。[官方性能口径](https://agent-sandbox.sigs.k8s.io/docs/performance-assessment/)

| 动作 | 提前做什么 | 候选触发时机 |
|---|---|---|
| Prefetch | 拉取镜像层或依赖包到本地缓存 | 已知仓库或候选环境，但离执行还远，或者执行意图尚不明确 |
| Preload | 解包或组装可复用的只读环境 | 环境版本和依赖已明确，预计按需准备会进入请求的关键路径 |
| Prewarm | 启动 worker 并装载基础环境，使其可以接受租约 | 预计请求会在启动耗时内到达，且届时可用 worker 不足 |
| 扩池 / 缩池 | 增加 worker，或回收空闲 worker 并按预算保留本地环境 | 根据排队、即将归还的租约和准备中的容量扩池；根据空闲时长、预期回访和重新准备的代价缩池 |

## 第一轮实验

### Agent 行为与前端信号

先采集会话阶段、工具执行和后端资源的关联轨迹，再比较调度策略。客户端默认全会话持租，可选按批次或按需归还。OpenHands 模型请求边界已用于触发归还或标记可回收。模型客户端的 `llm_call` 计时包含网络和 SDK 内部重试。

| 信号 | 来源和可信程度 | 可验证的用途 |
|---|---|---|
| 工具已提交、执行开始、完成、失败 | 工具执行入口的观测事实 | 分离排队和执行时间，统计下一次工具到达间隔 |
| 模型请求开始、结束、重试 | 已记录模型请求区间，单次请求内部重试仍需拆分 | 测量环境准备可重叠的窗口 |
| 等待用户、审批、取消、会话结束 | 前端或编排器显式事件 | 估计需求空档，取消尚未使用的准备 |
| 环境版本、仓库与依赖清单指纹 | 工具参数和工作区解析，需版本绑定 | 环境匹配、缓存有效性和依赖预取 |
| 必须保留后台服务、终端或私有写层 | 工具协议声明，并由运行时核对 | 约束可回收的资源，信息缺失时保守保留 |
| 下一工具或所需环境的预测 | 前端计划、流式输出或历史模型，属于提示 | 预算内预取和预热，记录预测落空成本 |
| syscall 等待、CPU、内存、队列深度 | 后端观测，尚未接入 | 判断拥塞和资源占用，核对前端阶段与实际执行 |

事件至少关联 session、tool call、lease 和环境版本，记录发生时刻与调度器收到时刻。前端事件可能延迟、重复或乱序，不能仅凭“模型正在推理”或“没有工具执行”就判断后台进程可销毁。观测日志默认只记录标识、阶段、耗时和计数，原始提示词、命令、凭据和工具输出不进入调度轨迹。

第一批真实任务覆盖首次装依赖、重复测试、常驻开发服务器和多轮改错。先测租约持有时间中执行、I/O 等待和工具间隙的占比，再测哪些空档同时遇到其他可运行任务排队。为验证前端信号的增量价值，固定底层机制和资源预算，比较仅用后端指标、增加已确认前端事件、再增加预测提示三组。预测只能使用当时已到达的信息，真实 I/O 时长只能作为事后标签。轨迹重放验证资源调度，再用实时 agent 任务核验完成时间、成功率和状态连续性。

1. 先测量下载、解包、worker 启动、租约交接和首条命令各阶段的耗时，区分冷缓存和热缓存。用当前策略作基线，固定归还机制，避免把 worker 复用的收益计入准备策略。
2. 用相同镜像、到达轨迹和资源上限重放稳定流量、突发流量和突发后的空档。先在固定的扩缩池策略下比较按需准备、prefetch、prefetch + preload、再加 prewarm；再固定准备策略，比较固定下限和空闲超时与基于队列和短期需求的扩缩池。
3. 逐步改变提前量，加入预测落空、环境变更和短时间回访。记录 P95 排队与首条有用结果耗时、准备命中率、未被使用的准备工作、回收后重新创建次数，以及 CPU、内存占用时间、磁盘和 I/O。所有提前准备的开销都计入预算。

运行中才发现的下载可以作为独立的 I/O 步骤。执行步骤正常结束后归还租约，下载完成后再申请 worker，只通过工作区或显式产物传递状态。需要沿用进程或私有写层的命令继续持有租约。第一组[本地对照](experiments.md#下载期间归还租约的对照)固定池容量，先测归还租约能否减少另一项任务的等待，再考虑用下载完成时间触发预热。

第一轮使用按需启动的 I/O 池。本地 TCP 对照中，提前启动 I/O 线程并建立连接没有观察到明确收益。

交接正确性是这些实验的前置条件。用覆盖基础文件、修改依赖和启动后台服务的任务验证，确保后续任务的结果与干净环境一致。热镜像重建和当前 worker 复用可以另作机制对照。只有尾延迟收益在计入提前准备的开销和预测落空后仍然存在，才值得继续做更复杂的预测策略。

## FreeInference 生产轨迹对照

Harvard MaDSys 的 [FreeInference Agentic Trace](https://huggingface.co/datasets/harvardMadsys/freeinference_agentic_trace) 公开了 16 周约 1.2 万个会话。公开的 `requests` 表提供请求起止时间、触发类型以及输入、输出和缓存读取 token。可按模型和 harness 分层对照请求规模与会话节奏。工具延迟来自网关观察到的请求间隔，包含工具之外的客户端活动。该数据没有 SandWeaver 的 worker、租约或独立验收信息，不能直接测出可归还时长或调度收益。

首轮只读取 [2026-08-30 周的 requests 预览](https://datasets-server.huggingface.co/first-rows?dataset=harvardMadsys%2Ffreeinference_agentic_trace&config=requests&split=week_2026_08_30) 来确认字段。该接口返回 2 个会话中的 13 条请求，输入和输出的中位数分别是 51,480 和 258 token，缓存读取占输入 token 总量的 79.7%。这些是预览样本统计，不能代表该周或全量分布。原始预览留在仓库外。

[Harvard 的生产轨迹分析](https://systems.seas.harvard.edu/blog/agentic-traces-freeinference/) 报告，用户等待平均占会话时长的 50.3%，工具间隔占 21.7%。后续可按 `step_trigger` 区分用户等待和工具相关等待，把请求时间和间隔作为调度重放的输入。对重放里的后台进程、私有写层和可恢复边界单独设定假设，并用本地任务核验。论文里的模型成本是按参考价格估算，和本地 trace 中供应商返回的费用分开报告。

## 可延伸问题

- **提取最小可复用状态。** 把任务运行后产生的依赖或构建产物显式验证为只读增量，保留工作区和私有数据于各自会话。当前没有自动提取或跨会话发布任务写层。
- **有限磁盘预算的工具架。** 在同一预算比较缓存下载包、已安装工具链和完整环境。当 lockfile 或分支改变时验证有效性。先测纯按需和简单缓存，再判断预算预取是否有净收益。
- **按需释放和恢复语义。** 对可重启服务保存明确配置和可检查的恢复条件；交互调试器或未知进程保持原租约。环境变化后可用工具结果的环境版本来标识历史证据，避免复用过时结论。
- **规模化实现。** 去掉逐 worker 的 rootfs 解包，测试共享只读基础树。把创建和回收移出池锁，增加环境匹配、请求与租约指标、公平排队、重启清理。安全隔离与真实模型正确性分别验证。

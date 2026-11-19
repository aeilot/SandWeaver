# 相关工作与研究计划

## 相关工作矩阵（2026-11-15 核对）

本节按机制统一整理与"空闲沙盒怎么处理"相关的工作，用来检查候选方向是否已被覆盖。核对程度分三档：**全文**为读过正文相关章节，**摘要**为只读过摘要或项目页，**未复核**为依据已知文献、本轮没有重新打开原文。下文各节的旧条目保留，细节以本节为准。

### Agent 沙盒

| 工作 | 场景 | 何时动作 | 处理的状态 | 机制 | 证据 | 核对 |
|---|---|---|---|---|---|---|
| [AgentSysBench](https://arxiv.org/abs/2608.15127) | 10 种 agent 应用的刻画，含生产轨迹 | 模型调用时长超过固定阈值 | 整个沙盒 | 卸载后在下一步工具前恢复，原文未说明卸载手段 | Mini-SWE 受控实验：平均内存降 4.6×，峰值降 2.1×，延迟增加不到 0.5%（§8.3） | 全文 |
| [ARIES](https://arxiv.org/html/2607.29069)（SoCC '26） | 工具轨迹的成本分析 | 每次工具调用后 | 整个沙盒 | 拆除加快照 | 按 AWS 定价解析回放：总成本为常驻的 4.9×；把状态与资源分离列为未解问题（§5.3） | 全文 |
| [Crab](https://arxiv.org/abs/2604.28138) | coding 与 shell 类 agent 的容错和回滚 | 每轮结束，C/R 与 LLM 等待重叠 | 按 eBPF 观察到的每轮 OS 副作用分级：文件、进程或完整 checkpoint | 宿主侧运行时，不改 agent 和 C/R 后端 | 超过 75% 的轮次没有恢复相关状态；恢复正确率从 8% 升到 100%，checkpoint 流量最多降 87%，执行时间开销 1.9% | 摘要 |
| [DeltaBox](https://arxiv.org/abs/2605.22781) | 树搜索和 RL 的高频回滚 | 任意 checkpoint | 文件系统加进程 | 分层 CoW 文件系统，增量进程 dump，从冻结的模板进程 fork | SWE-bench 与微基准：checkpoint 14 ms，rollback 5 ms | 摘要 |
| [AgentCgroup](https://arxiv.org/abs/2602.09345) | 144 个 SWE-rebench 任务的 OS 资源刻画 | 每次工具调用 | 内存和 CPU 资源，不涉及状态 | 每次工具调用一个子 cgroup，eBPF 节流，压力过大时 `cgroup.freeze` | 内存峰均比最高 15.4×；按峰值设 `memory.max` 最多浪费 93%；初步回放中高优先级 P95 降 29% | 全文 |
| [CUA-Sandbox](https://arxiv.org/abs/2609.32750) | 计算机使用 agent 的 RL rollout | 每次 rollout，以及 reset 和 branch | 私有状态 capsule，运行时共享 | 按状态范围执行，生命周期操作带事务语义 | 相对 Docker：吞吐最高 6.2×，每环境内存降 9.2× | 摘要 |
| [Sandman](https://arxiv.org/html/2610.39711v1) | 训练与评测时跨任务复用 Pod | 归还后 | 归还后检查残留状态，能撤销的撤销 | 撤销后复查，失败就换新 Pod | 错误评分从 64/787 降到 0/787 | 全文（旧条目） |
| [aShare](https://doi.org/10.1007/978-981-92-4805-6_13) | 工作流 agent | 节点之间 | 无状态节点 | 离线按依赖划分，在线 EDF 分配沙盒 | 资源最多节省 92.9% | 全文（旧条目） |
| [TrEnv / TrEnv-X](https://arxiv.org/html/2509.09525v2) | serverless 和 agent | 函数切换时 | 清掉上一次调用的写层，换绑依赖 | 共享只读内存模板 mm-template，CXL 或 RDMA 按需取页，可用 microVM | 已扩展到浏览器类 agent | 全文（旧条目） |
| [E2B](https://docs.e2b.dev/sandbox/persistence)、[K8s Agent Sandbox](https://agent-sandbox.sigs.k8s.io/docs/) | 产品与基线 | 用户或 API 触发 | E2B 默认连内存一起保存，也可只存文件系统；K8s 用持久卷 suspend | 快照或暂停 | 产品文档 | 文档 |

### Serverless 的保活、快照与内存回收

| 工作 | 要点 | 核对 |
|---|---|---|
| Serverless in the Wild（ATC '20） | 按函数调用间隔的直方图决定预热和保活时长 | 未复核 |
| [FaaSMem](https://mivenhan.github.io/publication/2024faasmem/2024faasmem.pdf)（ASPLOS '24） | 保活阶段按内存段分别卸载到远端内存池，加"半热"阶段；本地内存降 9.9%–79.8%，部署密度提高到 108%–218% | 摘要 |
| [Desiccant](https://ipads.se.sjtu.edu.cn/_media/publications/zhao-eurosys24.pdf)（EuroSys '24） | 回收冻结函数实例里 JVM 和 Node 运行时的"冻结垃圾"；内存最多降 6.72× | 摘要 |
| [Squeezy](https://arxiv.org/abs/2411.12893) | 为 serverless 回收 VM 内存，亚秒级回收数 GiB | 摘要 |
| [CXLfork](https://tianyin.github.io/pub/cxlfork.pdf)（ASPLOS '25） | 经 CXL 远程 fork 进程，状态在集群内去重；恢复接近本地 fork，本地内存降 87% | 摘要 |
| REAP（ASPLOS '21）、FaaSnap（EuroSys '22）、Catalyzer（ASPLOS '20）、Medes（EuroSys '22） | 快照恢复时预取工作集、从快照启动、跨实例去重 | 未复核 |
| TPP、Pond（ASPLOS '23） | 透明内存分层和 CXL 内存池 | 未复核 |

### 推理侧在工具调用期间的处理

| 工作 | 要点 | 核对 |
|---|---|---|
| [Continuum](https://arxiv.org/abs/2511.02230)（ICLR '26） | 工具调用期间按 TTL 把 KV cache 固定在 GPU 上，TTL 由预测的工具时长、重新加载代价和请求顺序决定；SWE-bench 与 BFCL 上降低作业完成时间 | 摘要 |
| InferCept（ICML '24）、Autellix | 前者静态保留工具调用期间的 KV，后者在每轮结束时淘汰 KV（据 Continuum 的描述） | 未复核 |

### 候选方向的覆盖情况

| 候选做法 | 已覆盖它的工作 |
|---|---|
| 模型等待期间卸载或冻结沙盒 | AgentSysBench §8.3、Crab、E2B pause，以及 serverless 的 FaaSMem 和 Desiccant |
| 按每轮状态决定保存粒度 | Crab |
| 让 checkpoint/rollback 足够快、不再是瓶颈 | DeltaBox（毫秒级）、CXLfork |
| 峰值突发与超卖控制 | AgentCgroup |
| 共享运行时或内存模板以提高密度 | TrEnv、CUA-Sandbox、CXLfork |
| 按预测空闲时长分级保活 | Serverless in the Wild、FaaSMem 的半热阶段 |
| 空闲 worker 池循环与跨会话复用 | aShare、Sandman、TrEnv、K8s WarmPool |
| 工具调用期间保留 KV | Continuum、InferCept |

据此，此前提出的"按状态分级处理空闲沙盒"（保持热态、原地冻结并回收、释放）没有新的机制成分，不应作为主贡献。"恢复太慢所以放弃 resume"这一前提也被 DeltaBox 的毫秒级回滚和 AgentSysBench 不到 0.5% 的开销进一步削弱。

### 仍可能空着的位置（待验证的判断）

1. **交互式云桌面 agent 的服务。** CUA-Sandbox 针对 RL rollout；AgentSysBench 的 GUIAgent 桌面沙盒占执行时间 70% 以上，而两篇的生产轨迹都不含桌面负载。交互式服务中有用户停顿，状态几乎全在进程内存里，又有渲染和编码开销。这一场景下的资源刻画与调度尚未见到。
2. **沙盒和推理放在同一预算下调度。** Continuum 只处理 KV，AgentSysBench 只提出同时卸载 KV 和沙盒的设想。两者的空闲期互补：模型推理时沙盒空闲，工具执行时 KV 空闲。完整评估需要自建推理服务，本机 6 GB GPU 只能做小模型验证。
3. **丢弃状态的反事实影响（测量贡献）。** Crab 衡量的是故障恢复后的正确性。SandWeaver 的全量回放在 9 种语言上对同一轨迹配对比较 session 与 batch，并用官方评测打分，可以量化"释放时丢掉状态"对结果的影响。这是测量，不是系统机制。
4. **会话中途依赖变化后的恢复。** aShare 和 TrEnv 只处理预先确定的依赖。不过试点里写层中的依赖类内容只出现在 caddy（Go 模块缓存），这个问题的重要性尚缺证据。

### 两个候选方向的进一步核对

**方向一：交互式云桌面 agent。** 新找到的相关工作如下，均只核对到摘要。

| 工作 | 场景 | 与交互式服务的差别 |
|---|---|---|
| [CUA-Sandbox](https://arxiv.org/abs/2609.32750) | RL rollout，私有状态加共享运行时 | 面向训练吞吐，没有用户停顿 |
| [TClone](https://arxiv.org/abs/2605.17320) | 在用户真实工作区里 fork 实时 GUI 环境，用于安全回滚和推测执行；基于容器，内存 CoW | 解决分支与回滚，摘要未涉及空闲桌面的密度或资源回收；端到端任务延迟相对 KVM 降 1.9×，相对 CRIU 降 1.5× |
| [OSGym](https://arxiv.org/pdf/2511.11672v1) | 以学术预算扩展到上千个 OS 副本 | 面向训练规模，副本比任务沙盒重得多 |
| [AgentSysBench](https://arxiv.org/abs/2608.15127) | GUIAgent 刻画 | 桌面沙盒占执行时间 70% 以上，每步传输高分辨率截图；生产轨迹不含桌面 |
| 早期 VDI 与内存去重（Difference Engine，OSDI '08；KSM） | 多台桌面虚拟机整合 | 面向人类用户，不是 agent；未复核 |

判断：还没有找到研究"交互式服务中空闲云桌面的资源与状态"的工作。这个空白和本项目最初的场景（类似 Grok 的交互式 agent 操纵云电脑）一致，但目前只是候选，需要先刻画。

本机条件：有 `/dev/kvm`；本地有 AgentSysBench 的 GUIAgent 部署脚本，它基于 OSWorld 的 QEMU 虚拟机，首次运行要下载约 11 GB 的 qcow2 镜像。WSL 只有 7.9 GB 内存，同时只能跑一到两台桌面 VM，可以通过 `.wslconfig` 调高内存。在线运行需要多模态模型。不用 API 的做法是像 coding 试点一样回放公开的 OSWorld 轨迹，但这些轨迹是否公开、能否按记录的等待回放，尚未核实。

**方向一的追问：桌面内存能否按来源拆分并共享（2026-11-15 核对）。** 桌面虚拟机实测的 3.5 GiB 约一半是客户机页缓存、约三成是进程内存（见 [characterization](characterization.md#第二期交互式云桌面2026-11-15-启动)）。按机制已有大量先例：

| 机制 | 工作 | 要点 | 核对 |
|---|---|---|---|
| 按内容去重 | Difference Engine（OSDI '08） | 整页、子页共享加压缩，异构负载最多省 65% | 二手资料 |
| 按内容去重 | Satori（ATC '09） | 客户机配合的页共享，可捕获短寿命的共享页 | 二手资料 |
| 按内容去重 | [KSM++ 与 XLH](https://os.itec.kit.edu/2445.php)（KIT） | 用 I/O 提示加快扫描；可共享页中 63.8%–94% 属于页缓存，三台桌面虚拟机测试中 file 页占可共享内存的 73.7% | 摘要 |
| 用户提示的合并 | [UPM](https://arxiv.org/abs/2311.13588)（IEEE BigData '23） | 用 `madvise` 声明可共享区域，代替 KSM 后台扫描；serverless 内存最多省 55% | 摘要 |
| 模板克隆加写时复制 | Potemkin（SOSP '05）、SnowFlock（EuroSys '09）、TrEnv、CXLfork | 从已初始化的实例 fork，内存写时复制 | 二手资料或旧条目 |
| agent 沙盒的模板与差量 | [AgentZip](https://arxiv.org/abs/2609.11294)（arXiv 2609.11294） | 利用相对共享模板和跨沙盒的冗余压缩沙盒私有页，把压缩安排在 LLM 等待期间；沙盒私有内存最多降 8.7×（Linux 配置为 2.1×），减速从最多 3.1× 降到 1.40× | 摘要 |
| GUI 环境 fork | [TClone](https://arxiv.org/abs/2605.17320)、[CUA-Sandbox](https://arxiv.org/abs/2609.32750) | 写时复制内存共享；共享运行时加私有状态 | 摘要 |
| 共享宿主页缓存 | virtio-pmem 或 virtio-fs 加 DAX（[内核讨论](https://lists.openwall.net/linux-ext4/2019/01/14/1)） | 可执行文件等只在宿主保留一份；讨论中提到页是否驻留可能在客户机之间泄露信息 | 邮件列表 |

判断：把内存按来源拆分（镜像页、模板初始状态、会话私有增量、可丢弃部分）并分别共享或压缩，在机制层面已被覆盖，AgentZip 连"在 LLM 等待期间做"也已覆盖。可能剩下的是测量：交互式长会话中私有增量随时间和用户停顿如何增长，以及多租户下只共享公开镜像页（不做按内容去重）能保住多少收益。这些只能算测量贡献，单独不足以构成系统论文。

**桌面观测通路与冷启动（2026-11-15 核对，均为摘要或厂商资料）。** 每步截图 0.5–1.6 MB，但视觉 token 削减已很拥挤：[ReVision](https://arxiv.org/abs/2605.11212)（跨截图的时间冗余，token 降 46%）、[GUI-KV](https://arxiv.org/abs/2510.00536)、[STaR-KV](https://arxiv.org/abs/2606.01790)、[AQuaUI](https://arxiv.org/abs/2605.19260)、[Visual Token Routing](https://arxiv.org/abs/2611.06854)。桌面冷启动实测 17–82 s，而厂商已普遍用预热池、内存快照或精简镜像解决（如 [Blaxel](https://blaxel.ai/blog/agent-code-execution-at-scale-no-cold-starts)、[Dedalus](https://www.dedaluslabs.ai/blog/sandbox-cold-start)、[Cua](https://cua.ai/docs/cua/guide/get-started/what-is-desktop-sandbox)）。二者都不宜作为主线。

**设想：容器化的精简桌面（microDE，2026-11-15 提出）。** 不用完整虚拟机，在容器里跑面向 agent 的精简桌面。深入检索后，已有工作如下（标注同前；"二手"指只见到摘要、厂商页或第三方评述）。

| 类别 | 工作 | 要点 | 核对 |
|---|---|---|---|
| 容器化 OSWorld | [CUA-Lite](https://rdi.berkeley.edu/blog/cua-lite)（Berkeley RDI，2026-09） | Lite.OSWorld 在 Docker 里的 GNOME 桌面中原样运行 OSWorld 的任务和评测器，不需要 `/dev/kvm`；[README](https://github.com/cua-lite/cua-lite/blob/main/lite/gym/envs/lite/osworld/README.md) 称"数秒内启动"，369 个评测任务中排除 41 个。官方博客没有给出数字；第三方评述称每实例 0.9 GB 对比虚拟机 4.1 GB，冷启动 23.8 s 对比 29.9 s，未核实 | 官方页与 README |
| 大规模 GUI 环境 | [MAI-Gym](https://arxiv.org/abs/2610.20939)（2026-10） | 手机用 ReDroid 容器跑在宿主内核上，绕开嵌套虚拟化；桌面仍是虚拟机，重置中位数 37 s；并行 20,000 个环境 | 正文前半 |
| 容器 Android 环境 | [Qwen-UI-Agent 技术报告](https://arxiv.org/abs/2607.28227) | 改用 ReDroid 突破基于 KVM 的模拟器的扩展上限 | 摘要 |
| 产品与开源实践 | Anthropic computer-use 参考实现、[E2B Desktop](https://e2b.dev/docs/template/examples/desktop)（Firecracker 里跑 Xvfb 加 XFCE）、[Cua](https://cua.ai/docs/explanation/how-sandboxes-work)（Kasm 容器桌面，macOS 用 Lume 虚拟机）、[OpenSandbox](https://www.mintlify.com/alibaba/OpenSandbox/examples/desktop-environment)、[Warp](https://www.warp.dev/blog/computer-use-cloud-agents)、[Beam](https://www.beam.cloud/use-cases/computer-use)（每个桌面一个 microVM，暂停即释放计算） | Xvfb 加轻量窗口管理器的容器桌面已是常见做法 | 文档 |
| 面向 agent 的合成器会话 | [waydriver](https://docs.rs/crate/waydriver/latest)、kwin-mcp、Deskwright | 隔离的无头 Mutter 或 KWin 会话，通过 AT-SPI 和 PipeWire 截图，供 agent 驱动 | 文档 |
| 浏览器的对应物 | [Unikraft 无头浏览器](https://unikraft.com/blog/millisecond-headless-browsers) | 精简的 Chromium，从快照 50 ms 内恢复，空闲时缩到零，单机数千实例；每实例约 1.5 GB；只有无头浏览器，没有桌面 | 厂商博客 |
| 轻量桌面虚拟化（学术） | THINC（SOSP '05）、MobiDesk、[DejaView](https://www.cs.columbia.edu/~nieh/pubs/sosp2007_dejaview.pdf)（SOSP '07）、[Apiary](https://www.cs.columbia.edu/~nieh/pubs/usenix2010_apiary.pdf)（ATC '10）、[Cells](https://www.cs.columbia.edu/~nieh/pubs/sosp2011_cells.pdf)（SOSP '11） | Columbia Nieh 组：显示虚拟化、用 pod 承载桌面会话并持续 checkpoint（不改内核）、每个桌面应用一个短命容器、单内核上用设备命名空间虚拟显示与输入 | 摘要与幻灯片 |
| 库操作系统跑桌面应用 | [Drawbridge](https://www.cs.unc.edu/~porter/pubs/p291-porter.pdf)（ASPLOS '11）、[Embassies](https://www.usenix.net/system/files/conference/nsdi13/nsdi13-final85.pdf)（NSDI '13） | picoprocess 加 Windows 库操作系统运行 Office、IE，经 RDP 显示；Excel 进程快照压缩后不到 4 MB，对比虚拟机快照约 150 MB；Embassies 只给应用像素式界面 | 摘要 |
| 内核：设备命名空间 | [2013 RFC](https://lwn.net/Articles/564854)、[2021 LKML 讨论](https://lore.kernel.org/containers/877dj4ff9g.fsf@disp2133/) | 面向多个手机实例的设备命名空间提案，2021 年再议被否，未合入主线 | 邮件列表 |
| GUI 容器隔离工具 | [x11docker](https://github.com/mviereck/x11docker)（JOSS '19）、Xpra 或 Xephyr 嵌套 X、Flatpak 安全上下文套接字 | 避免共享宿主 X 套接字造成泄露；没有找到 gVisor 支持 GUI 栈的资料 | 文档 |

判断：

- "容器桌面代替虚拟机"本身不新。产品普遍这样做；CUA-Lite 已经把 OSWorld 原样搬进容器；学术上的轻量桌面虚拟化可以追溯到 2005–2011 年的 Nieh 组和 Drawbridge。
- 仍可能空着的位置：
  1. 公开、系统的容器桌面与虚拟机对比，覆盖密度、内存成分、空闲回收和评测忠实度。CUA-Lite 没有发表数字。
  2. 多租户服务中共享内核桌面的隔离。桌面会运行不可信网页，而设备命名空间没有进主线，gVisor 对 GUI 栈的支持不明。Cells 是单用户手机场景的先例，不是云上多租户。这是改内核最有依据的方向。
  3. 交互式服务（而非 RL rollout）下容器桌面的空闲回收与恢复。

**多租户桌面隔离的设计空间（2026-11-15 讨论，未验证）。** 现有 OSWorld 栈从下到上是：宿主内核、Docker 容器、QEMU、客户机内核、systemd 与 GNOME、Xorg、应用，截图再经客户机内的 HTTP 服务传回。可以从三个方向压缩：

| 做法 | 隔离边界 | 已有工作 | 本项目的问题 |
|---|---|---|---|
| 把 microVM 压到最小：精简客户机，只跑 Xvfb 加窗口管理器；rootfs 用 virtio-fs DAX 共享；空闲页上报；模板快照 | 硬件虚拟化 | LightVM（SOSP '17，启动 2.3 ms）、Firecracker、E2B Desktop、Beam | 桌面负载下每台虚拟机的内存下限，以及共享页缓存的实测；新颖性有限 |
| 共享内核，每个租户一套桌面容器，再加固内核 | 内核命名空间加 seccomp、Landlock | Cells（单用户手机）、CUA-Lite（不涉及多租户隔离）、设备命名空间未合入 | GUI 栈实际用到的系统调用和 ioctl 面有多大，能削到多小 |
| 去掉客户机内核：用户态内核或库操作系统承接系统调用 | gVisor 的 Sentry 或库操作系统 | gVisor 在 Tencent 每天运行数百万个代码沙盒（[博客](https://gvisor.dev/blog/2026/04/23/scaling-agentic-rl-sandboxes-to-the-millions-with-gvisor-at-tencent/)，不含 GUI）；X-Containers（ASPLOS '19）；Drawbridge 跑过 Office | 未找到 gVisor 跑 Xvfb、GUI 应用或 OSWorld 任务的公开资料；兼容性和系统调用开销对图形负载的影响未知 |

第三种做法验证成本最低：同一个容器桌面镜像，分别用 runc、runsc（gVisor）和 microVM 运行，比较 OSWorld 任务能否正常回放、内存、启动时间和每步延迟。

**相关工作（2026-11-15 检索；除注明外只核对到摘要、文档或二手资料）。**

| 方向 | 工作 | 要点 |
|---|---|---|
| 压扁的桌面虚拟机 | [Windows Sandbox](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-architecture) | 动态基础镜像：不可变的系统文件直接用宿主的，只带可变文件的原始副本（压缩包约 30 MB，安装后约 500 MB）；"direct map" 让沙盒与宿主共用系统二进制的物理页（只共享只读页）；宿主可以像回收进程内存一样回收沙盒内存。官方文档 |
| GUI 应用跑在轻量虚拟机里 | [ChromeOS Crostini](https://chromium.org/chromium-os/developer-library/guides/containers/containers-and-vms) | crosvm 启动精简的 Termina 虚拟机，里面跑容器；Sommelier 代理把 Wayland 和 X 流量转发到宿主的 Exo 合成器。官方文档 |
| 每个任务一个虚拟机 | Bromium（现 HP Sure Click）、Qubes OS | 每个不可信任务一个 micro-VM；Qubes 一次性虚拟机从保存的镜像恢复；应用虚拟机只能经受限的 Qubes GUI 协议显示。厂商资料 |
| 轻量虚拟机 | LightVM（SOSP '17） | 重写 Xen 控制面，启动 2.3 ms |
| 每个容器一个内核 | X-Containers（ASPLOS '19） | 库操作系统加 exokernel，系统调用吞吐比 Docker 最高快 27× |
| 每个容器一个内核 | [CKI](https://ipads.se.sjtu.edu.cn/zh/publications/ShiEurosys25.pdf)（EuroSys '25） | 用内核态内存保护键（PKS）为每个容器隔离出独立内核；PKS 只有 16 个域 |
| 每个容器一个内核 | [RContainer](https://www.ndss-symposium.org/wp-content/uploads/2025-328-paper.pdf)（NDSS '25）、[ParaCell](https://arxiv.org/abs/2605.20906)、MettEagle（OSDI '25，据文件名） | ARM 颗粒保护表、MPK 门、基于 L4Re 微内核的容器式隔离 |
| 无硬件虚拟化的安全容器 | [PVM](https://ranger.uta.edu/~jrao/papers/sosp23.pdf)（SOSP '23） | 不依赖嵌套硬件虚拟化的客户机 hypervisor，阿里云和蚂蚁每天用它承载数万个安全容器 |
| 用户态内核 | gVisor | 在 Tencent 每天运行数百万个代码沙盒；GitHub 上与 GUI 相关的只有 [#5571](https://github.com/google/gvisor/issues/5571)（2021，宿主 X11 或 Wayland 套接字无法映射进沙盒，已关闭）。没有找到跑 Xvfb 或 GUI 应用的资料 |
| 库操作系统 | Drawbridge（跑过 Office）、Gramine、Occlum | 后两者面向 SGX 单应用，没有找到 GUI 支持的资料 |
| 设备的按容器实例化 | [binderfs](https://people.kernel.org/brauner/android-binderfs)（已合入主线） | 为 Anbox 等 Android 容器提供每容器独立的 binder 设备；通用设备命名空间则被否（见上表） |
| 系统调用面削减 | [Confine](https://www.usenix.org/conference/raid2020/presentation/ghavanmnia)（RAID '20）、Temporal System Call Specialization（USENIX Security '20） | 对容器镜像静态分析生成 seccomp 策略，约一半镜像可禁用 145 个以上系统调用（共 326 个），覆盖 51 个已知内核漏洞 |
| 安全窗口系统 | [Nitpicker](https://typeset.io/pdf/a-nitpickers-guide-to-a-minimal-complexity-secure-gui-fnq1gqjmr7.pdf)（ACSAC '05）、[EWS](https://usenix.org/event/sec04/tech/full_papers/shapiro/shapiro.pdf)（USENIX Security '04）、Qubes GUI 协议 | GUI 服务器缩到约 1,500 行（Nitpicker）或 4,500 行以内（EWS），窗口处理移到客户端 |

判断：

- "压扁 microVM、共享内核、各租户不同桌面"的每个组件都有先例：共享宿主系统页（Windows Sandbox）、每容器独立内核（X-Containers、CKI、PVM）、虚拟机内跑 GUI 再经窄协议导出（Crostini、Qubes）、削减系统调用面（Confine）。
- 没有找到把这些用于多租户 agent 桌面的工作，也没有找到在 gVisor、CKI 一类机制下实测 GUI 栈（Xvfb、浏览器、办公套件）的公开数据。
- agent 桌面与人用桌面有一处结构差异：消费画面的是 agent，不需要面向人的可信路径。隔离边界上可以只导出帧缓冲和输入事件（类似 Embassies 的像素接口），整个 GUI 栈留在隔离域内，不必让 X 或 Wayland 套接字跨越边界。这一点是否足以构成贡献，需要先测 GUI 栈在这些隔离机制下的兼容性、系统调用面和开销。

按本项目对一台 OSWorld 虚拟机的内存拆分估算（未实测）：约 1.7 GiB 客户机页缓存在容器中变为宿主共享页缓存；0.5–0.8 GiB 已触及的空闲页不再存在；约 0.5 GiB 对 agent 无用的桌面服务可以去掉。每个实例可能只剩应用本身加 X 服务器和 agent 服务，约 0.3–0.6 GiB，启动从 17–82 s 降到秒级。

需要回答的问题：

- **隔离。** 容器共享内核，桌面又运行不可信网页内容，隔离弱于虚拟机。这是改内核最有理由的地方，例如虚拟输入和显示设备目前没有命名空间。gVisor、Kata 等是现成的折中。
- **快速 fork 与回滚。** TClone、DeltaBox 已在这方面做了工作，需要先确认还缺什么，再决定是否改内核。
- **忠实度。** 公开轨迹是在 GNOME 桌面上录制的，换成精简桌面后，录好的点击坐标会错位。对照实验应分三步：虚拟机，然后同样的 Ubuntu GNOME 用户态放进容器，最后才是精简桌面。

**对 agent 无用的桌面机制（2026-11-16，分析，未验证）。** 人用桌面的许多机制假设有人坐在屏幕前。按对 agent 的影响分四类；内存数字来自上文 libreoffice_calc 的单次快照（RSS 含共享页），其余为推测。

| 类别 | 机制 | 依据 |
|---|---|---|
| 无用且有成本（去掉） | 软件中心、更新与固件服务（snap-store、snapd、snapd-desktop-integration、packagekitd、fwupd）；日历与邮件提醒（evolution-alarm）；文件索引、崩溃上报、定位、色彩管理、蓝牙、打印；登录管理器与多用户会话切换；合成器动画与光标闪烁 | 前五个服务 RSS 合计约 420 MiB；空闲期 top 中 evolution-alarm 偶尔排第一；动画与闪烁的开销未拆分 |
| 对 agent 有害 | 锁屏、屏保与显示器休眠（模型等待中位 24 s）；通知弹窗遮挡点击位置；更新提示、首次运行向导、授权与密钥环弹窗 | 推测，需要从失败轨迹中核实 |
| 形式不对 | 物理显示、GPU、DRM/KMS 与垂直同步（agent 只需观测时的一帧，可软件渲染）；内核输入设备与 udev 热插拔（可直接经 XTEST 向 X 服务器注入）；声卡（空输出即可，VLC 任务只检查播放状态）。无障碍树相反，应保留并加强 | 设计判断 |
| 虚拟化层重复 | 每台一份客户机内核、固件与完整 systemd 启动；客户机页缓存约 1.7 GiB；已触及的空闲页 0.5–0.8 GiB；QEMU 模拟的 VGA、USB 平板、声卡 | 内存来自快照；启动 17–150 s 受争用影响 |

按快照估算，3.5 GiB 中约 2.5 GiB 属于第一类和第四类，应用本身、X 服务器和 agent 服务约 0.3–0.6 GiB（未实测）。

**大规模并行隔离桌面的分层设计（2026-11-16，设计提案，未验证）。** 关键观察：显示改用 Xvfb、输入改用 XTEST、声音改用空输出后，桌面不再需要 `/dev/dri`、`/dev/input`、`/dev/tty`、`/dev/snd`。此前共享内核方案的障碍是设备命名空间没有进入主线，而这时它不再必需，剩下的只是普通系统调用、共享内存和 Unix 套接字，gVisor、每容器独立内核、seccomp 等容器隔离手段都可能适用。Xvfb 与 Chromium 在 gVisor 下能否运行，没有找到公开报告；Chromium 自身的沙盒在 gVisor 下可能要关闭，属于安全取舍。

| 层 | 做法 | 已有工作 | 可能的新东西 |
|---|---|---|---|
| ① 共享只读基础 | 一份镜像，宿主页缓存由所有租户共享（容器 overlay，虚拟机则 virtio-fs DAX） | Windows Sandbox、CUA-Lite | 无 |
| ② 每租户最小会话 | Xvfb 或无头 wlroots、简单窗口管理器、应用、AT-SPI 总线、agent 服务；不要 gdm、gnome-shell 和用户会话服务；分辨率与主题与录制一致 | E2B Desktop、CUA-Lite | 无 |
| ③ 窄隔离边界 | 边界只导出帧、输入、无障碍树和文件，GUI 栈留在沙盒内；每租户网络命名空间加出口策略；隔离由弱到强选 gVisor、每容器内核、最小 microVM | Qubes GUI 协议、Embassies、Cells | agent 桌面相对人用桌面的系统调用和 ioctl 面实测；GUI 栈在 gVisor、CKI 下的兼容性与开销 |
| ④ 生命周期 | 从初始化好的模板 fork；等待期降优先级或冻结；SandWeaver 租约从工作区扩展到桌面 | TClone、CUA-Sandbox、AgentZip、Android cached apps freezer | 每步粒度的策略（见下文方案 A、C） |
| ⑤ 必要时改内核 | 每步冻结后客户机会看到时钟跳变；time namespace 的偏移只能在首个进程进入前设置，候选做法是允许对已冻结的 cgroup 调整偏移 | CRIU 恢复时使用 time namespace | 未检索，不能称新 |

面向 agent 的操作系统类工作：[LUMOS](https://arxiv.org/abs/2606.30697) 在人用界面旁增加语义接口；[Microsoft Project Solara](https://thenextweb.com/news/microsoft-project-solara-agent-first-devices-build-2026) 是基于 AOSP 的 agent 设备（新闻报道）；[LiteCUA](https://arxiv.org/abs/2505.18829) 把电脑包装成 MCP 服务器；[AgentKernel](https://arxiv.org/abs/2609.29647) 只见到参考文献部分。均不涉及多租户隔离和密度。

判断：①②④ 基本是已有部件的组合；可能新的只有"去掉人用设备后内核接口缩小到容器级隔离可用"的实测论证，以及冻结时的时间命名空间调整，二者都未验证。最便宜的验证是：精简桌面镜像在 runc 下回放 OSWorld 任务并用 strace 或 seccomp 日志记录系统调用和 ioctl，再换到 runsc，比较可运行性、内存、启动和每步延迟，并用 OSWorld 评测器检查忠实度。

**安卓的对照：共享内核的 GUI 实例已经大规模运行（2026-11-16 检索，多为摘要、文档或厂商资料）。**

| 场景 | 工作 | 做法与规模 |
|---|---|---|
| agent 评测 | [AndroidWorld](https://arxiv.org/abs/2405.14573)（ICLR '25） | 官方 Android Emulator（KVM 虚拟机），116 个任务，每实例约 2 GB 内存 |
| agent 训练 | [MAI-Gym](https://arxiv.org/abs/2610.20939)、[Qwen-UI-Agent](https://arxiv.org/abs/2607.28227) | 手机改用 ReDroid 容器，共享宿主内核，避开嵌套虚拟化；MAI-Gym 并行 20,000 个环境，但桌面仍用虚拟机 |
| agent 训练 | [MobileGym](https://arxiv.org/pdf/2605.26114.pdf) | 认为模拟器每实例数 GB 难以并行，改用仿真平台，单机数百实例（编号与论文对应未核实） |
| 云手机 | [Anbox Cloud](https://documentation.ubuntu.com/anbox-cloud/) | LXD 系统容器共享宿主内核，厂商称每台服务器最多约 100 个实例；国内云手机业务也大量运行在 ARM 服务器的容器上 |
| agent 产品 | [AutoGLM 2.0](https://eu.36kr.com/zh/p/3431965792144772) | 每个用户一台规格统一的云手机和一台云电脑（媒体实测，底层未公开） |
| 内核支持 | [binderfs](https://people.kernel.org/brauner/android-binderfs) | 已合入主线，为每个容器提供独立 binder 设备；通用设备命名空间未合入 |

安卓与 Linux 桌面的差距主要在用户态框架，不在内核（两者是同一个 Linux 内核；下表安卓一列来自通用知识，未逐条核对）：

| 能力 | 安卓 | Linux 桌面 |
|---|---|---|
| 应用生命周期 | 框架统一管理前台、后台、停止、缓存，应用在 `onStop`、`onSaveInstanceState` 中保存状态 | 没有通用约定；XSMP 会话管理很少被应用实现 |
| 后台冻结与回收 | cached apps freezer 在缓存 10 s 后冻结；lmkd 杀进程后应用可恢复状态 | 没有统一机制；OOM 杀进程即丢状态 |
| 不可见时停止渲染 | 应用进入后台即停止绘制，SurfaceFlinger 只合成可见层 | X11 没有帧回调；Wayland 下取决于合成器 |
| 虚拟显示与输入 | 框架提供 VirtualDisplay，输入经 ADB 注入 | Xvfb、无头 Mutter 或 wlroots 可用，但不是标准配置 |
| 自动化与语义接口 | 系统内置 AccessibilityService、UIAutomator | AT-SPI 支持参差，部分工具包在窗口映射后才发布 |
| 每应用隔离 | 每个应用独立 uid 加 SELinux | Flatpak 部分提供 |

判断：

- 手机侧"大规模、共享内核、容器化"已经做到，是工程现实，不是研究空白。手机侧仍未见公开测量的是：多租户下共享内核的隔离强度，以及 agent 等待期间的空闲处理。
- 桌面侧缺的不是内核功能，而是安卓框架提供的那套约定：生命周期、冻结后可恢复、不可见即停绘、标准化的虚拟显示与语义接口。可以研究的问题是把这些约定的哪几样以最小代价补给 Linux 桌面，补上后能否达到云手机的密度。这需要先测量，且要检索桌面侧是否已有类似尝试（例如 GNOME 的后台应用门户、systemd 的应用 scope 管理），尚未完成。

**把安卓的约定补给 Linux 桌面：代价与已有工作（2026-11-16 检索，多为文档、补丁、论坛或新闻）。** agent 桌面与人用桌面有一处关键差异：整个显示服务器和会话都在沙盒里，由平台控制。因此不需要应用配合的做法（冻结整个沙盒、透明 checkpoint）可以替代人用桌面上必须由应用实现的约定。

| 约定 | 补给 agent 桌面的最小做法 | 代价 | 已有工作 |
|---|---|---|---|
| 虚拟显示与输入 | Xvfb 或无头合成器，XTEST 注入 | 已有，零开发 | E2B Desktop、waydriver、CUA-Lite（见上文） |
| 后台冻结 | 按步冻结整个桌面的 cgroup，不必区分应用 | 低：cgroup v2 freezer 已有 | 安卓 cached apps freezer；[Ubuntu Touch](https://forums.ubports.com/topic/7439/is-closing-apps-generally-unnecessary-in-ut-like-in-android) 对切到后台的应用发 SIGSTOP（论坛，机制未确认）；Plasma 和 GNOME 已把每个应用放进独立的 systemd scope，KDE 称冻结是计划用途（[博客](https://blog.davidedmundson.co.uk/blog/modern-process-management-on-the-desktop/)，2020）；macOS [App Nap](https://developer.apple.com/library/archive/documentation/Performance/Conceptual/power_efficiency_guidelines_osx/WorkWhenActive.html) 由系统决定；Google 的 [RFC 补丁](https://patchew.org/linux/20250805032940.3587891-4-ynaffit@google.com) 为 cgroup v2 freezer 统计冻结时长，并指出冻结可能让看门狗误杀进程 |
| 冻结后可恢复，被回收不丢状态 | 不依赖应用保存状态，对整个桌面容器做 checkpoint（显示服务器也在被 checkpoint 的进程树内） | 中到高：虚拟机快照成熟；容器下 CRIU 原理可行但稳定性未验证，X 服务器须在同一进程树内（见下文"整桌面 checkpoint 的可行性"） | 安卓 `onSaveInstanceState`、[UWP PLM](https://learn.microsoft.com/windows/uwp/launch-resume/app-lifecycle)、macOS 自动终止都要求应用配合；GNOME 的[会话保存与恢复计划](https://discourse.gnome.org/t/introducing-the-session-save-restore-initiative/33127)基于 `xdg_session_management_v1`，只恢复窗口状态，GTK 的应用状态快照尚在进行，不会进入 GNOME 51（[新闻](https://linuxiac.com/gnome-is-building-session-save-and-restore-but-it-wont-make-gnome-51/)）；不需要应用配合的有 [CRIU 的 VNC 做法](https://www.criu.org/VNC)（VNC 服务器、窗口管理器和应用放进同一 PID 命名空间）、[criu-x11-poc](https://github.com/mikaelhg/criu-x11-poc)（每个应用一个 Xvfb）、DejaView（SOSP '07）以及 agent 侧的 Crab、DeltaBox、TClone、CUA-Sandbox |
| 不可见即停绘 | 观测之间让合成器停发帧回调，或让应用以为窗口已隐藏；截图时补画一帧 | 中到高：X11 没有帧回调，要改合成器或换 Wayland；客户端可能卡死 | Weston 和 KWin 对被遮挡窗口停发帧回调（见上文方案 C）；Chrome 的隐藏页节流；没找到面向 agent 的实现 |
| 语义接口 | 依赖 AT-SPI；补齐要逐个应用改 | 高 | [LUMOS](https://arxiv.org/abs/2606.30697)；OSWorld 的无障碍树观测 |
| 每应用隔离 | agent 场景更需要的是每租户隔离（见上文分层设计） | 不适用 | Flatpak |

判断：

- 单项都有人做过：冻结在手机 Linux、macOS、安卓上都是成熟机制；透明 checkpoint GUI 会话有 CRIU 的做法和 DejaView；虚拟显示是常规做法。人用 Linux 桌面上唯一仍在进行的是"应用配合的状态保存"（GNOME 会话恢复），而 agent 桌面可以用整桌面 checkpoint 绕过它。
- 没找到把这些组合起来用于 agent 桌面、并测量密度和恢复时延的工作。组合本身是集成，贡献偏测量。
- 仍有技术难点的三处：按步冻结后的时钟跳变与看门狗（Google 的补丁只统计冻结时长，不对进程隐藏跳变）；X11 下的不可见即停绘；每步粒度的整桌面 checkpoint 成本（需要先核对 TClone 和 CUA-Sandbox 全文，确认是否已覆盖）。
- 检索局限：没检索到在 Linux 笔记本上评估冻结后台桌面应用的学术论文；ChromeOS 的标签页丢弃与 ARC 生命周期尚未检索。

**整桌面 checkpoint 的可行性（2026-11-16 补充）。** 上表"整桌面 checkpoint 代替应用配合"要分情况：

- 虚拟机：成熟。QEMU `savevm` 或内存快照可以保存整台桌面，代价是每次写出全部客户机内存（本项目实测 3–4 GiB），按步做太贵，需要增量快照。
- 容器：原理上可行，CRIU 的 VNC 做法和 DejaView（2007）都保存过整个桌面会话，但稳定性未知。已知障碍：X 服务器必须在被 checkpoint 的进程树内；活动 TCP 连接要 `--tcp-established` 且须尽快恢复；被 ptrace 的进程无法 checkpoint；D-Bus 会话和共享内存要一起保存；Chromium 自身的沙盒使用嵌套命名空间和 seccomp，没有找到 CRIU 处理它的公开资料。每次 dump 的数据量是全部应用内存，同样需要增量（DeltaBox 的方向）。
- 所以容器桌面的整桌面 checkpoint 是"需要先实测能否工作"的前提，不能当作已知可用。

**共享内核、共享桌面环境、应用隔离、多个 agent 并行（2026-11-16 讨论与检索，设计提案，未验证）。** 设想：一个合成器和桌面外壳服务多个 agent，每个 agent 有自己的焦点、光标、剪贴板、可截图的输出和隔离的应用。

| 要分开的东西 | 做法 | 现有支持 |
|---|---|---|
| 焦点、光标、剪贴板 | Wayland 多 seat：每个 agent 一个 seat，各自独立的指针、键盘焦点、剪贴板和拖放状态 | wlroots 0.1 与 sway 1.0 起支持；Weston 也有；[Musa](https://mainiomano.srht.site/blog/2024/03/introducing-musa/) 是专门的多 seat 合成器；SDL、Blender 等工具包对多焦点处理不完善（[综述](https://blinry.org/multi-seat-wayland/)） |
| 输入注入 | 每个 agent 一个 [libei](https://libinput.pages.freedesktop.org/libei/api/) 客户端，合成器知道每个事件来自谁，可以按 seat 路由或拒绝 | libei 已发布，经 RemoteDesktop 门户授权 |
| 截图 | 每个 agent 一个无头输出，只截自己的输出 | 无头输出和按输出截屏在 wlroots 一类合成器中已有 |
| 应用隔离 | 每个 agent 的应用放进 bubblewrap 或类 Flatpak 沙盒：独立的挂载（HOME、/tmp）、PID、网络命名空间，D-Bus 经过滤代理，独立的 dconf | Flatpak 已用于单用户桌面 |
| 共享 | 内核、合成器、只读 `/usr` 的页缓存、字体与图标缓存 | 上文分层设计 ① |

为什么要多 seat 加 Wayland：X11 下任何客户端都能读其他窗口和全局输入，XTEST 注入是全局的，无法在一个 X 服务器里隔离多个 agent。

需要处理的冲突：

- 单实例应用：LibreOffice、Chrome、VS Code、Thunderbird 启动第二个实例时会把请求交给已有实例，跨 agent 串到一起。需要靠每个 agent 独立的 HOME、/tmp 和 D-Bus 打断。
- 修改全局状态的任务：OSWorld 的 os 域和部分设置类任务改的是系统或桌面设置，本质上不能共享，只能落到独立实例。
- 合成器是共享的可信计算基：它的漏洞就是跨 agent 漏洞。同一用户的多个 agent 可以接受，跨租户较弱。

相关工作：

- [Multi-Agent Computer Use](https://arxiv.org/abs/2606.01533)（CMU）给每个子 agent 一台虚拟机，以避免互相干扰，代价是子任务之间要传状态（摘要）。
- [agent-desktop](https://flaviocopes.com/agent-desktop/) 在 X11 上给每个 agent 画一个光标，但动作按租约轮流执行（博客）。
- [Codex issue #20852](https://github.com/openai/codex/issues/20852) 请求并行的 computer-use 会话，指出共享桌面只有一个前台焦点和一条输入流。
- Qubes 是"共享桌面、应用隔离"的先例，但隔离靠虚拟机，不共享内核；Flatpak 是共享内核和桌面、应用沙盒化，但面向单个用户。

判断：

- 没找到用多 seat 合成器加应用沙盒、让多个 agent 并行共用一个桌面的系统。组件都已存在（多 seat、libei、bubblewrap、xdg-dbus-proxy），新意在组合与冲突处理。
- 收益要算清楚：共享桌面环境省下的是合成器和外壳。GNOME 下 gnome-shell 加 Xorg 约 0.6 GiB，但每个 agent 改用 Xvfb 或最小合成器后，这部分估计只剩几十 MiB（未测）。此时主要成本是应用本身，共享桌面环境省得不多；更值得共享的是应用运行时（例如浏览器的隔离上下文共享一个浏览器进程，或类似安卓 zygote 的预加载 fork）。
- 共享桌面环境真正必要的场景是：多个 agent 和用户本人在同一个用户桌面上并行工作（Codex issue 的场景）。这时桌面本身就是共享资源，多 seat 加应用隔离是直接的需求。云上批量运行的场景，每个 agent 一个最小显示更简单。

**面向 agent 的无头合成器（2026-11-16 讨论与检索，设计提案，未验证）。** 在 Wayland 下，合成器负责管理窗口、把各应用的缓冲区拼成画面、把输入分给对应的应用；应用彼此看不到对方的画面，截图和输入注入都要经过合成器。因此合成器是做按 agent 截图、输入、隔离和渲染控制的天然位置。

- 不以 Xfce 为底座：xfwm4 只支持 X11；Xfce 的 Wayland 合成器 [xfwl4](https://docs.xfce.org/xfce/xfwl4/start) 基于 Smithay（Rust）从头编写，2026 年有 4.21.x 预发布，但官方仍标为实验性、不推荐使用（[路线图](https://wiki.xfce.org/releng/wayland_roadmap)，[linuxiac](https://linuxiac.com/xfce-begins-work-on-xfwl4-a-rust-based-wayland-compositor/)）。面板、桌面、通知、电源管理对 agent 无用（见上文无用机制表），所以"新桌面"实质上是一个新合成器加会话与设置管理。
- 基于 wlroots（2026-11-16 选定，原先在 Smithay 与 wlroots 之间待定）从零写无头合成器，原型为独立仓库 [Heddle](https://github.com/aeilot/HeddleDE)。不接 DRM/KMS 和 libinput，只实现应用需要的协议（xdg-shell、wl_shm、wl_seat、剪贴板、输入法），对外提供按 agent 的截图和输入接口；控件树走 AT-SPI，与合成器无关。wlroots 的示例 tinywl 约千行 C，规模供参考；实际工作量未评估。
- 按观测出帧：平时不发 `wl_surface.frame` 回调，agent 请求截图时才向它的窗口发回调，等应用提交并画面稳定后合成一次再截图。这把上文方案 A（按观测时刻调度与画面稳定判定）和方案 C（不可见就不渲染）合成一个机制。协议讨论建议不可见表面不发回调（[wayland#266](https://gitlab.freedesktop.org/wayland/wayland/-/issues/266)）；Mutter 只对被录屏的隐藏表面破例发回调（[MR 2789](https://gitlab.gnome.org/GNOME/mutter/-/merge_requests/2789)）。没找到把"只在观测时出帧"作为默认策略的合成器。
- 已知风险：拿不到回调的 Firefox 和 GDK 会卡住（[Mozilla 1711244](https://bugzilla.mozilla.org/show_bug.cgi?id=1711244)）；光标和拖放表面从不被绘制，回调若绑定绘制就永远不发（[GNOME 739163](https://bugzilla.gnome.org/show_bug.cgi?id=739163)）；Xwayland 应用和自带定时器的视频、动画不受帧回调约束；截图要等应用重画，用延迟换 CPU。
- 前提待测：动作后约 10 s 的 0.3–1.2 核余波里，渲染占多少、应用逻辑（页面加载、排版、语言服务器）占多少。若以应用逻辑为主，压帧收益有限。需要每步实际帧数与按进程的 CPU 采样。

**应用状态隔离与"同时开 100 个 VS Code"（2026-11-16 分析，未验证）。** 不需要虚拟机，用 bubblewrap（Flatpak 的底层）给每个 agent 一套命名空间：

| 状态 | 不隔开的后果 | 办法 |
|---|---|---|
| 配置、扩展、缓存、最近文件 | 互相改设置 | 独立 HOME 与 XDG 目录（挂载命名空间） |
| 单实例锁与 IPC 套接字 | 第二个实例把请求转给第一个，两个 agent 串在一起 | 独立 `XDG_RUNTIME_DIR` 与 /tmp；VS Code 另有 `--user-data-dir` |
| D-Bus 会话总线 | 能找到并调用别的 agent 的应用 | 每个 agent 一条会话总线，或经 xdg-dbus-proxy 过滤 |
| 进程 | 能看到、杀掉、ptrace 别人的进程 | PID 命名空间 |
| 端口 | 语言服务器、调试器端口冲突或互连 | 网络命名空间 |
| 窗口、输入、剪贴板 | 互相截图、注入 | 合成器按 agent 分开（上节） |
| 工作区 | 互相改代码 | 只挂载自己租用的工作区，沿用独占租约 |
| CPU、内存 | 相互拖慢 | 每个 agent 一个 cgroup |

100 个 VS Code 的瓶颈：

- 内存很可能先到上限。Electron 每个窗口至少有主进程、渲染进程、GPU 进程和扩展宿主，再加语言服务器；常见说法是每窗口几百 MiB 到 1 GiB 以上（未测）。按 0.5–1 GiB 估，100 个需要 50–100 GiB。
- CPU：试点中 vs_code 域等待期稳定约 0.8 核，是整台虚拟机 cgroup 的数，没有拆到进程。若确实来自 VS Code，100 个约 80 核。可能来源有光标闪烁引起的重绘、文件监视、扩展宿主、语言服务器（假设）。若主要是重绘，按观测出帧能消掉；若是语言服务器，要靠冻结或 cgroup 限额。
- 上文 GUI 必要性分析表明，编码任务大多不需要 VS Code 界面；真正需要 100 个可见 IDE 的只有以操作界面为目标的任务。

**内存尽可能共享（2026-11-16 分析，未验证）。** 分两类：

- 文件页（代码、库、字体、图标、只读数据）：同一文件在宿主页缓存只有一份，所有进程自动共用。前提是共享内核：100 个容器用同一镜像只读层（overlayfs 下层）即可；100 台虚拟机各有页缓存，同样的代码存 100 份，只能靠 virtio-fs DAX 或 KSM。
- 匿名页（堆、JS 堆、索引、渲染缓存）：默认私有。手段按预期收益排序：
  1. 快照克隆、写时复制：应用预热后快照，新实例以 `MAP_PRIVATE` 映射同一内存快照文件，未写的页一直共享。Firecracker 快照与 Lambda SnapStart 是这样做的；容器下 CRIU 恢复是拷贝而不是映射，默认不共享，需要改造（未验证）。
  2. 模板进程 fork（安卓 zygote）：天然写时复制，但 Electron、Chrome 多线程，跨实例 fork 需要大改。
  3. KSM 合并相同页：Linux 6.4 起可用 `prctl(PR_SET_MEMORY_MERGE)` 对整个进程开启；代价是扫描 CPU 与侧信道风险。按约定，开启前需用户同意。
  4. 应用层共享（一个浏览器进程里多个隔离上下文）：省得最多，但隔离边界降到应用内部。
- 关键未知量：100 个实例的匿名页中内容相同的比例（KSM 统计可回答），以及运行后快照页被改写的比例。

**XDG 与 D-Bus 在隔离中的作用（2026-11-16 整理）。**

[XDG Base Directory](https://specifications.freedesktop.org/basedir-spec/latest/) 是 freedesktop.org 的约定，规定应用把东西放在哪里：

| 变量 | 默认 | 内容 |
|---|---|---|
| `XDG_CONFIG_HOME` | ~/.config | 用户配置 |
| `XDG_DATA_HOME` | ~/.local/share | 用户数据、扩展 |
| `XDG_CACHE_HOME` | ~/.cache | 可删除的缓存 |
| `XDG_STATE_HOME` | ~/.local/state | 历史、最近文件 |
| `XDG_RUNTIME_DIR` | /run/user/UID（tmpfs） | Wayland、D-Bus、音频套接字，常见的单实例锁 |
| `XDG_CONFIG_DIRS`、`XDG_DATA_DIRS` | /etc/xdg、/usr/share | 系统级只读默认值 |

- 隔离：每个 agent 一套 `*_HOME` 与 `XDG_RUNTIME_DIR`。共享：只读默认值放在 `XDG_*_DIRS`，所有 agent 共用一份，改过的部分才写进各自目录。
- 局限：不是所有应用都遵守（VS Code 写 ~/.vscode，Firefox 写 ~/.mozilla，Thunderbird 写 ~/.thunderbird），所以还要用挂载命名空间给每个 agent 独立 HOME。
- [xdg-desktop-portal](https://flatpak.github.io/xdg-desktop-portal/) 是沙盒应用申请文件、截图等能力的受控接口，可作为 agent 的权限检查点。

[D-Bus](https://www.freedesktop.org/wiki/Software/dbus/) 是桌面上的进程间消息总线：守护进程（dbus-daemon 或 dbus-broker）转发消息，应用注册名字（如 `org.gnome.TextEditor`）并提供方法和信号。系统总线每台机器一条，供 systemd、NetworkManager 等使用；会话总线每个登录会话一条，地址在 `DBUS_SESSION_BUS_ADDRESS`，通常是 `$XDG_RUNTIME_DIR/bus`。桌面上走会话总线的功能包括单实例转发（GApplication 检查名字是否被占用）、dconf/GSettings 设置、通知、MPRIS 媒体控制、Secret Service 密钥，以及门户。无障碍接口 AT-SPI 用一条单独的总线。

- 隔离：同一会话总线上任何应用都能调用其他应用，所以每个 agent 需要自己的总线，或经 xdg-dbus-proxy 只放行指定名字。
- 用途：AT-SPI 与 MPRIS 等是 agent 的语义接口，读控件树或控制播放比截图加点击更直接。

**整体思路（2026-11-16 小结）。** 以下串起方向一目前的论证，区分已测、分析和提案。

1. 问题（已测）：交互式桌面 agent 的桌面虚拟机约 3.5 GiB 内存，大部分时间在等模型（见 [characterization](characterization.md#第二期交互式云桌面2026-11-15-启动)）。等待期平均约 0.31 核，内存先于 CPU 成为密度瓶颈。
2. 浪费在哪（已测与分析）：约一半是客户机页缓存，约三成是进程内存；人用桌面的许多机制（显示、外壳、索引、更新、声音）对 agent 无用；动作后约 10 s 的 CPU 余波之后桌面基本空闲，vs_code 例外。
3. 为什么能换掉虚拟机（分析）：agent 桌面用无头显示、注入输入、空声音，不需要 `/dev/dri`、`/dev/input`、`/dev/snd`，共享内核的容器隔离变得可行；安卓（ReDroid、Anbox Cloud）已证明共享内核的 GUI 实例能大规模运行。
4. 怎么做（提案）：
   - 共享只读底座，文件页自动共享；匿名页靠快照克隆、KSM 等。
   - 每个 agent 用命名空间隔离应用状态（HOME、XDG、D-Bus、PID、网络、cgroup）。
   - 自写面向 agent 的无头 Wayland 合成器：按 agent 截图、输入和 seat，只在观测时出帧。
   - 生命周期：静止后冻结，观测前解冻，整桌面 checkpoint 作为可选项。
5. 新意与方法（2026-11-16 确定）：不以提出新机制为卖点，而是把成熟方案原样移植到 Linux 桌面，实测收益，并找出移植后才出现的新问题。贡献是这些新问题的实测证据、成因，以及最小修补和它的代价。见下文"移植已有方案"。
6. 待测（等全量回放结束、经同意后进行）：按进程的余波 CPU 与每步帧数；N 个隔离实例的内存曲线与 KSM 可合并比例；runc、runsc、microVM 下的容器桌面；冻结与恢复延迟；多实例并发。

**移植已有方案：方法与候选（2026-11-16 确定方法，表中"可能的新问题"均为假设）。**

方法：

- 每个方案先按原样移植，不预先修补。同一套 OSWorld 回放下同时记录收益（内存、CPU、启动或恢复时间）和损害（卡住、状态错误、任务失败、观测延迟）。
- 损害要对应到具体任务和原因。每个新问题给出触发条件、发生频率、最小修补和修补代价。
- 基线是现有的每任务一台桌面虚拟机。KSM、gVisor、CRIU 和自定义内核各自开启前单独征得同意。

| 已有方案（出处） | 移植到 Linux 桌面 | 可能的新问题（假设） |
|---|---|---|
| 共享内核的 GUI 容器（ReDroid、Anbox Cloud） | 桌面从虚拟机换成容器，分别在 runc、runsc、microVM 下运行 | 无 GPU 时 llvmpipe 软件渲染的 CPU 开销；Chromium 自带沙盒能否在 gVisor 中运行；容器内 systemd 与 D-Bus；应用假设存在的设备 |
| 静止后冻结（安卓 cached 应用、Lambda） | cgroup freezer 冻结整个桌面，观测前解冻 | 解冻后积压定时器集中触发；合成器未冻而应用被冻时被判为无响应；D-Bus 调用约 25 s 超时；IMAP 等长连接断开 |
| 快照克隆、写时复制（Firecracker、SnapStart） | 预热好的桌面做模板，克隆 N 份 | 身份重复：machine-id、随机数种子、D-Bus 与 X 认证信息、Chrome 配置锁（含主机名与 PID）；桌面写内存频繁，共享页很快失效 |
| 合并相同页（KSM） | 合并 N 个同类应用实例的相同页 | ASLR 与 JS 堆布局降低可合并比例；异构应用混部时更低 |
| 看不见就不渲染（安卓不可见 Activity、Chrome 后台标签限速） | 合成器只在截图时发帧回调 | 应用拿不到回调而卡住；截到旧画面；画面稳定的判定；截图延迟 |
| 每应用沙盒（安卓每应用 UID、Flatpak） | 每个 agent 一套命名空间 | 单实例应用；文件选择需要走 portal；multi_apps 任务的跨应用数据传递 |
| 杀进程后恢复（安卓低内存查杀加 savedInstanceState） | 内存紧张时回收桌面，需要时恢复 | Linux 应用不保存界面状态，只能外部 checkpoint；CRIU 对 Chromium、X、D-Bus 能否恢复 |
| 按截止时间调度（deflation、cgroup 权重） | 按下一次观测分配 CPU 份额 | 余波被压缩后截图时页面未加载完，任务成功率下降 |

**移植方法的补充检索（2026-11-19，web 检索；除注明外只核对到摘要、检索摘要或二手报道）。** 针对"共享内核的精简容器桌面"和"把安卓约定移植到 Linux 桌面"，补查容器桌面、安卓侧先例、冻结副作用和 agent 沙盒的内存回收。

| 方向 | 工作 | 要点 | 与本方向的关系 |
|---|---|---|---|
| 容器桌面评测 | [UI-CUBE](https://arxiv.org/abs/2511.17131) | 每个评测一个 Docker Ubuntu 桌面；16 GB 服务器约 15 个并发实例，启动不到 20 s | 又一个"容器桌面已是常规做法"的例子，面向评测，不涉及空闲回收 |
| 共享运行时 | [CUA-Sandbox](https://arxiv.org/html/2609.32750v1)（全文，2026-11-19 读） | 已初始化的应用进程跨环境共享，每条轨迹的可变状态放进私有"状态胶囊"（数据库分支、文件、浏览器配置、显示与消息总线端点），隔离靠绑定、写时复制分支和按代租约（§3）。没有说明容器运行时、命名空间、内核、X 服务器或合成器。OSWorld 每环境内存 2,653.8 → 837.3 MiB（3.17×，8 个并发环境，基线为官方 Docker，§4.3、表 6）。摘要中的 9.2×、6.20×、504× 只来自正文的 VisualWebArena 数字，与表 6（1.75×、约 4.25×、约 390×）和表 7 不一致，论文未解释。成功率在 12 组模型与基准上都不低于 Docker（表 1），无方差 | 面向 RL rollout 与评测，没有交互式服务。没有讨论等待期冻结、节流或回收，也没有报告模型等待和等待期 CPU；§3.4 的"N 个逻辑环境共用 Q 个物理槽位"是最接近的机制，但实验没给 Q。没有威胁模型、多租户和渲染的讨论。数字内部矛盾，引用时用表 6 的 OSWorld 行 |
| 实时 GUI fork | [TClone](https://arxiv.org/html/2605.17320v1)（全文，2026-11-19 读） | 容器内跑 Wayland 合成器与应用（Webtop 加 Selkies，经 HTTPS 导出画面），fork 时合成器和应用一起重建（§4.5）。匿名内存用内核模块按 VMA 写保护共享，不拷贝页；文件系统块级写时复制加延迟的页缓存写时复制；内部 TCP 用 TCP-repair，外部连接在分支时关闭；帧缓冲共享内存按分支私有（§4.1–4.5）。fork 比 KVM 最多快 4.9×、比 CRIU 快 3.4×；端到端快 1.9×、1.5×；16 个并发克隆约 9 GB，CRIU 约 14 GB（§5，i5-13400、32 GB，GPT-5.5，369 个 OSWorld 任务加 229 个 GTA 任务）。代码称录用后发布 | 目标是用户真实工作区里的分支、回滚与搜索，不是密度。冻结只在 fork 时短暂发生；没有等待期冻结、回收或密度，没有渲染、帧回调的讨论，没有多租户。**没有提 GPU、D-Bus、Chromium 沙盒、时钟与定时器、machine-id 等身份重复**，正好是我们预期移植后会遇到的问题。没有报告 fork 对任务成功率的影响 |
| 生产沙盒平台 | [DSec](https://arxiv.org/html/2609.22978v1)（全文，2026-11-19 读） | 容器、microVM、完整虚拟机后端。**暂停（§6.3）：** 只在 RL 训练任务被抢占 GPU 时，由 RL 框架主动发暂停请求；容器用 `docker pause` 冻结进程树，设 `memory.swap.max` 并调用 `memory.reclaim` 回收匿名页和文件页，恢复时 `MADV_WILLNEED` 预取再解冻；microVM 快照后终止 Firecracker 进程。没有给出暂停或恢复时延。**后台回收（§5.2、§8.4）：** 仅 microVM：virtio-pmem/DAX 去重页缓存，峰值内存降 40.2%，但瞬时 CPU 峰值从 26.5% 升到 41.4%；DAMON 冷页回收加 virtio-balloon 空闲页上报，峰值基本不变，按时间积分的内存降 21.2%；两者是不同指标，没有给出合并数字。**负载：** 只有 RL rollout 与评测（SWE-bench、Terminal-Bench 等），没有交互式服务 | 机制上已覆盖"容器冻结后 `memory.reclaim`"和"microVM 快照释放"，不能再作为新意。但没有覆盖：(1) 按 agent 循环的模型等待触发暂停，论文只把等待期用于论证 CPU 超卖（§4.1、§4.3）；(2) GUI 桌面：只说完整虚拟机用 virtio-gpu 支持 computer-use（§2.2、§3.3），没有显示服务器、渲染或截图的讨论，冻结、回收和密度评测都不含桌面负载；(3) 冻结副作用：没有讨论时钟跳变、定时器、连接超时或看门狗；(4) 暂停与恢复时延 |
| 安卓云渲染 | [DroidCloud](https://dl.acm.org/doi/10.1145/3394171.3413675)（MM '20） | 容器化高密度安卓云渲染，单台 Xeon 数百个安卓实例；实例间共享内存、编译代码和应用安装 | 安卓侧"共享内核加跨实例共享"的学术先例 |
| 安卓容器 | [Rattrap](https://ranger.uta.edu/~jrao/papers/IPDPS17_Wu.pdf)（IPDPS '17） | 用安卓容器代替虚拟机做计算卸载；启动平均快 16×，内存省 75% | 同上，面向卸载而非云手机 |
| 安卓冻结加回收 | [Ice](https://pure.ecnu.edu.cn/en/publications/ice-collaborating-memory-and-process-management-for-user-experien/)（EuroSys '23）、[TOCS '25 扩展版](https://doi.org/10.1145/3714409) | 冻结会频繁 refault 的后台进程，内存允许时解冻；帧率平均提升 1.57× | 冻结与回收协同的直接先例，目标是前台体验而不是密度 |
| 冻结副作用 | [cgroup freezer 统计补丁](https://lists.openwall.net/linux-kernel/2025/08/22/67)（2025-08） | 看门狗按系统时间计时，冻结后可能误杀健康进程；补丁只增加冻结时长统计，是否合入未确认 | 没找到对 Linux 桌面应用冻结副作用的系统评估 |
| agent 会话 | [waydriver](https://docs.rs/crate/waydriver/latest)、kwin-mcp、[deskwright](https://pypi.org/project/deskwright/) | 每个会话一个无头 Mutter 或 KWin，独立 D-Bus | waydriver 早期 README 称无头 Mutter 只在有录屏消费者拉帧时才合成，没有流时 GTK4 应用画完首帧就不再重绘。这是"不观测就不渲染"会遇到的问题的现成证据 |
| 容器内 GUI checkpoint | [criu-x11-poc](https://github.com/mikaelhg/criu-x11-poc) | 每个应用一个 Xvfb，放进同一 PID 命名空间后 dump；需要 privileged 容器，Ubuntu 的 overlayfs 补丁会让恢复崩溃 | 仍只有概念验证，没找到 Chromium 或整桌面的报告 |
| gVisor 下的 GUI | （无） | 没找到 Xvfb 或 Chromium 在 runsc 下运行的公开报告 | 仍是空白，需要实测 |

判断：

- 容器桌面、共享运行时、GUI fork、安卓侧的容器化和冻结都有先例，"移植"本身不构成新意，这与"移植已有方案"一节的方法一致：贡献落在移植后的实测和新问题。
- DSec 全文已读（见上表）：冻结加 `memory.reclaim` 的机制已有人用在生产上，但只由 GPU 抢占触发、只评测 coding 类负载，且没有时延和副作用数据。因此本方向的落点应是"按每步模型等待触发"和"桌面负载下的副作用与恢复时延"，而不是机制本身。CUA-Sandbox 和 TClone 全文也已读：两者都不处理等待期冻结或回收，都不讨论渲染、帧回调、gVisor 和多租户隔离；TClone 已证明合成器加应用可以在容器内整体 fork，但没有报告身份重复、时钟、D-Bus 等问题。因此桌面特有的部分（GUI 栈在用户态内核下的兼容性、按步冻结后的时钟与超时、按观测出帧导致的卡住、交互式等待下的冻结与恢复时延）在这三篇覆盖范围内仍是空的。
- 最便宜的第一个实验不变：同一精简桌面镜像在 runc 与 runsc 下回放 OSWorld，再加每步冻结，记录哪些任务卡住或失败及原因。

**安卓框架约定在 Linux 沙盒中的对应（2026-11-19 检索核实；多为项目代码库、问题追踪、文档或新闻，标注同前）。** 安卓的约定按执行者分三层：平台单方面执行、经工具包和桌面协议通知应用、应用自己实现。第一层（cgroup 冻结、整桌面 checkpoint、模板克隆、命名空间隔离）见上文；这里核实第二层，即 Linux 桌面上已经存在、应用不改代码也可能响应的信号。

| 安卓约定 | Linux 上的对应 | 核实结果 | 来源 |
|---|---|---|---|
| 窗口不可见即停绘 | xdg-shell 的 `xdg_toplevel` suspended 状态 | 2023-07 随 wayland-protocols 1.32 加入（xdg-shell v6），语义是"表面重绘已暂停，可以省电"。Mutter 在 GNOME 45 实现，有 45.x 的误判和 Qt 6.7 初始状态问题，后已修复；据 Mutter 问题讨论，窗口被遮挡约 3 s 后才发送。KDE Plasma 6.3 测试版中窗口被完全遮挡时不会进入该状态；sway 尚未支持 | [协议说明](https://wayland.app/protocols/xdg-shell)、[1.32 公告](https://lists.freedesktop.org/archives/wayland-devel/2023-July/042836.html)、[Mutter MR 3019](https://gitlab.gnome.org/GNOME/mutter/-/merge_requests/3019)、[Mutter #3229](https://gitlab.gnome.org/GNOME/mutter/-/issues/3229)、[Mutter #3663](https://gitlab.gnome.org/GNOME/mutter/-/work_items/3663)、[SDL #12156](https://github.com/libsdl-org/SDL/issues/12156)、[sway #9300](https://github.com/swaywm/sway/issues/9300) |
| 同上，客户端是否响应 | GTK4、WebKitGTK、Chromium、winit | GTK4 有 `GDK_TOPLEVEL_STATE_SUSPENDED`，帧时钟在帧不可见时可自行停止；在非 Wayland 后端与最小化同时设置。WebKitGTK 用它把视图标为不可见、停止帧时钟。Chromium 有按遮挡节流渲染的逻辑，Ubuntu 的问题报告称 Chrome 收到该状态会停止工作（Chromium 源码未核）。**GTK3 没有这个常量**（Mozilla bug 2063202），因此基于 GTK3 的 Firefox、Thunderbird、LibreOffice（gtk3 后端）、GIMP 不能经 GDK 收到；Firefox 是否另行处理未找到资料。Xwayland 应用收不到 | [GDK 文档](https://docs.gtk.org/gdk4/class.FrameClock.html)、[GTK gdktoplevel.h](https://gitlab.gnome.org/GNOME/gtk/-/blob/main/gdk/gdktoplevel.h)、[WebKit 提交](https://www.mail-archive.com/webkit-changes@lists.webkit.org/msg224653.html)、[Mozilla 2063202](https://bugzilla.mozilla.org/show_bug.cgi?id=2063202)、[Ubuntu 2174026](http://www.mail-archive.com/desktop-bugs@lists.ubuntu.com/msg836236.html)、[winit PR 4709](https://github.com/rust-windowing/winit/pull/4709) |
| `onTrimMemory` | GLib 的 `GMemoryMonitor`，沙盒内经 xdg-desktop-portal 的 `org.freedesktop.portal.MemoryMonitor` | 2019 年同时进入 GLib 与 xdg-desktop-portal；后端是 low-memory-monitor 守护进程，按级别发 `LowMemoryWarning`，低级别时应用应释放缓存等非必要资源。任何调用 `g_memory_monitor_dup_default()` 的 GLib 应用可自动获得；**没有找到具体哪些应用监听的资料**，需要逐个查源码或实测 | [GLib 提交](https://mail.gnome.org/archives/commits-list/2019-July/msg11223.html)、[PyGObject 文档](https://api.pygobject.gnome.org/Gio-2.0/interface-MemoryMonitor.html)、[ashpd](https://docs.rs/ashpd/latest/src/ashpd/desktop/memory_monitor.rs.html) |
| 后台限制 | `org.freedesktop.portal.Background` | 只管沙盒应用能否无窗口运行和是否开机自启（v2 增加 `SetStatus`），GNOME 用它填充"后台应用"列表；**不做节流或冻结**，只对 Flatpak 一类沙盒应用有效 | [门户文档](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Background.html)、[GNOME 设计](https://gitlab.gnome.org/Teams/Design/os-mockups/-/issues/191) |
| 进程冻结 | systemd `systemctl freeze`/`thaw` | 基于 cgroup v2 的 `cgroup.freeze`，cgroup v1 不支持；只支持 service、scope、slice 类单元（第三方手册，未对照官方）。GNOME、KDE 已把每个应用放进独立 scope，可以按应用冻结 | [systemd-devel 讨论](https://lists.freedesktop.org/archives/systemd-devel/2021-April/046302.html)、[systemd 提交](https://gitea.basealt.ru/shaba/systemd/src/commit/d9e45bc3abb8adf5a1cb20816ba8f2d2aa65b17e)、[RHEL bug 1830861](https://bugzilla.redhat.com/show_bug.cgi?id=1830861) |
| `onSaveInstanceState` | `xdg-session-management-v1` 协议，加上工具包层的状态保存 | 协议 2020 年提出，2026-03-23 合入，随 wayland-protocols 1.48（2026-04）发布；Chromium 已加入支持，KDE 与 GNOME 在实现中，Qt 6.12 加 KDE 6.7 有用户报告可用。GTK 的会话保存没赶上 4.22（4.22 有标为不稳定的 `GtkApplication::restore-window` 信号），预计 4.24。协议只恢复窗口（位置、大小等），应用内部状态仍要应用自己存 | [Phoronix 1.48](https://www.phoronix.com/news/Wayland-Protocols-1.48)、[Phoronix Chromium](https://www.phoronix.com/news/Chrome-XDG-Session-Management)、[GTK MR 7370](https://gitlab.gnome.org/GNOME/gtk/-/merge_requests/7370)、[GTK 文档](https://docs.gtk.org/gtk4/signal.Application.restore-window.html)、[Phoronix GTK 黑客松](https://phoronix.com/news/gtk-fosdem-2026-hackfest)、[KDE 讨论](https://discuss.kde.org/t/session-management-with-qt/47876)、[GNOME 计划](https://discourse.gnome.org/t/introducing-the-session-save-restore-initiative/33127) |

判断：

- 第二层的信号确实存在，但覆盖很不均匀。suspended 状态只对 Wayland 原生、基于 GTK4、WebKitGTK 或 Chromium 的客户端有效；OSWorld 的 LibreOffice、GIMP、Thunderbird 走 GTK3，收不到。而且现有 OSWorld 虚拟机用 Xorg，这些协议一个都用不上，必须先换成 Wayland 合成器。
- 低内存信号的机制完整，但实际有多少应用响应没有资料，只能实测。后台门户与冻结无关，不必移植。
- 会话保存协议刚进入主线，只管窗口几何，替代不了 `onSaveInstanceState`；应用内部状态仍要靠整桌面 checkpoint 兜底。
- 因此"把安卓框架约定搬进 Linux 沙盒"的可测问题是：在自写的无头合成器下，对 OSWorld 用到的每个应用依次发 suspended（或停发帧回调）、低内存信号，再做 cgroup 冻结，测各自的 CPU 余波、内存变化和解冻后的功能错误。结果是一张"安卓约定在 Linux 桌面上的覆盖率"表；没有约定的部分，用平台硬冻结兜底，并测它的代价。

**负载：OSWorld 够不够做大规模研究（2026-11-16 检索，只核对到摘要或二手资料）。**

OSWorld 1.0 的局限：

| 缺口 | 影响 |
|---|---|
| 会话短：每任务几分钟、约 30 次工具调用，从干净快照开始 | 测不到状态积累、长期内存增长、长连接超时；冻结的问题会被低估 |
| 没有到达过程、并发、空闲分布 | 无法回答同时有多少桌面、各自空闲多久 |
| 所有任务同一镜像 | 高估 KSM 合并与快照克隆的共享比例 |
| 部分任务依赖外网 | 结果不完全可复现 |
| 单 agent、无人在场 | 测不到多个 agent 与用户共用一个桌面 |

它适合做"任务单元加正确性检查"：每个任务有评测器，可以逐个核对移植的方案把哪些任务做坏了。

补充来源：

- [OSWorld 2.0](https://huggingface.co/papers/2606.29537)：108 个长周期工作流，人类完成时间中位数约 1.6 小时，平均约 318 次工具调用（1.0 约 30 次）。网站自托管，有跨应用流程；超过 2 小时的任务几乎都失败（[Snorkel](https://snorkel.ai/research-paper/os-world-2/)，[排行榜](https://leaderboard.steel.dev/leaderboards/osworld-2.md)）。它补上了"会话短"和"依赖外网"。[OS-Marathon](https://arxiv.org/html/2601.20650) 是长周期重复任务。
- 到达与并发：没找到计算机使用 agent 的公开生产 trace。最接近的是 [GitHub Copilot 编码 agent 生产 trace](https://www.microsoft.com/en-us/research/wp-content/uploads/2026/08/ghcp_traces-6.pdf)（[arXiv 2608.00101](https://www.alphaxiv.org/abs/2608.00101)，1300 万会话），以及 [Agentic AI Workload Characteristics](https://arxiv.org/pdf/2605.26297)（Claude Code trace）。[OSWorld-Human](https://arxiv.org/abs/2506.16042) 研究 OSWorld 上 agent 的时间效率，是 benchmark 研究而非生产 trace。
- VDI 与云桌面：没找到公开 trace。Horizon 等产品能导出会话时长与空闲时长（[Omnissa 文档](https://docs.omnissa.com/nl-NL/HorizonDaaSTenantAdministration-V9.2.0/ReportsPage?hl=nl-NL)），只能从自有部署获取。

拟定的负载组合（提案）：

1. 正确性：OSWorld 1.0 加 OSWorld 2.0 的评测器。
2. 单桌面的时间节奏：回放 1.0 与 2.0 的轨迹；2.0 是否公开带时间戳的轨迹尚未确认。
3. 规模：到达过程与会话长度借用 Copilot trace 的分布，混合不同应用与镜像，预先灌入积累状态。论文中需说明这是从编码 agent 借来的假设。

为什么这些问题可能是 Linux 桌面特有的（判断）：安卓应用按"随时会被冻结、被杀"编写，会主动保存状态、停止渲染；serverless 快照的对象是无窗口、无长连接、无会话总线的函数。Linux 桌面应用默认自己持续运行、始终可见、独占机器。移植后出问题的地方，预期集中在这些前提上：可冻结、实例唯一、有人观看、会话持续。这可能成为论文主线。

**CXL 能否用于大规模桌面沙盒（2026-11-16 检索；TrEnv-X 读了 arXiv HTML 全文，其余只看摘要或二手资料）。** 瓶颈是内存，而桌面大部分时间在等模型，空闲内存适合放到 CXL 上。三种用法：

| 用法 | 对桌面的作用 | 已有工作 |
|---|---|---|
| 冷页下放 | 等待或冻结中的桌面页下放到 CXL，本地 DRAM 只留活跃桌面 | [TPP](https://arxiv.org/pdf/2206.02878)（Meta，部分合入 Linux 5.18）；[Equilibria](https://arxiv.org/html/2602.08800)（2026，多租户容器分层内存的公平与抖动控制） |
| 内存池 | 多机共用内存池，减少单机内存闲置 | [Pond](https://www.microsoft.com/en-us/research/wp-content/uploads/2022/10/Pond-ASPLOS23.pdf)（Azure，ASPLOS'23，面向虚拟机，DRAM 成本约降 7%） |
| 跨机共享模板 | 预热桌面模板在 CXL 上只存一份，各机写时复制克隆 | [CXLfork](https://tianyin.github.io/pub/cxlfork.pdf)（ASPLOS'25，跨节点零拷贝 fork，本地内存平均降 87%）；[TrEnv](https://madsys.cs.tsinghua.edu.cn/publication/trenv-transparently-share-serverless-execution-environments-across-different-functions-and-nodes/SOSP24-huang.pdf)（SOSP'24） |

[TrEnv-X](https://arxiv.org/abs/2509.09525)（TrEnv 的扩展版，v2 2026-03）与本方向最近，要点：

- 负载：作者自选的 6 个开源 agent（Blackjack、Bug fixer、LangChain map-reduce、Browser-Use 购物助手、OWL 博客摘要、OpenManus 游戏设计），因为没有标准 agent benchmark；用真实 LLM 运行的 trace 回放，推理由模拟服务器按原延迟返回（§3、§9.6）。没有计算机使用桌面或办公应用。
- 机制：`mm-template` 把 CXL 或 RDMA 上去重后的 checkpoint 表示为内核页表模板，挂载只复制元数据，CXL 页写保护后写时复制（§5.1）；沙盒清理后放回池子复用（§5.2）；microVM 用改过的 Cloud Hypervisor，只读基础镜像经 virtio-pmem 绕过客户机页缓存，宿主只存一份（§6.3）。
- 浏览器共享（§6.2）：一个浏览器实例放在独立沙盒里，多个 agent 经同一个 CDP 端点各开标签页。agent 之间不隔离，作者假设它们不处理敏感数据，并在 §8.1.2 承认可能互相共享 cookie。
- 硬件与数字：真实的 128 GB 三星实验 CXL 设备，RDMA 用 Soft-RoCE（§9.1）。20 个物理核上并发 200 个 agent 实例；相对 E2B，P99 延迟最多降 58%，内存最多降 61%（§9.6、§11）。
- 没有涉及：显示服务器与 GUI 桌面、有头浏览器的图形问题、LLM 调用之间的空闲处理（只有通用的 10 分钟保活）、冻结、长会话。

与本方向的边界（判断）：

- TrEnv-X 已覆盖"跨机共享内存模板"和"消除虚拟机重复页缓存"，不能再作为我们的新意；我们要把它当作基线或已有方案移植。
- 它的浏览器共享以放弃 agent 间隔离为代价；我们要求每个 agent 隔离，并覆盖整个桌面（合成器、多个应用、会话总线）。
- 它没有处理桌面特有的部分：观测—等待节奏下的冻结与按观测出帧、积累状态的长会话、实例身份唯一性。这些仍是可能的空位。

把 CXL 移植到桌面后可能出现的新问题（假设）：

- 观测前要把下放的页拉回 DRAM，截图延迟变长。
- 动作后的余波会访问大量冷页，访问 CXL 拖慢余波，截图时页面可能未就绪。
- 桌面写内存频繁，CXL 上的共享模板很快变成私有页，共享比例可能远低于无状态函数。

条件：本机没有 CXL。可用双路服务器的远端 NUMA 节点模拟延迟，或用 QEMU CXL 模拟（只验证功能，延迟不真实）；云上 CXL 实例尚未调查。CXL 适合作为扩展方向，不作第一阶段主线。

**探索：agent 桌面不需要显示（2026-11-15，未验证）。** 人用桌面持续合成画面，而 agent 只在观测时读取一帧，或者只读语义结构。"不需要显示"可以分四级：

| 级别 | agent 看到什么 | 可以去掉什么 | 已有工作或证据 |
|---|---|---|---|
| L0 无头但持续渲染（现状） | 截图 | 物理显示器 | Xvfb、VNC、OSWorld 虚拟机 |
| L1 按观测渲染 | 截图，只在 agent 要观测时合成一帧 | 观测之间的合成与重绘：动画、光标闪烁、视频；可能还有缓冲区内存 | Wayland 规范允许合成器不给被遮挡窗口发 frame callback，[KWin](https://bugs.kde.org/show_bug.cgi?id=464217)、Mutter、Chromium、GTK、Qt 已有相应行为和变通；[waydriver](https://docs.rs/crate/waydriver/latest) 注明无头 Wayland 下 GTK4 只画首帧、之后不重绘，但仍能读 AT-SPI 树。没有找到按 agent 观测驱动帧时钟的系统 |
| L2 只要语义 | 无障碍树（AT-SPI、UIA），按元素操作 | 合成器、渲染和截图通路；应用仍需布局 | OSWorld 原论文中 GPT-4 只用无障碍树成功率 12.2%，高于只用截图的约 5.3%（二手资料，2024 年模型）；waydriver、gui-user 等经 AT-SPI 驱动应用；有些工具包只有窗口被映射后才发布无障碍树 |
| L3 不要 GUI | 应用 API | 整个桌面 | [UFO2](https://arxiv.org/abs/2504.14603)（Windows 上 GUI 与原生 API 混合，代理在隔离的虚拟桌面里运行）；[API Agents vs. GUI Agents](https://arxiv.org/abs/2503.11069)（ICML '25，OSWorld 27 个办公任务上混合方式把 GPT-4o 从 16.3% 提高到 22.4%）；[Windows agent workspace](https://support.microsoft.com/en-us/windows/ai/ai-features/experimental-agentic-features)（agent 在单独的 Windows 会话和账户中运行） |

本项目已有数据中与显示相关的部分（单次快照，见 [characterization](characterization.md#第二期交互式云桌面2026-11-15-启动)）：gnome-shell 399 MiB、Xorg 180 MiB、xdg-desktop-portal 124 MiB、gjs 111 MiB，按 RSS 合计约 0.8 GiB（含共享页），而任务应用本身 soffice.bin 为 279 MiB。每步截图 0.5–1.6 MB，1080p 截图在 Qwen3.5-2B 中约 2,040 个视觉 token（Visual Token Routing 的二手数字）。

待回答的问题：

- 同一批轨迹在 L0、L1、L2 下回放，CPU、内存和每步延迟分别差多少；有多少是"只为产生没人看的像素"而花的。
- L1 的正确性：不重绘时，无障碍树和应用内部状态是否仍及时更新；观测时补画一帧的延迟和画面是否过时。
- L2 的覆盖率：GIMP、画布类网页等无障碍树信息不足的应用占多少任务。
- 与隔离的关系：L1、L2 下隔离边界只需导出观测接口，合成器和 X 或 Wayland 套接字都留在隔离域内（接上一节）。

当前模型的趋势是直接看截图（如 Claude computer use），L2 的成功率优势来自 2024 年的模型，需要用当前模型重新确认。

**OSWorld 任务中有多少必须用 GUI（2026-11-15，本项目分析）。** 对 Claude Sonnet 4.5 公开轨迹覆盖的 360 个任务，逐个按评测器检查的终态判断是否存在不经 GUI 的做法：先按评测器读取的结果类型分类，再人工复核 34 个可疑任务以及全部 multi_apps、thunderbird、vs_code、vlc、os 和 chrome 任务。脚本与逐任务结果见 [osworld-gui-necessity.py](../benchmarks/osworld-gui-necessity.py) 和 [osworld-gui-necessity-results.json](../benchmarks/osworld-gui-necessity-results.json)。

| 类别 | 任务数 | 占可完成任务 | 含义 |
|---|---:|---:|---|
| 无需 GUI | 270 | 80.8% | 终态是文件、配置或系统设置，可用库（python-docx、openpyxl、python-pptx、LibreOffice headless 或 UNO、ImageMagick、ffmpeg、mutagen）、命令行、配置文件或应用脚本接口完成；其中 10 个仍需理解图像或视频内容 |
| 只需浏览器 | 55 | 16.5% | 需要网页内容或浏览器状态，可经 DevTools 协议或 HTTP 完成，不需要桌面 |
| 需要桌面会话 | 3 | 0.9% | 需要剪贴板、已打开的窗口或全屏状态，但不需要看画面 |
| 需要 GUI | 6 | 1.8% | 评测器读取实时界面状态（例如 Thunderbird 账户配置页、编辑器收件人栏），或要求交付终端截图 |
| 不可完成（排除） | 26 | | OSWorld 标为 infeasible |

解读与限制：

- 这只说明"存在不经 GUI 的做法"，不说明 agent 能找到，也不保证结果与 GUI 操作完全一致。例如 Thunderbird、Chrome 运行时会覆盖配置文件，需要先关闭应用。
- 有选择偏差：OSWorld 的任务必须能被脚本判分，因此天然偏向终态落在文件和配置里的任务；虚拟机里的应用也都是可脚本化的开源软件。因此它不能说明真实负载中必须用 GUI 的比例很低，只能说明 OSWorld 不足以支撑"必须用 GUI"的论证。
- 与之对照，公开轨迹中的 agent 几乎全程用 GUI 操作：8,877 个动作里点击 3,621 次、按键 1,902 次、输入 1,260 次，步间隔中位数 24 s。对这批任务而言，"API 优先、GUI 兜底"可能在效率上有很大空间，这与 [API Agents vs. GUI Agents](https://arxiv.org/abs/2503.11069) 的混合方式结论一致。
- 对系统设计的含义（待验证）：OSWorld 这类负载约 97% 只需要"文件系统和工具加无头浏览器"，桌面只是兜底。若要论证桌面方向，需要真实负载中必须用 GUI 的任务比例，这一数据目前没有。

**浏览器状态是否需要连续存在。** 再看 55 个"只需浏览器"的任务，评测器检查的终态落在三处：

| 终态在哪里 | 任务数 | 释放浏览器后如何恢复 |
|---|---:|---|
| 网页内容只用来生成文件或设置 | 22 | 不需要恢复，浏览器只在读取时存在 |
| 当前标签页（URL、查询参数、页面内容） | 29 | 用 URL 重新打开，再配合 cookie；例如 Steam 购物车存在服务器端，凭 cookie 即可恢复 |
| 浏览器配置文件（书签、标签页会话） | 4 | 配置目录本身就在磁盘上 |

因此这批任务的浏览器状态可以表示为"URL 加配置目录（cookie、本地存储）"，浏览器进程不必在模型等待期间常驻。跨运行保存配置目录已有产品做法：[Browserbase Contexts](https://docs.browserbase.com/features/contexts) 在会话之间保存 cookie 与应用数据；[Steel Profiles](https://docs.steel.dev/overview/profiles-api/overview) 恢复 cookie、存储和扩展，单个配置上限 300 MB，30 天不用即删除。它们针对的是跨运行的持久化，会话进行中仍保持浏览器常驻。

把配置目录当作工作区状态，SandWeaver 的池循环（等待期间归还 worker、保留工作区）就可以覆盖这批浏览器任务，再加上无需 GUI 的任务，约占 OSWorld 可完成任务的 97%。待验证的风险：

- 一步之内仍需活页面（输入、点击、等待脚本执行）。
- 部分站点的状态不在 URL 里（单页应用的内存状态、POST 提交的筛选），重新加载会丢失。
- 重新加载可能触发反爬验证，短期令牌可能过期，动态内容可能变化。
- 恢复成本：无头浏览器冷启动加页面重新加载约需数秒，与 24 s 的步间隔中位数相比是否划算，正是决策图要回答的问题。
- 同样受评测偏差影响：OSWorld 的浏览器任务按 URL 判分，天然偏向状态在 URL 里的任务。

**"没人看却仍在运行"的开销：方案与已有工作（2026-11-16）。** 依据是 9 个应用域试点的等待期 CPU 分段（见 [characterization](characterization.md#第二期交互式云桌面2026-11-15-启动)）：多数应用在动作后约 10 s 内有 0.3–1.2 核的余波，之后降到 0.03–0.18 核；vs_code 整个等待期稳定在约 0.8 核。按等待时长加权，平均约 0.31 核。

先说一个限制本方向价值的判断（估算，未实测）：在常见的每核 4 GiB 宿主上，以每台 3.6 GiB、等待期 0.31 核计，内存先于 CPU 耗尽，大约在 CPU 用到三成时内存就满了。所以单独节省等待期 CPU 不能提高密度，除非同时解决内存。动作期间 1–2 核的峰值靠统计复用摊开，这一点也待用多台并发测量确认。

| 方案 | 做法 | 已有工作（标注核对深度） | 空白与风险 |
|---|---|---|---|
| A. 按下次观测截止期调度 | 等待期把虚拟机 cgroup 的 `cpu.weight` 或 `cpu.max` 调低，让余波用空闲核慢慢完成；下次截图前检查已静止（CPU 回落或画面稳定），再截图 | 资源缩容而不抢占：[Resource Deflation](https://lass.cs.umass.edu/papers/pdf/eurosys19-deflation.pdf)（EuroSys '19，摘要）、[Cloud-scale VM Deflation](https://arxiv.org/abs/2006.00508)（HPDC '20，摘要），由提供方压力驱动，不看 agent 节奏。[Citrix WEM](https://docs.citrix.com/en-us/workspace-environment-management/service/using-environment-management/system-optimization/multi-session-optimization) 在用户断开 1 分钟后降低会话的 CPU 和 I/O 优先级（文档）。[AgentCgroup](https://arxiv.org/abs/2602.09345) 每次工具调用一个子 cgroup，按优先级节流（全文）。[DSec](https://arxiv.org/abs/2609.22978) 报告约 90% 的容器和 microVM 沙盒平均只用请求 CPU 的 5% 以内，因而超卖（全文 §4.3）。截图前等待稳定在测试工具中很常见，如 Silk Test 的 [WaitForScreenshotStable](https://www.microfocus.com/documentation/silk-test/200/en/silktestclassic-help-en/GUID-1A244B68-C7A0-40FD-A2D5-B48131AB7B12.html)。反方向利用空闲的有 [PASTE](https://arxiv.org/abs/2603.18897)：在模型生成时用空闲核投机执行工具（摘要） | 没找到以"下一次观测时间"作为每步截止期来调度桌面的工作。机制本身是现成的 cgroup 控制，新意只在策略和测量。风险：模型等待时间不可预知，余波被拉长后可能赶不上下次截图，需要静止检测兜底 |
| B. 静止后冻结 | 检测到 CPU 回落后用 `cgroup.freeze` 或 QEMU `stop` 冻结，下一个动作到来时恢复 | [Android cached apps freezer](https://source.android.com/docs/core/perf/cached-apps-freezer)：进入缓存状态 10 s 后用 cgroup v2 freezer 冻结应用（文档）。AWS Lambda 在两次调用之间冻结执行环境（[AWS 博客](https://aws.amazon.com/blogs/compute/operating-lambda-performance-optimization-part-1)，机制未公开）。厂商在两次运行之间或等待审批时暂停沙盒：[Freestyle](https://www.freestyle.sh/blog/product/ai-agent-waiting-for-approval-sandbox-state)、[Beam](https://www.beam.cloud/use-cases/computer-use)（厂商页）。[AgentCgroup](https://arxiv.org/abs/2602.09345) 在压力过大时冻结。人用桌面空闲合并：[LiteGreen](https://www.usenix.org/legacy/events/atc10/tech/full_papers/Das.pdf)（ATC '10）、[Jettison](https://www.cs.cmu.edu/~satya/docdir/bila-eurosys2012.pdf)（EuroSys '12，只迁移空闲工作集）、[Oasis](https://research.ibm.com/publications/oasis-energy-proportionality-with-hybrid-server-consolidation)（摘要） | 机制完全现成，只是粒度（每步约 24 s）没人测过。本项目数据显示，静止之后多数应用只剩 0.03–0.18 核，CPU 上省得很少，vs_code 是例外。冻结真正的价值在于为内存回收创造前提，而那条路很拥挤（Desiccant、FaaSMem 等）。风险：恢复后客户机时钟跳变、定时器积压、网络连接超时 |
| C. 让桌面知道"没人在看" | 观测之间把输出标为不可见，让应用自己节流（浏览器隐藏页节流、合成器不发帧回调）；截图时强制补画一帧 | Chrome 隐藏页定时器节流：页面已加载完时 10 s 后启用强化节流，Chrome 133 起在节能模式下冻结 CPU 密集的后台标签页（[Chrome 博客](https://developer.chrome.com/blog/freezing-on-energy-saver)、[timer throttling](https://developer.chrome.com/blog/timer-throttling-in-chrome-88)）。Wayland 合成器可以不给被遮挡窗口发 frame callback（[Weston MR 1524](https://gitlab.freedesktop.org/wayland/weston/-/merge_requests/1524)、[KWin 467032](https://bugs.kde.org/show_bug.cgi?id=467032)）。VDI 断开后 DWM 停止合成，见 [社区帖子](https://communities.vmware.com/t5/Horizon-Desktops-and-Apps/IE-CPU-Utilisation-shoots-to-100-on-disconnected-session/td-p/1797193)（单一帖子，未经证实）。也见上文 L1 | 没找到按 agent 观测驱动可见性或帧时钟的系统。风险：客户端阻塞等待帧回调导致卡死（[Firefox](https://bugzilla.mozilla.org/show_bug.cgi?id=1711244)、[Weston EGL](https://gitlab.freedesktop.org/wayland/weston/-/issues/597)），恢复后卡顿。OSWorld 虚拟机用 Xorg，没有帧回调机制，要用最小化或遮挡来触发应用节流。收益大小未知：需要先拆出余波里有多少是渲染和定时器，有多少是真实工作 |
| D. 精简常驻服务 | 去掉对 agent 无用的服务（snap-store、fwupd、packagekitd、evolution-alarm 等） | [CUA-Lite](https://rdi.berkeley.edu/blog/cua-lite) 已把 OSWorld 桌面容器化，[CUA-Sandbox](https://arxiv.org/abs/2609.32750) 共享运行时、每环境内存降 9.2×（摘要）（见上文） | 工程，不是研究点。空闲 top 中 evolution-alarm 偶尔排在前面，可以顺带量化 |

判断：

- 四条的机制都有先例。A 和 C 的组合（余波按截止期慢跑，加上不可见时让应用自己节流）是检索范围内没找到的部分，但贡献偏策略，CPU 收益也受上面内存约束的限制。
- 更有说服力的做法是把它和内存放在一起：冻结只是前提，关键在于冻结后能回收多少内存、恢复时延多少。这又回到已经拥挤的内存回收方向，需要找出桌面特有的部分，例如页缓存占一半、77% 的 anon 是透明大页。
- 检索局限：只做了 web 检索，多数条目只看到摘要或文档；软实时调度、VDI 密度规划和合成器节能方面可能还有更接近的工作，尚未系统检索。

下一步需要的测量（都是新的桌面实验，等全量回放结束后再做）：

1. 动作后 0–10 s 在客户机内逐进程采样，拆出余波来源。
2. 方案 A：在不同 `cpu.max` 下回放，测余波完成时间和截图是否与原速一致。
3. 方案 B：测每步冻结和恢复的延迟，以及恢复后时钟和网络的表现。
4. 多台并发：测实际瓶颈是 CPU 还是内存。

**方向二：沙盒与推理联合调度。** 推理侧的工作已经很密集。

| 工作 | 管理的资源 | 是否管理沙盒内存或生命周期 |
|---|---|---|
| [SpecBox](https://arxiv.org/abs/2607.23933) | LLM 生成期间预先启动可能用到的沙盒；P99 延迟最多降 2.9×，峰值内存比常驻沙盒少 45.9% | 管理沙盒启动时机 |
| [MARS](https://arxiv.org/abs/2604.26963) | GPU KV 准入，避免 KV 反复驱逐 | 否 |
| [TAO](https://arxiv.org/abs/2610.37230) | 按工具返回的就绪时间决定 GPU 准入和放置 | 摘要未提及 |
| [Continuum](https://arxiv.org/abs/2511.02230) | 工具调用期间的 KV TTL | 否 |
| [Agentic CPU-GPU Scheduling](https://arxiv.org/abs/2607.22242) | 工具放在 CPU 还是 GPU 上执行 | 否 |

判断：确实没有工作把沙盒内存和 KV 当作同一预算管理，但"沙盒和推理协同"这个大方向已被 SpecBox、TAO 覆盖。云上推理集群和沙盒集群通常分开部署，统一预算只在单机自托管或 RL rollout 节点上才成立，动机较弱。本机 RTX 4050（6 GB）可以用 vLLM 跑小模型实测 KV，但测不到云端规模。

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
- **候选贡献是回答 ARIES §5.3 的问题。**（2026-11-15 更正：Crab 已按轮次用 eBPF 区分恢复相关状态，并据此选择 checkpoint 粒度，见[相关工作矩阵](#相关工作矩阵2026-11-15-核对)。下面这条只剩测量价值。）在真实轨迹上测每个批次边界留下的写层文件和进程，后续批次实际读取了多少，并据此区分可丢弃、可重建和必须驻留的状态。已有的 `lease_state` 探测只记录归还时的状态量，后续读取尚未测量。
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

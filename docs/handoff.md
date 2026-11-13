# SandWeaver 研究交接

## 研究问题

SandWeaver 是本地 Docker worker 调度器。OpenHands 在 worker 外运行，通过 Unix socket 调用工具。项目文件保存在宿主工作区，工具执行容量按租约分配。同一会话在模型等待期间可以保留工作区独占权，归还 worker 或将它标记为可回收。每个租约有独立的 mount/PID namespace 和 OverlayFS 写层。归还时销毁租约的临时状态。重置失败时淘汰 worker，旧容器的删除未确认前继续保护工作区。当前原型面向可信本地任务，跨不可信租户的隔离仍待验证。[架构](architecture.md)

研究范围先收在单机、固定 worker 容量、多轮 coding agent。Agent 可能在一次工具批次里改 lockfile、安装或升级依赖，然后进入模型等待。归还 worker 后，下一批工具可能在另一 worker 执行，仍应拿到该会话实际装好的依赖版本。包下载缓存省下载，已安装环境缓存还能省安装和构建。选用后者需要绑定正确版本，核对平台、工具链和 ABI，并管理引用、存储预算和淘汰。后台服务、活跃连接、未完成安装和仍需使用的临时文件会约束回收。[依赖设计](lease-and-dependencies.md)

核心问题是 **依赖版本变化和缓存命中成本，是否会改变同一场排队竞争中的回收决策**。托管 serverless sandbox 把底层容量管理交给平台，应用仍需决定哪些会话状态要跨执行环境保留。

## 已测结果与适用范围

- 一次 OpenHands/DeepSeek Flash Python 修复通过 5 项独立测试。模型客户端调用累计约 13.776 s，占 14.328 s 全会话租约的 96.2%。客户端时间含 SDK 和网络。这条轨迹只说明潜在归还窗口，实际可回收时间取决于状态依赖。[Agent 观测](agent-observation.md)
- 两个热 worker、模拟 830 ms 模型等待且有竞争时，按需回收把短任务领租请求至首条命令返回的 P50 从 1015 ms 降到 160 ms。原会话模型调用结束至下一条工具返回的 P95 从 70 ms 增到 144 ms。每组 9 轮。真实轨迹和更高并发下的收益待测。[Worker 实验](worker-reuse.md#openhands-租约策略对照)
- 只读组件原型验证了预备依赖 v1 → v2 → v1 的换绑，以及替换 worker 后的版本恢复。对 humanize 4.12.3 的 30 轮小包对照，发出领租到首条验证完成的 P50 为挂载 92.43 ms、离线重装 260.20 ms，配对节省中位数 165.90 ms。预下载和首次准备组件在计时之外。会话中动态发布环境、引用管理和淘汰仍是设计提案。[组件实测](lease-and-dependencies.md#组件原型实测)

## TrEnv 作为外部对照

- SOSP 2024 的 **TrEnv** 已经实现跨函数复用热 sandbox。§4.2.1 和图 9 描述了保留通用挂载、清除旧调用的写入、切换预备的函数专属 OverlayFS 并池化这些文件系统。§4.1 的 `mm-template` 是另一层机制，它映射函数初始化后的共享只读快照页，通过 CoW 私有化写入。CXL 路径直接读共享页，RDMA 路径按需取页。[原论文](https://madsys.cs.tsinghua.edu.cn/publication/trenv-transparently-share-serverless-execution-environments-across-different-functions-and-nodes/SOSP24-huang.pdf)
- **TrEnv-X v2** 扩展到 microVM、共享浏览器和页缓存优化。六种 agent 中三种用浏览器。最接近 coding agent 的 Bug Fixer 执行一段 Python 并向模型请求修复建议。其静态流程未覆盖会话中安装、升级、换 worker 后继续验证依赖版本。[TrEnv-X §3.2、§6、§9.6](https://arxiv.org/html/2509.09525v2)
- TrEnv 已覆盖预备依赖的快速切换。SandWeaver 的候选贡献在于 **恢复会话中改变的依赖，并用恢复成本指导租约回收**。跨 agent 重分配空闲 sandbox 也有 aShare 等先例。[相关工作](research.md)
- 本地可以用 OrbStack 做 **TrEnv 式文件系统换绑对照**。只测文件系统无需 RDMA/CXL。运行作者发布的完整 TrEnv 时，官方流程用 DAX 或软件 RDMA（RXE）生成内存模板。纯文件系统入口在发布代码中尚未确认。[作者部署说明](https://github.com/switch-container#run-trenv)

## 换机器后从哪里开始

1. 拉取仓库，按[运行与验证](operations.md)安装环境、构建 demo 镜像、运行 `python tests/smoke.py`。仅用调度器时 OpenHands 是可选依赖。真实模型实验使用 **OpenRouter DeepSeek Flash**，除非明确改选模型。密钥由宿主环境提供，保持真实工作区、socket 和生成会话数据在 Git 外。
2. 先做最小依赖实验。选一个 Python 项目和两个固定版本的 wheel。让 A 安装 v1、升级到 v2、进入模型等待并让出 worker，B 使用容量。强制 A 在不同 worker 上恢复，断言实际导入版本和路径并跑项目测试。回退到 v1 再验证一次。把已安装环境显式绑定到会话版本。
3. 对照用本地 wheel 重装、恢复会话私有已安装目录、挂载共享只读环境。记录环境准备及重建成本、磁盘占用、版本正确性和恢复到首条测试通过的延迟。固定 worker 数量和工具轨迹，再比较全会话持租、竞争时回收和按恢复成本回收，观察缓存命中与未命中时回收决策是否翻转。
4. 并行准备完整 TrEnv 原版验证。优先找可启动自定义内核的 x86‑64 Linux。作者只在 Intel 上测试过，部署以 Ubuntu 22.04 为基准，使用修改后的 Linux、CRIU、runc、containerd 和 faasd。WSL2 支持自定义内核，配置影响该 Windows 用户的全部 WSL2 发行版。先验证内核启动、`/dev/pseudo_mm` 与 RXE，再跑官方样例，最后把两批工具接到同一实验负载。独立 Linux VM 更便于测试和回退。[WSL2 配置](https://learn.microsoft.com/en-us/windows/wsl/wsl-config) · [TrEnv 安装](https://github.com/switch-container#software-installation)

当前完整 TrEnv 尚未运行。本机 OrbStack 是 Linux arm64。Apple Silicon 上可用 QEMU 软件模拟 x86 做功能验证，性能数字会受模拟开销影响。Windows 实验机使用 SSH 别名 `gpu-wsl`，本轮因本机 Tailscale 失效而连接超时，远端未开始部署。Azure 没有跑出实验结果。East US 被订阅地区策略拒绝，当时可选区列表为 France Central、Sweden Central、Norway East、Belgium Central 和 North Central US。后续看到的 Basv2 为 AMD x86‑64，持续负载受 CPU 积分限制，可考虑做功能验证。

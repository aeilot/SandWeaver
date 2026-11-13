# Coding agent 的执行容量与依赖管理

**研究问题**：在固定资源预算和明确的隔离要求下，当 coding agent 持续修改代码、安装依赖、切换版本并产生构建产物时，怎样提高正确完成的任务吞吐，同时控制新任务和恢复会话的尾延迟？

## 四项研究问题

| 问题 | 待验证的决策 | 对照和指标 |
|---|---|---|
| 调度 | 等待即将可用的容量、回收并复用、创建新 worker、排空后缩池。允许启动与等待重叠，启动中的 worker 计入预算。 | 固定池比较全会话持租、每批归还、按需归还和有界等待。再用相同峰值上限比较队列扩容和考虑恢复代价的策略。报告新任务与恢复 P95、成功吞吐、连锁回收、worker-seconds 和缩池后首波恢复。 |
| 隔离 | 分清同会话、同租户与跨不可信租户。交接应撤销旧进程、写层、工作区访问和凭据。无法确认 reset 完成时淘汰 worker。 | 在同一威胁模型下比较原地重置和销毁重建，测访问撤销到首条命令完成的耗时。现有验证只覆盖可信本地任务的功能清理。 |
| 依赖 | 会话中新增、升级和回退后恢复哪版环境，哪些组件可以共享，谁有权发布，以及何时可以淘汰。 | 固定 worker 和磁盘预算，比较重装、会话私有缓存、共享只读组件。测版本正确性、依赖变化频率、命中、重建耗时、字节与 inode。 |
| 存储 | 区分 CXL 内存分层节省本地 DRAM 与跨主机访问减少复制这两个假设。优先考察可重建依赖层、热构建缓存或快照数据。 | 固定恢复机制，对比本地 DRAM、NVMe、网络存储与可用的 CXL 硬件。测读取带宽、DRAM 占用和首条有效命令 P95。易失性内存中的数据需要可恢复副本。当前无 CXL 实测。[Linux CXL](https://www.kernel.org/doc/html/latest/driver-api/cxl/devices/device-types.html) · [Pond](https://arxiv.org/abs/2203.00241) |

## 调度器能看到的信号

OpenHands 每会话复用一条本机 Unix socket，发送逐行 JSON。模型请求前的 `park` 和工具就绪时的 `claim` 已能标识等待与恢复。Scheduler 通过 Docker 启动租约、探测就绪和执行工具。源码与构建缓存走工作区挂载。调度器的目标是通用协议，OpenHands 用于端到端验证，直接使用协议的客户端可用于确定性重放。

现有两个 worker 的 150 ms 场景中，9 轮有 3 轮出现连锁回收。A 的 worker 被短任务 C 接手，A 很快回来并触发对仍在等待的 B 的回收。830 ms 有竞争时，按需 reset P50 约 46 ms。另一个近同步恢复对照测得领租 P50 约 107 ms，其中 Docker 启动和探测分别约 60 和 45 ms。两组计时边界不同。[实测](worker-reuse.md)

候选策略在满池时给恢复请求一个有界等待窗口，对比 0、25、50 和 100 ms。已有空闲容量或原租约可用时立即分配。显式记录请求类型、入队时间、等待截止时间、正在 reset 与启动的容量。新建与等待可以并行，先满足条件的容量接单，未用到的启动也计入成本。运行中的命令还剩多久可以用命令类别、已运行时长和历史归还分布估计；模型流式进度、项目版本及缓存命中是后续可检验信号。先做影子评估，决策只读取内存统计，P99 < 1 ms 是待测目标。

Delay Scheduling 提供有界等待的参照。Slurm backfill 用预计完成时间判断未来容量。FaasCache 为按重建成本排序提供参照。三者分别用于等待、供给估计和淘汰。[Delay Scheduling](https://people.csail.mit.edu/matei/papers/2010/eurosys_delay_scheduling.pdf) · [Slurm](https://slurm.schedmd.com/sched_config.html) · [FaasCache](https://homes.luddy.indiana.edu/prateeks/papers/faascache-asplos21.pdf)

## 按清单组装环境

设计提案是让 worker 只提供执行容量，宿主级组件库保存只读版本。清单固定镜像、工具链、依赖组件、挂载路径和会话持久目录。内容摘要用于标识组件，平台、ABI 和解析输入用于检查兼容性。先按工具链和完整解析环境拆分，再用实际重复率判断是否值得细化到单包。

领租时预留 worker 与组件引用，在私有 mount namespace 中组装依赖、工作区和新写层，验证就绪后才开放执行。安装先进入会话私有状态，受控构建验证来源和输入后可发布新只读版本，已有租约继续固定原版本。缩池回收执行容量。组件管理器在字节或 inode 达到水位时淘汰未引用、可重建的组件。必需状态按会话生命周期保留。隔离权限和清理失败语义见[架构](architecture.md#信任和恢复边界)。

## 组件原型实测

OrbStack 上使用同一 demo 镜像。两次功能试跑在原 worker 上切换 v1 → v2 → v1，再在替换 worker 恢复 v1。各租约只挂载指定组件，共享文件拒绝写入，旧 `/tmp` 标记消失。热领租到验证完成约 80–88 ms，删除并准备替代 worker 约 651–694 ms，替代后的领租另计。[一次试跑原始数据](results/worker-component-mount.json)

真实包对照使用 humanize 4.12.3，组件约 393 KiB。同一热 worker 上三组各预热 1 轮、轮换测 30 轮，验证导入路径、版本和输出。预下载与组件首次准备在计时之外，重装用已下载 wheel，计入复制和 pip 安装。数值为 P50 / P95。

| 来源 | 领租（ms） | 发出领租至首条验证完成（ms） |
|---|---:|---:|
| 镜像预装 | 52.68 / 59.07 | 90.54 / 99.67 |
| 只读组件 | 50.90 / 60.89 | 92.43 / 113.78 |
| 离线重装 | 52.27 / 57.67 | 260.20 / 318.90 |

挂载组比离线重装每轮都快，配对节省中位数 165.90 ms。相对预装，挂载组端到端配对中位数多 2.58 ms，尾部波动较大。结果覆盖小型包的本地挂载与复用，组件发布、引用管理、并发挂载、淘汰和跨不可信租户隔离仍待验证。

```bash
PYTHONPATH=. python benchmarks/worker-component-mount.py
PYTHONPATH=. python benchmarks/worker-component-mount.py --rounds 30
```

[原型与基准](../benchmarks/worker-component-mount.py) · [逐轮数据](results/worker-component-comparison.json)

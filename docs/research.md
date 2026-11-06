# 相关工作与研究计划

## 最接近的先例

- **Sandman** 已做 coding agent 训练和评测中的跨任务 Pod 复用。它在归还后检查状态、撤销可恢复的变化并复查，其余情况换新 Pod。论文附录的同批测试里，普通复用有 64/787 次错误评分，经检查的复用有 0/787 次。SandWeaver 的候选区别在于，从一开始把写入和任务进程限制在可丢弃的执行视图内。两者的延迟数据不可直接比较。[Sandman](https://arxiv.org/html/2610.39711v1)
- **Kubernetes Agent Sandbox** 有 WarmPool/Claim，RL 示例还支持 Git 重置、进程与临时目录清理，再次分配 Pod。文档将 OverlayFS 和 checkpoint 路径列为后续方案。[WarmPool](https://kubernetes.io/blog/2026/03/20/running-agents-on-kubernetes-with-agent-sandbox/) · [RL 复用策略](https://github.com/kubernetes-sigs/agent-sandbox/blob/main/examples/agent-sandbox-rl/docs/strategies.md)
- **SAND** 在 serverless 中用常驻应用沙箱和单独函数进程摊销启动成本。**aShare** 的论文题目和摘要覆盖跨 agent 重新分配空闲沙箱，具体机制仍需阅读全文比较。[SAND](https://www.usenix.org/conference/atc18/presentation/akkus) · [aShare](https://link.springer.com/chapter/10.1007/978-981-92-4805-6_13)
- **Crab** 按 agent 轮次观察系统副作用，选择文件、进程或完整 checkpoint。**CUA-Sandbox** 则以私有状态 capsule 和共享运行时支持 computer-use 训练。二者都是状态分类和复用的重要先例。[Crab](https://arxiv.org/html/2604.28138v1) · [CUA-Sandbox](https://arxiv.org/html/2609.32750v1)
- **SpecBox** 用流式模型输出和历史轨迹提前准备环境。**DSec** 在 agent 训练中组合独立版本环境层并按需加载。**SWE-MiniSandbox** 缓存仓库和依赖环境。更早的 **Nix、SOCK、Slacker** 分别覆盖不可变包环境、包感知预热和镜像按需拉取。[SpecBox](https://arxiv.org/html/2607.23933v1) · [DSec](https://arxiv.org/html/2609.22978v1) · [SWE-MiniSandbox](https://proceedings.mlr.press/v306/yuan26l.html) · [Nix](https://edolstra.github.io/pubs/nspfssd-lisa2004-final.pdf) · [SOCK](https://www.usenix.org/conference/atc18/presentation/oakes) · [Slacker](https://www.usenix.org/conference/fast16/technical-sessions/presentation/harter)

## 优先验证的假设

在持续到达、会改写依赖和启动服务的 coding 工作负载上，丢弃任务可写层并重建进程空间，能否以更低交接成本实现和热镜像新建容器一致的结果，并在相同资源预算下减少排队？

1. 同一调度器内比较热镜像新建、用完销毁加后台补位、检查清理后复用、丢弃任务层后归还。固定基础镜像、CPU、内存、并发和任务轨迹。原生 OpenHands 单列为系统对照。
2. 用真实仓库采集执行轨迹，再重放同样的命令和相对到达时间做可控对照。覆盖多语言、重复与长尾环境、突发与持续流量、修改依赖和间歇回访。挑选可自动验证的任务，并保留实时模型运行以评估任务结果。环境配置负载可参考 [SetupBench](https://arxiv.org/abs/2507.09063)。
3. A 主动制造残留，包括覆盖和删除基础文件、修改包元数据、启动后台进程、写入任务数据。B 的验证结果和一份从未复用的环境比对。对外部服务、凭据和网络做单独的边界检查。
4. 记录队列等待、创建与归还、请求到首个有用结果的 P50/P95/P99、任务成功率、错误通过、回退率、worker 峰值、内存时间积分、磁盘和 I/O。把首次准备和后台扩容成本计入。
5. 只有在隔离边界可比、结果一致、收益在真实负载中仍存在时，才把它当成系统贡献。若新建容器已足够快，或收益只在固定微基准出现，先收窄到实验与边界分析。

## 可延伸问题

- **提取最小可复用状态。** 把任务运行后产生的依赖或构建产物显式验证为只读增量，保留工作区和私有数据于各自会话。当前没有自动提取或跨会话发布任务写层。
- **有限磁盘预算的工具架。** 在同一预算比较缓存下载包、已安装工具链和完整环境。当 lockfile 或分支改变时验证有效性。先测纯按需和简单缓存，再判断预算预取是否有净收益。
- **按需释放和恢复语义。** 对可重启服务保存明确配置和可检查的恢复条件；交互调试器或未知进程保持原租约。环境变化后可用工具结果的环境版本来标识历史证据，避免复用过时结论。
- **规模化实现。** 去掉逐 worker 的 rootfs 解包，测试共享只读基础树。把创建和回收移出池锁，增加环境匹配、请求与租约指标、公平排队、重启清理。安全隔离与真实模型正确性分别验证。

# SandWeaver 项目文档

SandWeaver 是一个独立的本机沙盒调度器。Coding agent 在外部运行，通过租约使用动态 Docker worker 池。Worker 保留只读环境，任务进程和文件系统写入按租约隔离、回收。项目不依赖 Kubernetes。

| 文档 | 内容 |
|---|---|
| [一个沙盒可以接力多少次？](article.md) | 从 agent 的执行节奏讲到沙盒复用实验和研究问题 |
| [设计与实现](architecture.md) | 组件、协议、任务交接、状态归属、失败行为和安全边界 |
| [运行与验证](operations.md) | 启动、接入 OpenHands、复现验证和故障定位 |
| [DeepSeek Flash agent 观测报告](agent-observation.md) | 真实修复任务、时间线、租约占用与下一轮机制实验 |
| [实验与决策记录](experiments.md) | 已验证的结果、早期探索、对照组和可解释范围 |
| [Coding agent 的 worker 复用实验](worker-reuse.md) | 写层回收、状态与缓存、OpenHands 三种租约策略及逐轮数据 |
| [相关工作与研究计划](research.md) | 相关系统、集中恢复、容量调度与外部基线 |

仓库以外的早期 OpenHands 实验仅作为研究背景。当前 SandWeaver 实现以仓库中的代码、集成测试和可复现的 benchmark 为准。

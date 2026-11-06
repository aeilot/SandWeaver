# 运行与验证

安装和启动命令见仓库根目录 README。调度器只需要 Python 3.11+ 和可用的 Docker daemon。OpenHands 客户端使用 `.[agent]`，锁定 SDK 1.59.0，已用 Python 3.12 验证。默认镜像 `sandweaver-demo:local` 由仓库 Dockerfile 构建。示例包含一个装好 humanize 的虚拟环境 `/project/.venv`。

- 建议用专用 workspace root 并为每个任务提供自己的目录。当前运行镜像需要提供 `unshare`、`mount`、`nsenter`、`setpriv`、`chroot` 和基础 Debian shell 工具。
- `sandweaver --socket … status` 查看总量、租出和空闲数量。命令行 `run` 每次创建一个租约；需要跨多条命令保留临时状态时，使用 agent 客户端，或使用 scheduler 模块的 `connect()` 发多个 `exec`。
- `sandweaver-agent --smoke-command …` 可多次指定，用 SDK 工具接口跑固定命令，不请求模型。真实 agent 用 `--prompt`，宿主环境提供模型和密钥。状态默认写到 `~/.local/state/sandweaver`，可用 `--state-dir` 调整。
- `python tests/smoke.py` 验证实际 Docker 和 OpenHands SDK 链路。应先安装项目和 agent extra，构建示例镜像。脚本也接受已存在的同类镜像标签作为参数。

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

# SSH 远程运行

只在用户指定或授权远程计算时使用。继承已给连接方式，不重复询问；未指定远程时不擅自把模型传到历史主机。本技能不包含任何固定 IP、用户名、密码或密钥。

1. 使用接收电脑现有 SSH 配置/主机别名；只读确认目标操作系统、磁盘、软件、Python ABI、有效许可、可用核数和已有任务。
2. 在目标机建立新的案例目录。只传源 CAD、配置、适配器和必要工具；`environment.json` 在目标填写，不能照搬本机盘符和路径。
3. 在目标机运行环境检测、网格/QFX回读，再执行 `run_solver.py`。网格/工程若在本机生成，传输前后校验哈希。计算地点变化必须有用户依据。
4. Windows 目标使用其自己的 PowerShell/Python；Linux 通用脚本可用，但 QFlux 原生适配需其实际发行版。不要把两种 shell 引号混在一个未核实命令中。
5. 长任务用目标平台已有持久会话或进程管理能力启动 Python 启动器，保存 PID 与阶段日志，保证 SSH断开不会丢任务。不要把轮询等价于重新启动。不要创建用户未要求的定时任务。
6. 状态从 `job.json`、真实进程命令行和日志判断；只有 `finished.json`、退出码、最终DAT和回读证据齐全才进入最终后处理。
7. 先拉回日志和验收摘要，按需拉完整场；对大文件核对 SHA256。最终包排除 SSH连接配置和目标机器路径配置。

续算使用新阶段。先用新工程独立回读旧的完整 DAT：

```text
<QFlux-Python> tools/qflux_case.py inspect --case . --data <完整DAT绝对路径> --output checks/restart_readback
python tools/run_solver.py --case . --stage continuation --readback checks/restart_readback/check.json --initial <同一DAT绝对路径>
```

停止时核对当前案例的主机、PID、命令行和目录；只处理该任务，不能杀全部 QSolver。启动器异常留下 `checks/solver.lock` 时先核对其中PID是否仍活跃。仅在确认对应进程已结束后清理这个锁；不能自动按锁的年龄判定任务已经死亡。

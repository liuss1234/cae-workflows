# SSH 远程运行

只在用户指定或授权远程计算时使用。继承已给连接方式，不重复询问；未指定远程时不擅自把模型传到历史主机。本技能不包含任何固定 IP、用户名、密码或密钥。

1. 使用接收电脑现有 SSH 配置/主机别名；只读确认目标操作系统、磁盘、软件、Python ABI、有效许可、可用核数和已有任务。
2. 在目标机建立新的案例目录。只传源 CAD、配置、适配器和必要工具；`environment.json` 在目标填写，不能照搬本机盘符和路径。
3. 在目标机运行环境检测、网格/QFX回读；Windows 可执行 `run_solver.py`，Linux Slurm 使用现场已验证的原生转换/分区/MPI 脚本，不把 Windows 启动器原样搬过去。网格/工程若在本机生成，传输前后校验哈希。计算地点变化必须有用户依据。
4. Windows 目标使用其自己的 PowerShell/Python；Linux 通用脚本可用，但 QFlux 原生适配需其实际发行版。不要把两种 shell 引号混在一个未核实命令中。
5. 长任务用目标平台已有持久会话或进程管理能力启动 Python 启动器，保存 PID 与阶段日志，保证 SSH断开不会丢任务。不要把轮询等价于重新启动。不要创建用户未要求的定时任务。
6. 状态从 `job.json`、真实进程命令行和日志判断；只有 `finished.json`、退出码、最终DAT和回读证据齐全才进入最终后处理。
7. 按用户的下载偏好交付；要求仅留远程时只读取状态/摘要，所有场文件保留远程，不擅自下载。需要传回文件时对大文件核对 SHA256。最终包排除 SSH连接配置和目标机器路径配置。

## Linux Slurm 与连接故障

有可用的 `qflux-slurm` 技能时复用其单节点准备/登记/采集工具。否则同样保留现场脚本、每组独立初始工程与作业号。前处理 `uiToCore`、分区 `partition -n` 与 MPI `qcore` 参数以目标发行版核对；Windows UDF 改库名不能替代 Linux 编译和 ABI 检查。

使用已有 SSH 别名及私钥权限；主机指纹变化先核对可信指纹，不能自动关闭主机检查或删除记录。负载均衡有多个合法指纹时仅加入已验证的记录。连接尾部提示异常时结合实际作业号、调度状态、日志和退出码判断，不能仅凭一行警告判定失败或再次提交。

重计算放在 Slurm 计算节点。核对分区每节点 CPU、任务数、cpuset、MPI 绑定与通信后端；部分节点不照搬整节点 NUMA 映射。多节点总任务不能用登录节点或首节点的 nproc 判断。依次区分资源/许可、转换、分区、MPI、数值与回读失败，不从未知错误码猜原因。

提交返回不确定时按案例目录、作业名、用户、时间核查 squeue/sacct 后再决定是否重投。测速保持输入哈希、初场和物理一致，分别统计 Slurm 时间、求解器时间和每迭代时间；说明单次测试/共享节点等限制。Slurm COMPLETED 与 exit 0 不等于物理收敛；最终 DAT 存在仍需官方场回读与守恒验收。

续算使用新阶段。先用新工程独立回读旧的完整 DAT：

```text
<QFlux-Python> tools/qflux_case.py inspect --case . --data <完整DAT绝对路径> --output checks/restart_readback
python tools/run_solver.py --case . --stage continuation --readback checks/restart_readback/check.json --initial <同一DAT绝对路径>
```

停止时核对当前案例的主机、PID、命令行和目录；只处理该任务，不能杀全部 QSolver。启动器异常留下 `checks/solver.lock` 时先核对其中PID是否仍活跃。仅在确认对应进程已结束后清理这个锁；不能自动按锁的年龄判定任务已经死亡。

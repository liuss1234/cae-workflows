# SSH 远程求解

先核对目标操作系统。以下 PowerShell 流程针对 Windows；Linux Slurm 使用现场原生 `uiToCore → partition → mpirun qcore` 脚本，本机可用 `qflux-slurm` 时按其单节点准备/登记/采集流程执行。`run_solver.ps1` 不能当 Linux 启动器。

优先使用已有 SSH 别名，指纹异常先核对，不关闭校验或自动删除 known_hosts。作业号/PID、目录和日志用于识别既有任务，连接中断不等于任务失败，不盲目重投。结果下载服从用户要求，明确仅留远程时不拉回大场文件。

用户要求远程计算才进行传输和远程进程启动；SSH 目标、账号和路径由当前任务提供。技能不携带账号、地址、密码、私钥、known_hosts 或厂商许可。

1. 只读确认 `ssh -o BatchMode=yes <账号@主机> hostname`，以及目标磁盘、QFlux/Python/许可证/MPI。首次连接遵循用户现有主机密钥确认流程，不关闭 StrictHostKeyChecking 绕过校验。
2. 远程创建专用案例目录。上传脚本、CGNS、case_parameters、mesh_check、workflow.json；按任务需要同时上传 CAD、mesh_arrays。远端 workflow 中的软件目录/Python 必须按远机重新配置，不将本机路径照搬。
3. 在远端执行 setup_qflux.py、verify_case.py。QFX 内含输出绝对路径，应在远机生成或调整并重新保存，不能仅凭复制本机 QFX 就推定路径正确。
4. 上传所有文件后再启动单个监督脚本。长任务通过隐藏 PowerShell 后台进程运行 run_solver.ps1，让 supervisor 保留 Handle 并等待 QSolver，写结束记录；SSH 断开后任务仍需可追踪。
5. 记录监督进程 PID、QSolver PID、host、命令行、工程/阶段路径、开始时间、stdout/stderr。使用 run/job.json 和 finished.json 判断状态，并以 Get-CimInstance Win32_Process 查证实际进程。仅日志暂时不更新不能直接认定卡死。
6. 正常结束后下载匹配 QFX、完整 DAT、所有监测、job/finished、求解日志，核对本地/远程 SHA256。可以本地兼容 QFlux API 导出 VTU，也可远端导出后下载。

## 命令编码

Windows SSH 多层引号容易损坏脚本。可将纯 PowerShell 命令 UTF-16LE Base64 编码，使用 `powershell -NoProfile -EncodedCommand <编码>`；编码只是传输格式，不是加密。不要在命令中嵌入密码或打印私钥。

Windows PowerShell 5.1 执行包含中文的 PS1 时需要 UTF-8 BOM；本包交付时已处理。远端 Python API 使用其兼容 ABI 的解释器。所有路径带空格时使用 LiteralPath 和显式参数引号；不用字符串拼接跨 shell 删除/移动文件。

示例监督命令结构（变量均来自当前已验证配置）：

```powershell
Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList '-NoProfile -File "D:\CFD\demo\run_solver.ps1" -CaseRoot "D:\CFD\demo" -Stage run' -PassThru
```

远程监测只读读取日志尾部、进程和完成标记。需中止时再次核对具体 PID/CommandLine 与案例路径，若用户授权的任务内确需停止，结束该求解进程树；不要按进程名全局 kill，也不要打断其他人的计算。

已出现过 SSH 尾部 `close - IO is still pending...` 噪音。不能只凭该行判定失败；核查远端结果/退出码。禁止无变化重复启动以“重试”长任务。

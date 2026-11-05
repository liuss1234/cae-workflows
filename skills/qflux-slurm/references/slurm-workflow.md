# Slurm 链路与故障定位

## 环境与 SSH

- 复用目标机器已验证的 SSH 配置，不把账号、主机、密钥写进通用脚本。私钥只在本机且 ACL 仅授权用户；日志不显示密钥正文。
- 主机指纹变化先与管理员或已有可信记录核对；负载均衡可能有多个合法指纹，但不能因此关闭校验或自动删除 known_hosts。
- 登录节点仅做轻量文件检查、脚本准备和调度；网格分区、求解放入获分配的计算节点。核对分区 CPU 上限与许可，不按本机 CPU 数申请超算。
- SSH 尾部警告可能不代表远端失败，联合返回码、作业号、sacct 和阶段日志判断。

## 复用现有脚本

优先复用现场脚本的 module、QFLUX 环境、许可、日志、错误处理与通信配置。示意原生命令（参数以实际安装版本为准）：

```bash
# 软件环境已由现场脚本加载；每个目录仅一个输入QFX。
uiToCore -c case "$QFX" ./ ./dat
partition -n "$SLURM_NTASKS" -t 0 "$CASE"
mpirun -np "$SLURM_NTASKS" qcore "$CASE" -p --partall 2
```

HDF5 QFX 可直接转换；归档 QFX 应按官方格式解包后转换。Windows 的 `udf.dll` 不能在 Linux 加载；改为 `libudf.so` 只有在对应 Linux 库真实存在且 ABI 匹配时才有效，真实 UDF 需目标平台编译。CRLF 可在阶段副本清理，保留源工程。

`--ntasks`、每节点任务数和 partition 的进程数保持一致。部分节点 cpuset 下，按全节点 NUMA 分布绑核可能报“bind more processes than cpus”；使用现场验证的 core 映射。不要默认允许 overload。`nproc` 只反映当前节点可见 CPU，不能拿它限制多节点总 MPI 进程。

单节点已实测过 OpenMPI 的 `--map-by core --bind-to core` 与 `--mca pml ob1 --mca btl self,vader,tcp`。这不是所有 MPI 版本或多节点的通用配置；多节点应核对 UCX/IB、网卡和 MPI 版本。不把单节点 TCP 回退写成全面禁用 IB。

## 准备、提交与幂等

prepare 在新 root 内建立 `np<N>/`，仅放同一初始 QFX、submit.sh，根目录保存模板原件与 manifest。先在集群执行 `bash -n submit.sh`、`sbatch --test-only submit.sh`；这些操作没有提交计算。核对模板中 `PREPROCESSED` 等逻辑与输入一致，准备器不自动改它。

在每个 np 目录用 `sbatch --parsable submit.sh`，随后立即 register 真实 job-id。测速可按 `--dependency=afterany:<上一个job>` 串行运行，减少同批作业竞争；依赖不保证独占或相同物理节点。失败组不用于性能排名。提交中断时，用工作目录、作业名、用户和时间核查 squeue/sacct，确认未投递后才重试。不要依靠作业名唯一性阻止重复计费。

## 采集与验收

collect 从 `jobs.json`、`sacct` 与 `logs/job_<ID>/` 读取，写新的报告前缀；拒绝覆盖已有报告文件。基础证据为输入哈希一致、实际 CPU 数一致、正常结束、求解器计时和非初始 DAT 存在。数值收敛和守恒单独展示，仍需官方 API 回读完整场、残差限与关键监测验收。

可选 `--mass-in <相对dat路径> --mass-out <相对dat路径>`，监测默认第2列（1基），可设 `--monitor-column`。有符号流量约定入口负、出口正（或同时相反）；不平衡为 `abs(mi+mo)/abs(mi)*100%`。多入口/多出口应用所有端面的有符号通量之和，不能只取一对代替全域。压力文件通过 `--pressure-in/--pressure-out` 指定；调用者必须确认监测压力和平均口径相同。工具不猜名称、不自动识别量纲。

- `job_elapsed_s`：sacct ElapsedRaw，不含排队，含转换/分区/输出等。
- `solver_wall_s`：日志 EqnSolveInfo 的 Total wall time，不代表全部作业耗时。
- `seconds_per_iteration = solver_wall_s / iterations`：不同核数收敛步数不同时辅助比较。
- 基准取有效结果中最小核数 N₀；`S=t_iter(N₀)/t_iter(N)`，`E=S/(N/N₀)×100%`。这是相对基准核数的归一化效率，非相对单核效率。
- QFLUX 日志中的“on N nodes”可能指 MPI 进程，物理节点以 Slurm NodeList/NNodes 为准。

NaN/Inf、无计时、无最终场、哈希变化、CPU 不符均不得进入性能排名；`Convergent: Residual` 只证明该日志的残差停止条件，不证明网格精度、守恒或高级物理正确。达到最大迭代正常退出也不等于残差收敛。

常见失败按阶段定位：调度资源/时间限 → module/许可 → uiToCore 输入格式 → partition 核数/网格 → MPI 绑定/通信 → qcore 数值发散 → 最终场回读。保留完整日志和确切版本；错误码需查目标版本官方说明，不凭数字猜因。

---
name: qflux-slurm
description: 使用目标超算已有 Slurm 脚本运行 QFLUX，隔离各核数工况、核对作业与最终场、汇总并行耗时。适用于 SSH 超算提交、故障排查与核数测速；不替代几何建模或物理设置。
metadata:
  version: 1.0.0
---

# QFLUX Slurm 运行与测速

继承用户已给定的主机、案例、核数、命名和结果下载偏好。使用已有 SSH 别名；机器路径、账号、许可证和密钥留在机器配置中，不放入可迁移技能。

## 执行顺序

1. 读目标目录的现有 Slurm 脚本，核实分区、每节点容量、MPI、软件环境与唯一 QFX。记录源文件哈希。用户要求沿用脚本时保留其业务逻辑。
2. 每个核数使用独立目录与同一初始 QFX。先检查脚本语法和调度资源，再提交；保留 `sbatch --parsable` 返回的真实作业号，`--test-only` 不是已提交作业。
3. 对计费任务先核对授权范围；已有明确提交授权时继续执行。SSH 超时或返回值不明确时先核查 `squeue/sacct`，不得盲目重投。轮询、续算和重新提交是不同操作。
4. 对照调度状态、各阶段日志、残差、监测与最终 DAT。`COMPLETED` 仅表示作业退出正常。缺少完整场或数值验收时不能宣称仿真通过。
5. 比较 Slurm 总耗时、求解器内部计时与每迭代耗时，注明硬件、网格、迭代数、共享负载及测量次数。不把小例最佳核数外推到大案例。

具体命令、MPI/NUMA 问题和测量口径见 [references/slurm-workflow.md](references/slurm-workflow.md)；真实验证边界见 [references/validated-scope.md](references/validated-scope.md)。

## 辅助工具

`scripts/slurm_scaling.py` 仅准备目录、登记作业号和只读采集结果，**不会提交作业**。Windows/Linux 均可 prepare/register；collect 在有 `sacct` 的目标集群执行。Python 3.6+，无第三方依赖。

```text
python scripts/slurm_scaling.py prepare --root <新目录> --qfx <源.qfx> --template <已有Slurm脚本> --partition <实际分区> --cores 16 32 45 96 128 --job-prefix <用户指定前缀>
python scripts/slurm_scaling.py register --root <目录> --cores 16 --job-id <sbatch真实返回值>
python scripts/slurm_scaling.py collect --root <目录> --case-name <转换后的CASE基础名> --output-prefix report
```

prepare 限定单节点纯 MPI（每进程一个 CPU），只改模板的资源、名称和标准输出指令，保留原脚本副本。多节点、OpenMP、GPU或异构资源应独立适配，不能套用此准备器。register 拒绝覆盖已有作业号；未知提交结果先核查调度器。collect 支持已有 jobs.json 中的绝对目录；不自动下载结果、不改原始场、不把汇总代替官方场回读。

如需完整建模与求解验收，使用可用的 `cfd-case-workflow`；缺少该技能时仍按物理守恒、监测稳定性和官方完整场回读完成验收。

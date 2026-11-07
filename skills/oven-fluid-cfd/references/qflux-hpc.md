# QFlux设置、资源分工与Slurm

## 内存与输入交接

本例笔记本只控制、读取日志与统计；大内存台式机顺序设置M04/M08、保存QFX并新进程独立回读；DG运行转换、分区和MPI求解。两套不要同时在64 GB机器加载。临时文件与输出盘先核容量；原CGNS约十GB量级，输入QFX约2.2/2.6 GB，不能只按文件大小估RAM。

机密连接写本地environment.json或SSH配置，不提交。跨机SCP -3可以流过控制机不落大文件，但需核对实际版本和进程；目标先`.uploading`，校验源/目标SHA256后原子改名，完成收据后才允许提交。

## 原生设置与回读

包内 `qflux_case.py`、`cfd_common.py`为本次已用通用适配快照；`qflux_oven.py`写Realizable k–ε、双层近壁、关闭重力、等温常物性、逐开口质量/体积流量及面积平均压力监控。使用QFlux匹配ABI的Windows Python，`QFLUX_HOME`或environment.json给安装目录。原生数值枚举2/3只属于已核对版本；先查当前API再用。

```text
<QFlux-Python> <案例>/tools/qflux_oven.py setup-basic --case <案例> --output checks/setup_R01
<QFlux-Python> <案例>/tools/qflux_oven.py inspect --case <案例> --output checks/readback_R01
```

两个命令分别启动新进程。比较CAD→CGNS→QFX的区/边界名称、数量、面数、归属、bbox和CGNS哈希；inspect从实际管理器和保存的settings.json自动核对入口速度、方向、出口压力、稳态/能量/重力、密度黏度和湍流子型/近壁。另从settings.json逐项复核离散、松弛、初始场、监控定义和残差准则；不能把自动断言清单当成全部设置。读回正确才登记input_ready。自动设置仅单流体无接口等温；传热/回风全域/多材料须扩展且单独验收。

若网格passed:false，默认不准设置；仅当已有用户诊断授权文件、原因、源网格哈希一致时允许明确标记为诊断。授权不改变网格失败报告，设置check的passed也只表示设置核对通过。

## 本例工况

入口10 m/s是用户指定；面积0.1 m²得1 m³/s=3600 m³/h。15出口0 Pa表压、20℃常物性空气ρ1.2041 kg/m³/μ1.825e-5 Pa·s、湍强5%、黏度比10及稳态等温均为声明的工程假设。动量SecondUpwind，k/epsilon Upwind；初始k/epsilon与数值松弛须记录而不从旧案例静默套用。

## 集群提交

复用目标集群已有可用脚本，保留原件和哈希，不修改用户全局模板。每个网格/重试独立阶段、相同源QFX；先bash -n、资源和唯一输入检查。原生流程 `uiToCore → partition → mpirun qcore → recombine`；目标版本、MPI和分区依现场验证，不能复制Windows QSolver调用到Linux。

本次两套为单节点128 MPI进程、每进程1CPU、350G、8小时。OMP/BLAS/MKL线程=1；此资源不是所有烘箱的推荐值。CPU可用性读Slurm分配变量；`nproc`在batch步骤可能只见1核，不能据此判定整个作业只有1核。本例首个M04启动检查失败未迭代，修复为 `SLURM_JOB_CPUS_PER_NODE` 后在新阶段提交，不覆盖旧日志。

`sbatch --test-only`不代表已提交；`sbatch --parsable`取得真实号后写收据并查squeue/sacct。超时先查是否已提交，不能盲重投。不以轮询权限推定续算/新提交授权。

**转换后的CASE必须再次审查保存策略。** 本例QFX autoSaveIteration=200，但DG CASE实际writeControl=atEnd，200步没有完整场。若需周期保存，在转换CASE中按本版本能力配置并实测写场，再说已启用；本次没有事后虚构周期快照。

## 停止与结果保护

只停止已核对的本案例监视器或进程；不要杀用户其他STAR/Python。已验证的QFlux此发行版：阶段根u2c原子写`0\n`触发End by UI、save、writeStatus和正常MPI退出；`-1`是不保存退出，不能混用。这不是所有版本通用协议，未知版本先核实官方/安装实现。不要给全路径模糊匹配后批量kill。

保存停止后核对End by UI、DAT非零大小且稳定、recombine日志、sacct退出码；再用官方API独立读完整场，若未做回读必须标未验证。保留输入/QFX/DAT哈希及实际步数。用户要求不下载时原件保留集群，只回小摘要。历史停在887步是最新结束要求，不冒充原计划1000步。

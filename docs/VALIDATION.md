# 验证范围

## 烘箱公开信息修订 · 2026-11-07

公开技能仅保留结构类型及处理方法，移除真实结构数量、尺寸、拓扑统计、逐部件边界枚举、逐出口表和可反推尺寸的绝对流量。几何相关模板参数留空，逻辑自检使用独立合成边界及参数；原始私有工程、计算日志和结果不修改。校验范围为参数模板、逻辑自检、代码检查、技能结构和安装包回读；本次未重划网格或求解。此修订不代表旧Git提交或PR差异已从托管平台历史中清除。

## 烘箱供风技能 · 2026-11-07

新增[oven-fluid-cfd](../skills/oven-fluid-cfd/SKILL.md)，覆盖11月6日初始装配至11月7日最终求解诊断和逐出口统计。详见[历史过程与验证边界](../skills/oven-fluid-cfd/references/validation.md)。公开只含方法、参数化工具和脱敏摘要，客户CAD/网格/工程/结果场及连接信息不入包。

本地Windows/Python3.11已通过8技能、72 Python/宏、14 JSON、12 YAML、92本地文档链接、46 CLI入口、三套合成自检及全部技能ZIP的CRC/SHA256回读；仓库lint与3个pytest通过。新统计工具还在DG原生M08最后100个同步监控步上只读复核，CV=2.9433812%、守恒误差=0.0005926133%，与原统计一致，并返回监控稳定性未通过。未重新启动求解、未下载完整场。

M04在43步k NaN发散；M08用户887步保存停止，调度正常退出但残差和监控稳定性不通过。两套原网格工程检查均失败；无网格无关性、实验精度和最终DAT官方回读结论。参数化STAR宏与原生API迁移脚本的整模重运行不在此次发布验证范围；跨平台代码由CI另行核对。此次首个仓库Release使用普通GitHub标签；环境未配置标签签名/保护，真实性核对依赖已合并提交和附件SHA256，不宣称签名验证。

## 仓库规范化基线 · 2026-11-06

仓库新增单一工作流清单、README 一致性检查、标准 lint/pytest 入口和 Windows/Linux 的 Python 3.8/3.11 CI 矩阵。原有技能初始化、拒绝覆盖、自检、CLI 帮助和安装包 CRC/SHA256 检查继续保留。该基线只提高仓库结构与脚本兼容性的可审查性，不扩大任何 CFD 物理验证结论。

## 技能同步与仓库检查 · 2026-11-05

新增 `qflux-slurm` 可迁移技能，并同步几何前处理、FreeCAD/Gmsh/QFlux 和液冷技能的通用改进。`freecad-gmsh-qflux` 继续使用示例环境配置；本机路径配置、缓存和安装清单不进入仓库。

`python tools/check_repository.py` 本次通过：7 个技能入口、60 个 Python/宏文件、9 个 JSON、8 个 YAML、80 个文档链接和 38 个命令行帮助入口均通过；两套风扇自检、案例初始化/拒绝覆盖及七个技能包 CRC/SHA256 回读通过。Slurm 检查使用合成输入验证目录准备、哈希和重复作业号保护，不调用 `sbatch`。QFlux Slurm 文档中的超算实测属于原有记录，本次没有重新运行超算或 CFD。

更新范围内未发现用户目录路径、GitHub 凭据或 OneBrain 会话令牌。GitHub Actions 的远端结果需在推送后另行核对。

## 风扇行业技能 · 2026-11-05

新增独立 `fan-cfd`，覆盖保形清理、流体域、STAR/Gmsh网格、实际层证据、QFlux多区多接口MRF配置与计算记录。实测与限制见 [fan-cfd验证记录](../skills/fan-cfd/references/validation.md)。仓库检查同时执行其合成逻辑自检、帮助入口和独立技能ZIP验证；不会自动运行商业求解器。

## 仓库迁移检查 · 2026-11-03

本次工作将四个本机工作流整理为独立技能目录，替换风扇示例中的个人软件路径，增加空配置拒绝逻辑，修复液冷技能的 YAML 头部，并补充安装、依赖及打包说明。原安装目录中的文件保持原样。

运行 `python tools/check_repository.py` 检查源码/宏语法、JSON/YAML、四个技能入口、相对文档链接、命令行帮助、直管/自定义/液冷/风扇初始化及拒绝覆盖。四个 ZIP 使用显式文件清单创建，随后独立回读 ZIP CRC 和逐文件 SHA256，检查可直接安装的目录结构及风扇 CAD 输入。

本次在 Windows / Python 3.11 上实际检查通过：

| 检查项 | 结果 |
|---|---|
| Python / FreeCAD 宏语法 | 39 个文件通过 Python 3.8 语法解析 |
| 参数 / 元数据 | 5 个 JSON、5 个 YAML、4 个技能头部通过 |
| 文档链接 / 命令行入口 | 35 个相对链接、19 个帮助入口通过 |
| 初始化 / 原文件保护 | 直管、自定义、液冷、风扇独立初始化及重复初始化拒绝通过 |
| 安装包 | 4 个 ZIP 的 CRC、逐文件 SHA256 及安装目录结构通过 |
| PowerShell 启动器 | 语法解析通过 |
| 技能结构 | skill-creator 的 quick_validate 对 4 个技能全部通过 |

这组检查不要求商业软件或求解许可，不运行几何重建、重划网格或 CFD 求解。GitHub Actions 配置了 Windows/Linux 检查任务；配置存在不代表远端任务已经运行通过。

## 保留的历史验证记录

| 工作流 | 历史证据 | 范围 |
|---|---|---|
| 通用 CFD | [实测范围](../skills/cfd-case-workflow/references/validated-scope.md) | 2026-10-19：单区直管完整链路；三区导入/命名/连接回读 |
| 风扇前处理 | [七叶风扇基准](../skills/freecad-gmsh-qflux/references/fan-example.md) | 2026-10-14：CAD→网格→米制 CGNS→QFX；3 区、12 个边界侧面 |
| 液冷管路 | [原算例](../skills/qflux-liquid-cooling/references/validated-example.md)、[迁移记录](../skills/qflux-liquid-cooling/references/portability-check.md) | 独立目录重建/导入、历史真实场重处理；迁移整理时未再次长时间求解 |

以上数值与结论沿用本机已有记录，本次上传不构成重新计算或独立复现实验。

## 工程使用限制

- QFlux 原生适配与 CGNS 库只实测 Windows；目标版本的 ABI、枚举、API 和许可必须重新核对。
- 高阶、结构化/混合网格、非共形/滑移、MRF、瞬态运动、overset、CHT 等需要对应适配器和单独验证。
- 风扇示例的接口耦合持久化与转速设置尚未完成，不能直接称为旋转求解就绪。
- 直管自检无棱柱层、无 y+ 验证、无网格无关性研究；用于安装链路验证。
- 液冷为矩形通道水力模板，真实冷板和热负荷必须另建几何与物理模型；一阶格式的数值扩散限制保留。

## QFlux MCP 与 VOF/UDF 单步检查 · 2026-11-03 至 2026-11-06

本机 TF-QFLUX 原生 MCP 服务已注册到 Codex，并通过 stdio JSON-RPC 完成 initialize/tools-list、宿主发现/选择、API 声明读取、Python 脚本调用，以及已完成 QFX/DAT 的设置回读和检测面导出。源工程和结果场哈希保持不变；场重构流量与同一最终场的基线重构值一致。

2026-11-06 追加验证了单 Region 两相回流焊案例：从 STEP 真实圆弧轮廓生成 UDF 初始锡膏体积分数，通过 MCP/API 携带 `--spath` 实际启动 QSolver，并完成 1 个瞬态步、1 次内迭代。2,651,103 单元网格的初始液相体积离散误差为 `+0.065362%`；步 1 DAT 可回读且 SHA-256 与此前独立烟雾测试一致。

该实测只证明 UDF 加载、初始相、MCP 下发和单步写场链路，不证明完整 `0.02 s` 瞬态收敛、物理结果有效或 DFBI/Morphing 已配置。可迁移安装、宿主故障诊断和求解启动见 [QFlux MCP 参考](../skills/cfd-case-workflow/references/qflux-mcp.md)，真实轮廓初始化见 [VOF 与 UDF 初始相](../skills/cfd-case-workflow/references/vof-udf-initialization.md)。MCP 服务端、商业软件、许可证、客户模型、QFX/DAT、本机路径及会话记录不纳入 GitHub 技能资源。

## 吊扇试验技能

新增模块的分层证据与适配边界见 [ceiling-fan-cfd发布验证](../skills/ceiling-fan-cfd/references/release-validation.md)。仓库检查包含该模块的命令行、迁移自检和独立打包；不自动运行商业网格或求解器。

# 验证范围

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

## QFlux MCP 接入检查 · 2026-11-03

本机 TF-QFLUX 原生 MCP 服务已注册到 Codex，并通过 stdio JSON-RPC 完成 initialize/tools-list、宿主发现/选择、API 声明读取、Python 脚本调用，以及已完成 QFX/DAT 的设置回读和检测面导出。源工程和结果场哈希保持不变；场重构流量与同一最终场的基线重构值一致。

该实测不包含通过 MCP 启动新求解，也不证明任意版本、网格导入或高级物理设置均已验证。可迁移安装命令和操作步骤见 [QFlux MCP 参考](../skills/cfd-case-workflow/references/qflux-mcp.md)。MCP 服务端、商业软件、许可证、本机路径及会话记录不纳入 GitHub 技能资源。

## 吊扇试验技能

新增模块的分层证据与适配边界见 [ceiling-fan-cfd发布验证](../skills/ceiling-fan-cfd/references/release-validation.md)。仓库检查包含该模块的命令行、迁移自检和独立打包；不自动运行商业网格或求解器。

## 吊扇试验技能

新增模块的分层证据与适配边界见 [ceiling-fan-cfd发布验证](../skills/ceiling-fan-cfd/references/release-validation.md)。仓库检查包含该模块的命令行、迁移自检和独立打包；不自动运行商业网格或求解器。

## 吊扇试验技能

新增模块的分层证据与适配边界见 [ceiling-fan-cfd发布验证](../skills/ceiling-fan-cfd/references/release-validation.md)。仓库检查包含该模块的命令行、迁移自检和独立打包；不自动运行商业网格或求解器。

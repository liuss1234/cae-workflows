---
name: qflux-liquid-cooling
description: "使用 FreeCAD、Gmsh 和 TF-QFLUX 建立多支路液冷管路水力 CFD 案例，支持 Windows 本地或 SSH 求解、米制命名网格、原生工程回读、收敛核验及支路偏流后处理。附可配置演示脚本，不自动包含共轭换热或真实产品冷板结构。"
metadata:
  version: "1.1.0"
---

# QFlux 液冷管路 CFD

交付可回读的 CAD、米制网格、QFX/DAT 配对、真实流速/压力场及支路流量统计。软件本体、许可证、Python 环境和 SSH 凭据不随技能分发。

## 入口与资料

- 换电脑或首次运行：读 [安装与依赖](references/installation.md)，执行 `scripts/probe_environment.py`。不沿用原电脑用户名、IP、软件目录或 Python ABI。
- 建立案例：读 [建模与运行](references/workflow.md)，用 `scripts/init_case.py --output <新目录>` 生成独立工作副本；修改副本中的 `workflow.json`。模板不能原地运行。
- 远程求解：读 [SSH 与进程管理](references/remote.md)。仅在用户已要求远程计算时传输/运行；目标主机和账号取本次用户配置。
- Linux 超算：使用目标机器现有 Slurm 脚本；本机可用 `qflux-slurm` 时按其方式隔离提交与汇总。现有 `run_solver.ps1` 面向 Windows，不直接用于 Linux。
- 与 STAR-CCM+/Fluent 对比时按相同工况、物性、统计口径和原生云图视角/色标复核；有 `cfd-case-workflow` 时按其 `references/solver-comparison.md` 执行。不把接口可用或软件已启动当作复算完成。
- API 或运行失败：读 [QFlux API 经验](references/qflux-api.md)。仅以目标安装版本的公开 API、枚举和回读配置为依据。
- 判断完成和交付：读 [验收与后处理](references/validation.md)。历史标杆见 [已验证算例](references/validated-example.md)，不能把标杆数值当成新算例结果。

## 核心规则

1. 沿用用户已确认的尺寸、工况、求解位置和模型。模板为 U 型异程矩形总管、矩形支管、等效直通冷板流道。实际产品需重建几何与映射；热负荷/固体导热需另建能量方程和固体域，不能把水力模板当共轭换热模型。
2. 模板网格为 m；FreeCAD/STEP 为 mm。用尺寸、体积及导入包络核实单位，不能只改文件名。保留影响水力的孔、间隙、圆角和倒角；不凭视觉缝隙擅自封堵。
3. 共形内部面保持流通，不能在交接面设置阻断壁面。模板有一个流体区 `coolant` 和一个网格区 `fluid_network`；外边界为 inlet、outlet、两总管壁和各支路三组壁，数量 `4+3N`。
4. 检查正体积/Jacobian、边界覆盖、连通性、CAD 体积一致性、skewness/长宽比及最差位置。零角度偏斜仅适用于本模板轴对齐 HEX8，不能套用到任意 CAD。网格收敛验证按任务要求决定；未做时明确记录。
5. 各支管/冷板分别算 Re，不根据总流量认定全湍流。标准 k–ω 不能称为 SST。壁面函数与 y+ 按实际设置/场核验。
6. 正常退出、残差收敛、工程精度是不同状态。核查残差、质量守恒、压降稳定性和积分误差。改格式必须留记录，一阶结果说明数值扩散限制。
7. 求解器未结束时不读 DAT。续算只用完整场；停止前核对 PID、命令行和案例路径，不结束其他案例。每阶段独立目录/日志/启动结束记录，禁止同阶段重复启动。
8. QFX 落盘后独立回读名称、类型、区域及数量。导出匹配 QFX/DAT，逐点坐标及逐单元连接核验后积分；不强制归一化支路流量掩盖误差。

## 模板与交付

默认：8 路、25°C 水、8 L/min、出口 0 Pa、等温稳态、无重力、标准 k–ω。一阶迎风用于稳健演示，不是通用最佳格式；`workflow.json` 可选 SecondUpwind。残差平台先诊断，再决定是否一阶续算。

依次完成环境探测、初始化、网格/CAD、QFlux 配置及回读、指定位置求解、最终工程/场回读、官方 VTU 导出、后处理和报告。提供 STEP、CGNS/MSH、QFX/DAT、云图、支路表、配置和日志；说明压降、CV/最大偏差、求解主机、收敛证据和精度限制。用 `scripts/package_delivery.py` 打包并校验 SHA256/ZIP CRC，不纳入凭据和无关文件。

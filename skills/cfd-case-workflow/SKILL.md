---
name: cfd-case-workflow
description: "建立、运行和交付可追溯的 CFD 案例，覆盖内流、多支路、外流、旋转/运动、重叠网格与共轭传热。提供 FreeCAD/OCC、Gmsh、TF-QFLUX 的可迁移流程与验收工具；用于建模、网格、求解和后处理，按目标软件能力适配。"
metadata:
  version: "1.4.0"
---

# 通用 CFD 案例工作流

把用户的几何、工况和目标转化为可复现的 CAD、分区网格、原生工程、真实求解结果与交付包。通用方法与具体模型分开：不固定流体种类、支路数量、区域数量、湍流模型或计算地点。

## 开始工作

1. 继承对话中已确定的参数、软件、计算地点及授权。用户只要诊断、前处理或后处理时，完成该范围即可。
2. 新电脑先读 [安装与迁移](references/installation.md)，填写 `environment.json`，运行环境检测。普通 Python 与 QFlux API Python 分开；不拷贝厂商二进制或账号。
3. 创建独立案例目录。已有模型则保留原件；`init_case.py` 拒绝覆盖现有目录。参数集中在 `case.json`，几何/物理适配器读取它。

```text
python scripts/init_case.py --directory <新案例目录> --example duct
python <案例目录>/tools/probe_environment.py --case <案例目录> --check-api
```

`duct` 是可执行的层流直管小例，供安装自检；正式案例用 `--example custom`，根据用户目标填写参数并编写适配器。不能把示例几何或材料冒充实际产品。案例目录内复制了工具，不依赖原技能安装路径。

## 按当前阶段读取

| 当前工作 | 需要的参考 |
|---|---|
| 定义区域、边界、文件和脚本输入输出 | [数据契约与适配方法](references/contracts.md) |
| 几何清理、流体域、区域划分、网格 | [几何与网格](references/geometry-mesh.md) |
| 内流/多支路、外流、MRF/瞬态运动、overset/结构化网格、VOF造波、流固换热 | [物理场选择](references/physics.md) 中相应段落 |
| QFlux API、保存回读、接口和官方场导出 | [QFlux 适配](references/qflux.md) |
| QFlux 原生 MCP 的安装注册、宿主选择和工具使用 | [QFlux MCP](references/qflux-mcp.md) |
| VOF 初始相、STEP 真实轮廓 UDF、表面张力/接触角和单步烟雾测试 | [VOF 与 UDF 初始化](references/vof-udf-initialization.md) |
| SSH 计算 | [远程运行](references/remote.md) |
| 超算 Slurm 提交、核数测速 | 先读远程运行；本机提供 `qflux-slurm` 时使用其现有脚本适配与汇总工具 |
| STAR-CCM+/Fluent 复算、原生云图对比及跨软件结果准入 | [软件调用与对比](references/solver-comparison.md) |
| 求解完成、收敛、守恒、物理合理性、统计和最终交付 | [验收与交付](references/validation-delivery.md) |
| 核对这份包实际验证了什么 | [验证范围](references/validated-scope.md) |

## 执行原则

- 先建立 `regions.json` 语义清单，再验证 CAD→网格→QFX 的实际名称、类型、归属、面数和尺寸。`inlet`、`outlet` 自动识别正常，不能因此丢弃其余命名。
- CAD 显示缝隙不等于缺陷。按当前用户指令与流动影响决定孔、圆角、倒角和间隙的保留/删除；记录位置、尺寸、理由和影响。基础 `isValid()`、封闭和减面数不代替自交检查、STEP 独立回读与外形核对；细节见几何参考。
- 网格坐标使用 m，实际缩放并核对包围盒；单位标签不能代替缩放。不要把已是 m 的节点重复乘 0.001。
- 孔口、接口、旋转域、加热实体、固体材料按物理含义划分。网格区与求解计算域不同；不为增加显示数量随意拆计算域。
- `mesh_export.py` 是通用 **一阶 TET4/TRI3、共形接口** 交换器，支持任意数量的命名区。其他单元、周期、滑移或非共形接口应写对应适配器，不能偷偷丢掉不支持的单元。
- `qflux_case.py setup-basic` 仅自动配置单流体、稳态、等温的基础工况。CHT/MRF/多材料等按物理参考与目标版本 API 编写设置适配器；其回读、导出、求解、验收和打包仍可复用。
- VOF 中离散液滴/锡膏块若物理上处于同一连续流体域，应作为同一 Region 内的初始相分布，而不是为每块液体建立独立 Region。矩形包围盒只能用于轮廓本身为矩形且误差已量化的情况；圆弧、圆角和 U 形轮廓优先从 CAD/STEP 提取真实平面边界并由 UDF 初始化。
- 保存 `.qfx` 后在新进程独立回读。接口类别、预期配对列表和空接口组不能作为耦合成功证据；检查实际配对、区域归属、运动与热源持久化设置。
- 只有当前会话实际提供 QFlux MCP 工具时才通过 MCP 控制宿主；连接后先发现/选择目标宿主、读取当前模型状态，再按 MCP 参考中的只读检查→脚本调用顺序操作。没有 MCP 工具时使用已验证的官方 API/命令行路径，不能声称完成了 MCP 调用。
- 将“运行完成、数值收敛、守恒可接受、结果物理有效”作为不同结论分别举证。达到迭代数、生成结果文件或曲线趋平都不能单独证明收敛；残差、守恒、监测稳定性或物理量异常时，不把该工况纳入有效性能对比。网格收敛研究按用户范围决定；未做要明示。未验证 y+ 或无边界层网格时限制摩擦/换热结论。
- 每次求解使用新的阶段目录；不覆盖结果，不自动杀其他任务。续算必须指定已写完、匹配工程的完整场。按用户指定地点运行，缺权限/依赖时报告实因，不能悄悄改成本地。
- 只从完成的 DAT 用官方 API 导出。记录 QFX/DAT 哈希与迭代号，支持 VTM+子目录 VTU；不能拿初始化场、历史算例、示意图当新结果。

## 常用命令

以下路径相对案例目录。QFlux 官方 Python API 适配实测 Windows；Linux 原生 `uiToCore → partition → mpirun qcore` 的 Slurm 链路已实测，依其目标环境脚本运行，不能把 Windows QSolver 命令直接移植。

```text
python adapters/duct.py --case .
python tools/mesh_export.py --case .
<QFlux-Python> tools/qflux_case.py setup-basic --case .
<QFlux-Python> tools/qflux_case.py inspect --case . --output checks/readback
python tools/run_solver.py --case . --stage baseline
<QFlux-Python> tools/qflux_case.py export --case . --stage baseline --output post/baseline
python tools/solution_check.py --case . --stage baseline
python tools/package_artifacts.py create --root . --manifest delivery.json --output <新压缩包.zip>
```

`setup-basic` 和 `export` 需要独立进程，且输出目录必须新建。正式案例的建模脚本可用 FreeCAD、Gmsh/OCC 或用户现有工具替换 `duct.py`，输出遵守契约即可。使用前 `--help` 查看参数。

## 交付要求

给出最终模型、米制网格、原生工程、必要完整结果场、设置和检查记录、云图/统计、运行方法及局限。用显式 `delivery.json` 选择文件，不把缓存、失败中间文件、临时运行时、许可证或连接信息打包。压缩包内置 SHA256 清单并执行 CRC/内容校验。未完成的求解或未经验证的物理功能明确标为未完成。

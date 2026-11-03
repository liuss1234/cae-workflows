# 七叶风扇参考实现

## 适用范围

附带 `assets/fan-example.FCStd` 是此次已验证输入的独立快照。该示例有七片叶片、四根后支撑、轮毂/锥罩、电机和 140 mm 外框，圆形内流通道直径为 130 mm。叶型为建模演示形状，未进行气动优化。

示例几何脚本要求 `FrameFinal`、`Hub`、`HubCap`、`MotorHousing`、`BladeMaster`、`BoreTool`、`BladeLink*` 和 `SupportArm*` 对象，核对叶片/支撑数量及同轴性。新模型不满足该结构时应另外适配，不放宽检查后硬套。

初始几何参数：入口 +Z、出口 −Z，入口延长 2D、出口延长 5D，旋转轴为通过原点的 Z 轴，转速为空。这些是本例已有选择，不是其他风扇或烘箱的默认工况。

## 脚本清单

| 文件 | 功能 | 限定 |
|---|---|---|
| `probe_environment.py` | 只读核对程序路径与两套 Python ABI | 通用本机环境检查 |
| `qflux_handoff.py` | 导入/保存/回读，并逐项比对预期分区与边界 | 任意满足外部清单结构的 QFlux 网格；不配置运行工况 |
| `run_fan_example.py` | 初始化新工作目录并编排各阶段 | 七叶风扇示例 |
| `fan_example/draw_axial_fan.FCMacro` | FreeCAD 可见连续建模，无人为步骤停顿 | 生成演示模型，默认不自动替换快照 |
| `fan_example/build_fan_cfd.py` | 几何清理、三个流体体积、12 个 CAD 边界面组、几何核验 | 特定对象结构；长度 mm |
| `fan_example/export_face_signatures.py` | 输出面面积/形心/区域签名 | 给 Gmsh 导入恢复标签 |
| `fan_example/mesh_fan_gmsh.py` | fragment 共享拓扑、分组、局部尺寸、调用 Gmsh 划网格 | 一阶四面体，无棱柱边界层 |
| `fan_example/check_fan_mesh.py` | 独立回读质量、拓扑、面覆盖、区域体积和接口邻接 | 示例 manifest；报告长度 mm |
| `fan_example/export_fan_si.py` | 坐标转 m、命名映射、多区 CGNS、MSH 2.2 ASCII、独立回读 | 已验证示例一阶网格；本机 CGNS DLL |
| `fan_example/show_fan_cfd.FCMacro` | FreeCAD 内提供三域/旋转域/剖切显示 | 剖切体仅显示，不能作为网格输入 |

## 运行

先执行环境检查。新目录必须不存在；脚本会复制输入快照与可调模板到新项目，不修改技能内的模板。所有可调几何/网格参数在项目 `scripts` 中各文件头部。

```powershell
$cfdPython = (Get-Command python).Source
$cfdRunner = 'skills/freecad-gmsh-qflux/scripts/run_fan_example.py'

# 使用附带快照，从几何生成到 QFlux 保存/回读连续执行。
& $cfdPython $cfdRunner all --workspace 'cases/fan_cfd_new' --profile 'local/fan-environment.json'
```

如需调参数，先 `init`，修改新工作目录中的模板，再依次执行 `geometry`、`mesh`、`quality`、`export`、`qflux`。软件路径变化使用 `--profile 自己的环境.json`。不要对同一项目并发运行相互依赖的阶段。

`draw` 和 `view` 是显式 GUI 阶段，分别演示新建风扇、展示已有 CFD 几何；它们不在 `all` 中自动运行。修改了绘制参数后，先核对新模型，再用其快照初始化新的 CFD 项目。

每次调用记录单独日志。几何、网格和导出有各自的 `latest_*.json` 指针，使用前确认路径和上游成功状态；日志失败时不要继续下游。重跑 quality 会更新该网格目录内的质量报告，已有报告需要保留时先使用新的网格目录。

## 验证基准与完成边界

2026-10-14 用户验收的网格：202,985 个全局唯一节点、1,017,036 个四面体、3 个网格区、12 个边界侧面；最小 minSICN 0.2832695，最大内部面非正交角 67.405°；无负体积、重复四面体或非流形面。

本次封装验证时应从新输出读取实际数值。并行网格算法或版本变化可能影响单元数，不能把基准数值写死为每次结果必须相等。

封装后的完整复跑于同日通过：在独立测试目录从附带快照开始，实际生成 202,790 节点、1,015,820 四面体；最小 minSICN 为 0.2426326，无负体积或非流形面，基础检查通过。米制 CGNS 经 Gmsh 回读及 QFlux 导入、保存、独立回读后仍有 3 个网格区、12 个边界。单元数与原验收版本不同，进一步验证了检查工具使用新清单而不是写死旧网格数量。

10 个 Python/宏脚本完成语法解析；环境导入检查、技能结构检查和相对文档链接检查通过。新目录复跑覆盖批处理计算链，GUI 宏为此前交互中使用过的模板，此次封装未再启动 GUI 演示。

已验收的是米制几何、命名分区及 QFlux 识别。两对接口的四个侧面均独立命名，但接口持久化耦合和转速尚未完成。示例脚本只给出实测状态，不启动求解。

## 迁移到其他模型

保留环境检查、米制转换规则、明确分组以及 QFlux 清单比对方法；重新设计零件集合、流体域、参考系、接口和网格尺度。期望数据由新网格生成，不复用本例的节点数/单元数。需要把转换程序用于一般 CAD 时，先适配 manifest、区域映射和接口邻接，另做小算例回读验证。

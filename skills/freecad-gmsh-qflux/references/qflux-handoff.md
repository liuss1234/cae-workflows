# 米制转换、QFlux 命名与原生工程交付

## 名称与单位

名称使用无空格的稳定英文标识符。`inlet` / `outlet` 被 QFlux 自动识别为进出口属于预期行为；用户关心的是每个边界独立可见、可选且名称完整。附加管壁用 `wall_duct_upstream` / `wall_duct_downstream`，使含义更清楚；在保存工程时显式设定 `wall_*` 的壁面类别。

| 对象 | 本例名称 |
|---|---|
| 流体网格区 | `fluid_inlet`、`fluid_rotating`、`fluid_outlet` |
| 入口/出口 | `inlet`、`outlet` |
| 转子壁面 | `wall_rotor` |
| 静止部件壁面 | `wall_stator`、`wall_stator_rotating` |
| 管壁 | `wall_duct_upstream`、`wall_duct_rotating`、`wall_duct_downstream` |
| 上游接口 | `interface_inlet_stationary` ↔ `interface_inlet_rotating` |
| 下游接口 | `interface_outlet_stationary` ↔ `interface_outlet_rotating` |

这些是本例命名，不能作为所有模型固定的 3 区/12 边界约束。通用检查脚本从外部清单读取期望对象。

mm → m 要对节点坐标乘 0.001。面积乘 1e-6，体积乘 1e-9。仅改单位标签不能替代缩放，已是米制的文件不能再次缩放。检查实际包围盒、至少一个已知尺寸和总流体体积。

## 格式经验

- 本例最初 MSH 4.1 binary 在目标导入路径未被正确解析；MSH 2.2 ASCII 可读。此结论是目标版本与当时路径的实测，不能泛化成所有 QFlux 都不支持 binary。
- 即便 MSH 能导入，物理分组可能未被该导入路径正确恢复。多区 CGNS 能显式表达网格区、区域内边界与接口节点对应关系，是本例推荐交换格式。
- 每个 CGNS Zone 使用自己的节点序号，接口节点在两区各存一份。各区节点数之和大于全局唯一节点数属于正常情况；检查的是实际几何和单元连接。
- 三角面按各区外法向写入，四面体为正体积。每个区的外表面只能归类一次，不能漏标或重复。
- `fan_example/export_fan_si.py` 使用本机 `qxcgns64.dll` 原生 C API 写 CGNS/HDF5。当前库的 `cgsize_t` 为 64 位，换库前须确认 ABI；不要因名称含 64 就假定所有 CGNS 库如此。
- 本机已验证 `cg_units_write(2,2,2,2,3)` 表示 kg、m、s、K、rad。长度坐标也实际缩放。按 CGNS 名称长度限制保持名称不超过 32 字节。
- 手工用 h5py 拼 HDF5 节点曾得到目标软件无法读取的文件。h5py 可用于独立回读，但不以“HDF5 可打开”证明 CGNS 合规。标准写入后还需 Gmsh 和 QFlux 回读。

## QFlux 组织规则

同一流路的三个网格区在本例中放在一个流体求解计算域 `fluid` 下。旋转运动应分配给 `fluid_rotating`；不必为了显示三个网格区而创建三个独立求解计算域。

本机曾在跨独立求解计算域设置接口时提示 energy equation is off。不要因此开启能量方程；先检查区域组织是否符合物理问题。

`ICmdSetBoundaryPaired(..., CBCInterfaceBoundary())` 在此版本提示 target boundary condition is not a paired condition。`ICmdSetBoundaryInterfaceGroup` 可以改变边界类型，但当前导出仍有 `interfaceGroup=[]`；自动匹配也没有给出持久化分组证据。因此附带工具只设置/检查 Interface 类别，报告接口组数，**不承诺求解耦合已就绪**。需要接口设置时继续依据本机版本文档/GUI 实际状态操作和复核。

不要将 `interface_pairs` 这种脚本自己写入的预期列表当作已配对证据。有效验证应来自 QFlux 的实际对象/序列化设置，以及需要时的接口连接或守恒检查。

## 通用检查工具

`scripts/qflux_handoff.py` 使用独立 Python 3.8 进程，输入 CGNS 或 QFX 和期望 JSON。它验证：

- 完整网格区名称集合、节点数、体单元数；
- 每区边界名称、三角面数；
- QFlux 边界管理器名称、所属网格区与实际类别；
- 各区米制包围盒；
- 显式接口组和运动属性的实际数量，分别报告未验证的求解状态。

期望 JSON 的最小结构（省略具体数值时不能运行，以下为结构说明）：

```json
{
  "units": "m",
  "regions": {
    "fluid_zone": {
      "cells": 1,
      "nodes": 4,
      "bbox_m": [[0, 0, 0], [1, 1, 1]],
      "boundaries": {"wall_surface": 4}
    }
  }
}
```

实际使用 `si_export_check.json` 中的测量数据，不以这个结构示例作为模型参数。无固定区数、面数或管径。

```powershell
# 从本机配置读取 Python 和安装目录，不依赖原开发电脑路径。
$fanEnvironment = Get-Content local/fan-environment.json -Raw | ConvertFrom-Json
$handoffScript = 'skills/freecad-gmsh-qflux/scripts/qflux_handoff.py'

# 导入并保存为新的原生工程；网格与清单路径按实际导出位置填写。
& $fanEnvironment.python_qflux $handoffScript `
  'cases/fan_cfd_m.cgns' --expected 'cases/si_export_check.json' `
  --qflux-directory $fanEnvironment.qflux_directory `
  --output-dir 'cases/qflux_import_new' --save-project

# 在另一个进程打开刚保存的工程，再核对名称与尺寸。
& $fanEnvironment.python_qflux $handoffScript `
  'cases/qflux_import_new/project.qfx' --expected 'cases/si_export_check.json' `
  --qflux-directory $fanEnvironment.qflux_directory `
  --output-dir 'cases/qflux_reopen_new' --open-case
```

输出目录必须不存在，避免覆盖旧报告和工程。原生 API 会输出较多日志，建议重定向到单独日志文件；查看 JSON 时按字段解析，避免打印整行巨大 settings.json。`.qfx` 保存成功之后仍须独立回读。

## 版本依赖 API

以安装目录 `qfxPyApi/*.pyi` 为准。此版本已使用：`qxapp.initialize()`、`getActiveModel()`、`ICmdImportMesh`、`ICmdSetRegionName`、`ICmdSetRegionZone`、`ICmdSetBoundaryCondition(BC, Property)`、`ICmdSaveCase`、`ICmdOpenCase`、`ICmdExportCaseJson`。

保存采用 `fileType=1` 与 `ESaveCasePersistence.ProjectFile`；回读采用 `onlyLoadCase=True`。脚本未调用任何启动求解命令。

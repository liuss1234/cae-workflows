# 数据契约与适配方法

## 案例结构

```text
case/
  case.json                 几何、工况、网格、求解、验收、后处理参数
  environment.json          当前机器路径，默认不交付
  regions.json              实际期望区/边界/接口语义清单
  adapters/                 几何和物理适配器
  tools/                    自包含通用工具
  cad/                      STEP、FCStd、几何检查
  mesh/                     米制 MSH、CGNS
  checks/                   网格/回读/验收证据
  runs/<stage>/             独立阶段，stdout/stderr、监测、完整 DAT
  post/<stage>/             官方场导出、云图、统计
  delivery.json             显式交付文件列表
```

配置相对路径均以案例根目录为基准。脚本拒绝越界路径和覆盖已有关键产物。更换几何/参数用新案例目录或修改输出路径，不能用旧检查证明新模型合格。

`init_case.py` 把执行工具复制进案例。技能升级后旧案例不会自动改变，便于复现；需要更新工具时确认版本和重做相关检查。

## 区域清单

以下只展示结构，数值与名称由适配器根据模型生成：

```json
{
  "units": "m",
  "zones": [
    {
      "name": "fluid_main",
      "physical_volume": "fluid_main",
      "kind": "fluid",
      "region": "coolant",
      "bbox_m": [[0, 0, 0], [0.12, 0.01, 0.01]],
      "cad_volume_m3": 0.000012,
      "boundaries": [
        {"name": "inlet", "physical_surface": "inlet", "role": "velocity_inlet", "condition_class": "CBCVeloInlet"},
        {"name": "outlet", "physical_surface": "outlet", "role": "pressure_outlet", "condition_class": "CBCPressOutlet"},
        {"name": "wall_duct", "physical_surface": "wall_duct", "role": "wall", "condition_class": "CBCWall"}
      ]
    }
  ],
  "interfaces": []
}
```

- `zones` 是 CGNS 网格区，`region` 是 QFlux 求解计算域。多个区可属于同一流体计算域；多材料固体按求解器要求划分计算域/材料。
- `physical_volume`、`physical_surface` 对应 Gmsh Physical Group 名称。导入/fragment 后重新分类并赋组，不依赖面编号。
- 网格区与边界标识符为英文/数字/下划线，字母开头、全案例唯一、不超过32字节；避免 CGNS 保留节点名称。
- 同一共形面可对应同一个 `physical_surface`，但两侧 `name` 必须不同，例如 `interface_air_side`、`interface_solid_side`。
- 共形接口格式为 `{"a":"interface_air_side","b":"interface_solid_side","kind":"conformal"}`。工具校验共享面和相反法向，并写双向节点连接；**不等于 QFlux 物理接口已经正确配对**。
- `condition_class` 填本机 API 实际类别；CHT 接触、旋转或特殊出口按真实版本确定，不能凭名称猜。

## 几何适配器

输入：`case.json` 的 `geometry`、`mesh`、原始 CAD、软件环境。

输出：STEP/可选 FCStd，具有完整 Physical Groups 的一阶网格，以及 `regions.json`。可用 FreeCAD/OCC 构造实体，再用 Gmsh 读 STEP；或直接 Gmsh/OCC。`assets/duct.py` 演示单位、布尔后面重分类和多区接口，改变 `geometry.segments` 可测试任意正整数串联区数。

若直接提供高质量 CGNS/其他单元，可跳过 `mesh_export.py`，但应生成等价 `checks/mesh.json`：

```json
{
  "units": "m",
  "cgns_sha256": "实际CGNS文件散列",
  "zones": {
    "fluid_main": {
      "nodes": 0,
      "cells": 0,
      "bbox_m": [[0,0,0],[1,1,1]],
      "boundaries": {"inlet": 0, "outlet": 0, "wall_duct": 0}
    }
  }
}
```

示意中的0必须替换为实际测量数量；不可直接拿这份结构示意验收。网格报告同时记录单元类型、负体积、质量定义/分布、CAD体积误差、边界覆盖和限制。

## 物理适配器

`setup-basic` 只覆盖单流体、稳态、等温、指定的常物性和普通进出流边界。输入不是这个范围时，明确编写 `adapters/setup_physics.py`。可导入 `tools/qflux_case.py` 中 `bootstrap`、`scalar`、`add_monitor` 等工具；自身也要处理厂商原生生命周期。

输出：`case.files.qfx`；成功后单独进程执行 `qflux_case.py inspect`。将待核对的关键持久化设置写入 `case.json` 的 `qflux_assertions`：

```json
[
  {"pointer": "/region/0/solver/energy", "equals": true}
]
```

这是 JSON Pointer 精确断言，支持对象键和数组索引。数组顺序/字段路径以本次导出的真实 `settings.json` 为准，不能盲用示例。对高级物理，需涵盖接口双侧、运动区、转速、材料、热源及有效边界定义；仅断言 `energy=true` 不足以证明 CHT。

## 求解和结果契约

`run_solver.py` 记录 QFX 哈希、配置哈希、进程、时间和命令，完成后记录退出码、末场路径、迭代号和 DAT 哈希。输入工程必须先有相同哈希的成功独立回读。每阶段只对应一套网格和工程；改变设置要保存新 QFX/新阶段并重做回读。

后处理适配器只接受官方导出及其 `check.json`。CSV 统计必须写明单位、面选择、平均方式和计算来源；重构积分不能伪装成求解器面通量。

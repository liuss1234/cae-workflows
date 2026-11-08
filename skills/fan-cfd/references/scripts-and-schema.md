# 脚本、证据格式与迁移

## 依赖与执行

普通工具：Python 3.8+ 标准库。混合 CGNS 导出额外需要 NumPy 和匹配整数 ABI 的 CGNS C 库；库路径与 `--cgsize-bytes` 由目标安装明确提供。CAD 检查需要 FreeCAD/OCC 兼容 Python。QFlux 适配需厂商支持的 Python/位数和 `qfxPyApi`，不要向厂商 Python 强行安装普通运行环境依赖。

| 脚本 | 输入与产物 | 范围 |
|---|---|---|
| `fan_case.py init` | 新案例目录、源文件 → 来源副本、SHA256、case.json | 不覆盖已有目录；null工况需补充 |
| `fan_case.py validate` | case.json → 配置检查 | 显式区域/边界/参考系/层策略和旋向一致性 |
| `cad_audit.py` | STEP、坐标到米倍率 → CAD检查JSON | 不修复、不验证表面偏差 |
| `export_cgns.py` | NPZ+显式plan+C库 → CGNS及计数清单 | 线性TET4/PYRA5/PENTA6/HEXA8，TRI3/QUAD4；不包含NGON/NFACE多面体 |
| `fan_case.py check-mesh` | 实测证据、原网格 → mesh_gate.json | 核对哈希、单元类型、质量及实际层覆盖 |
| `qflux_adapter.py setup/readback` | 完整case、网格准入 → 新QFX/独立回读 | 详见[QFlux范围](qflux.md) |
| `run_solver.py` | 回读证明、QSolver路径、磁盘预算 → 作业记录 | 默认只检查，--execute启动已授权阶段 |
| `analyze_history.py` | 真实监控历史、列/窗口/阈值 → 稳定统计 | 不自动判定整体收敛 |
| `self_test.py` | 无商业依赖、无客户数据 | 合成逻辑检查，不运行风机仿真 |
| `create_smoke_case.py` | NumPy、CGNS动态库 → 四区32个六面体的安装案例 | 只检查软件链路，几何为规则方块，不代表风机或叶片层算法 |

复制整个 `fan-cfd/` 到 `~/.codex/skills/`（或 `$CODEX_HOME/skills/`）即可发现 `$fan-cfd`；DeepSeek Harness 使用 `~/.dsh/skills/`（或 `$DSH_HOME/skills/`）。独立脚本从技能目录执行或传入完整路径；案例可以放任意位置。所有计算路径相对 case 根，`files.qfx/run` 改为新阶段后重新准入、setup/readback。不要手改旧哈希以绕过不一致。

## 配置口径

完整模板位于 [case.example.json](../assets/case.example.json)。区/边界名称均为示例，可全部替换；同一网格区只出现一次，边界全局唯一。`bbox_m` 顺序为 `[xmin,ymin,zmin,xmax,ymax,zmax]`，脚本已转换 QFlux 原生交错包围盒顺序。入口压力为表压总压，出口压力为表压静压；环境绝对压力另存。

物性、rpm、旋向视线、层参数和阈值保持案例显式输入。`first_height_m` 与 `total_thickness_m` 至少一项明确，同时填写时与增长率计算一致。采用壁函数不能省去实际层覆盖/y+核验。

## 统一实测网格证据

将生产工具生成的证据放到 `checks/mesh_evidence.json`，然后执行：

```text
python scripts/fan_case.py check-mesh --case <case> --evidence <case>/checks/mesh_evidence.json
```

下面仅说明字段结构，数值不能复制为产品检查结果。每个区、每个边界都要出现，不能只报告转子：

```json
{
  "producer": "实际软件版本和检查脚本",
  "quality_method": "实际拓扑/体积/非正交算法与原始报告来源",
  "mesh_sha256": "实际网格sha256",
  "zones": {
    "任意区名": {
      "cells": 123,
      "bbox_m": [0, 0, 0, 1, 1, 1],
      "cell_types": {"tetra": 100, "prism": 20, "pyramid": 3},
      "quality": {"nonpositive_cells": 0, "invalid_topology_cells": 0, "min_volume_m3": 1e-12, "max_nonorth_deg": 70, "volume_error_fraction": 0.001}
    }
  },
  "boundaries": {
    "任意壁面名": {
      "zone": "任意区名", "faces": 10, "area_m2": 1.0,
      "layer_count_area_m2": {"0": 0.01, "1": 0.04, "5": 0.95},
      "unmatched_area_m2": 0.0,
      "actual_total_thickness_m": {"min": 0, "median": 0.0002, "max": 0.0003}
    }
  }
}
```

压力开口/接口只需 `zone/faces`，壁面另需面积、实际层直方图和厚度统计。`layer_count_area_m2` 的key是实际生成层数，value是对应完整壁面面积，包含零层；不得用请求值或总棱柱数填写。面积和与真实完整壁面面积一致，未匹配面另报；接口面积/法向相容性仍需原生或独立几何检查。

报告支持 NGON/NFACE 多面体统计，内置导出器则只支持所列线性混合单元。STAR 多面体直接使用其经核验原生 CGNS 导出。形状质量、闭合误差、层碰撞、y+ 等详细数据保留原报告；统一门槛不是全部质量指标的替代品。

## 混合 CGNS 输入

`export_cgns.py` 的plan例如：

```json
{"input_units":"mm","zones":{"任意ASCII区名":{"arrays":"zone.npz","boundaries":{"wall_a":"wall","side_a":"interface"}}}}
```

NPZ 必须显式包含 `xyz[N,3]`、`tetra[N,4]`、`pyramid[N,5]`、`prism[N,6]`、`hexa[N,8]`、`tri[N,3]`、`quad[N,4]`、`patch[Ntri]`、`quad_patch[Nquad]` 和单字符串 `metadata`（内容为 `{"names":["wall_a","side_a"]}`）。空类型仍放形状正确的空数组。节点从0计，面组索引对应 names；数组节点顺序需遵循CGNS。多区各用自身节点。导出器不推断边界角色，不补丢失的面，不修改负体积。

```text
python scripts/export_cgns.py --plan <plan.json> --output <新mesh.cgns> --library <CGNS动态库> --cgsize-bytes <4或8>
```

输出计数清单不证明质量，必须另做实际拓扑/质量检查以及 QFlux 回读。所有客户产物、本机连接配置和厂商库均不随技能发布。

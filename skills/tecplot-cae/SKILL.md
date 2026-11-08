---
name: tecplot-cae
description: 基于公开 Tecplot 经验，处理 Fluent 三维数据分开导出、局部切面云图和局部三维流线；适用于 Tecplot 360 后处理组织与显示，不把插值或消隐当作物理验证。
---

# Tecplot CAE 经验工作流

先确认数据来源、Zone 类型、变量名、坐标单位和目标图形，再选择局部 Zone、切面或流线流程。所有显示操作都应保留原始数据帧和变量，不覆盖原始结果。

## 按任务读取

| 任务 | 资料 |
|---|---|
| Fluent 三维数据导出与合并 | [fluent-export-merge.md](references/fluent-export-merge.md) |
| 局部切面云图 | [local-slice.md](references/local-slice.md) |
| 局部三维流线 | [local-streamlines.md](references/local-streamlines.md) |
| 来源、范围和版本边界 | [sources.md](references/sources.md) |

## 工作顺序

1. 记录源文件、变量清单、Zone/Frame 结构、单位和坐标系。
2. 复杂三维结果优先把体数据与边界/截面数据分开组织，再在同一 Frame 中追加。
3. 局部切面先建立目标 Zone 和空间范围，再线性插值需要的变量，最后只显示目标 Zone。
4. 局部流线先准备速度分量和种子面，再生成流线、着色和必要的 Value Blanking。
5. 保存原始数据、操作记录和最终布局；在报告中区分原始求解数据与后处理插值数据。

## 关键约束

- Rectangular Zone 的节点数影响显示分辨率和插值成本，但不会增加原始 CFD 数据精度。
- 规则 Zone 穿过固体、空域或多个不连续流体区时，插值可能缺值或产生异常；应检查覆盖范围和有效数据比例。
- Value Blanking 只控制显示，不裁剪或修改原始流场。
- 流线形态和颜色是可视化结果；流动分离、涡结构和速度结论仍需结合原始场、壁面量和数值验证。

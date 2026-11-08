---
name: pointwise-cae
description: 基于公开 Pointwise 翼型教程，规划 NACA0012 几何、C-H 结构网格、T-Rex 边界层和局部加密；适用于 Pointwise 入门与网格策略审查，不包含商业软件安装或许可绕过。
metadata:
  version: "1.0.0"
---

# Pointwise CAE 经验工作流

用于把二维翼型教学中的 Pointwise 操作抽象为可迁移的前处理检查。输入应包括翼型坐标、远场范围、求解器、湍流/壁面处理和目标 y+；没有这些信息时只给方案和假设，不把教学参数当成产品默认值。

## 按任务读取

| 任务 | 资料 |
|---|---|
| 坐标与翼型曲线 | [airfoil-geometry.md](references/airfoil-geometry.md) |
| C-H 结构化网格 | [structured-ch-grid.md](references/structured-ch-grid.md) |
| T-Rex 非结构网格 | [trex-unstructured-grid.md](references/trex-unstructured-grid.md) |
| 来源、范围和版本边界 | [sources.md](references/sources.md) |

## 工作顺序

1. 清理并检查坐标顺序、前缘/尾缘闭合、弦长归一化和几何法向。
2. 根据外流场尺度和尾迹范围建立远场拓扑；不要直接沿用示例尺寸。
3. 选择 C-H 结构拓扑或非结构 T-Rex 路线，记录节点分布、首层、增长率、层数和局部加密。
4. 检查最小体积、正交性/偏斜、边界层连续性、尾缘和远场过渡，再导出到目标求解器复核。

## 关键约束

- 首层高度由目标 y+、局部速度、物性、湍流模型和壁面处理共同决定；不能用“有边界层”替代 y+ 验证。
- C-H 拓扑的块连接、尾迹方向和 C 形包络决定网格质量；结构化不自动等于高质量。
- T-Rex 的层数、增长率和总厚度必须检查实际生成结果；参数被接受不等于所有壁面都覆盖成功。
- 仅把教学视频或截图复现出来不构成网格无关性、求解收敛或气动性能验证。

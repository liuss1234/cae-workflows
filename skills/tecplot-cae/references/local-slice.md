# Tecplot 局部切面

适用场景：只希望显示流体域内部一个规则局部区域的切面，而不是对整个 Fluid Zone 做贯穿切面。

## 流程

1. 使用 `Data → Create Zone → Rectangular` 创建包围目标区域的规则 Zone，设置 I/J/K 与 X/Y/Z Min/Max。
2. 使用 Probe 或已有几何坐标确定两个对角点，检查新 Zone 的包围盒、位置和厚度。
3. 在 `Data → Interpolate → Linear` 中，以原始流体 Zone 为 Source，以 Rectangular Zone 为 Destination，选择实际需要的变量。
4. 关闭原始大 Zone 的显示，仅显示新 Zone，重新配置 `Slices → Slice Details` 制作局部切面。

## 参数与限制

- 20～50 个节点是普通显示的经验起点，不是通用精度标准；应按原始网格尺度、区域尺寸和出图目的调整。
- 只画压力时可只插值压力；后续要画流线，至少插值三个速度分量。
- 规则长方体最好完全位于连续流体域内。若穿过壁面、固体或复杂障碍物，应改用贴合几何的局部 Zone 或外部生成的目标网格。
- 插值后的 Zone 是后处理数据块；应在图注或报告中说明插值范围和变量来源。

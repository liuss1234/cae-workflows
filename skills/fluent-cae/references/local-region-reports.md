# Fluent 局部区域统计

适用场景：需要在流体区域内部提取压力、温度、速度或其他变量的局部统计量，并在计算中持续监测。

## 推荐流程

1. 在 `Solution → Cell Registers` 新建 Region Register，按几何形状或已有标记定义目标单元集合。
2. 用 Save/Display 或等效显示方式检查标记范围、位置和是否误选固体或外部区域。
3. 如果目标是独立显示、监测或体积分，使用 `Domain → Separate → Cells`，以 Register 标记原始 Cell Zone，生成独立的局部 Cell Zone。
4. 在 `Solution → Report Definitions` 中建立 Volume Report，例如 Volume-Average；按需要启用 Report File、Report Plot 或控制台输出。
5. 计算结束后，在 `Results → Reports → Volume Integrals` 选择 Mass-Average、Volume-Average、Integral、Minimum、Maximum 或 Sum，并把统计结果写出。

## 检查点

- 先验证局部区域的几何范围和单元数量，再解释统计值。
- 明确平均量的权重：Mass-Average 与 Volume-Average 不能混用。
- Separate 会改变 Cell Zone 组织；修改前保留原始 case/data，并检查接口、材料和区域物理设置是否仍符合预期。
- 局部报告反映所选单元和当前离散解，不自动代表整个设备的性能。

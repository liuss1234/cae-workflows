# Tecplot 局部三维流线

## 流程

1. 在 `Analyze → Calculate Variables` 计算 `Velocity Magnitude`，选择不归一化并确认变量位置与原始数据一致。
2. 用 `Data → Create Zone → Rectangular` 创建局部种子区域，检查它位于有效流体区内。
3. 在 `Slices → Slice Details` 中从 Volume Zones 提取目标位置的局部切面，把切面作为种子对象；只做种子面时不需要把矩形 Zone 插值成完整流场。
4. 在 Streamtrace Details 中选择 Volume Line、合适的方向和 `On Surfaces of Selected Objects`，设置种子数量并从局部切面生成流线。
5. 在 Contour 中选择速度大小，在 Streamtrace Lines 中用 Multi 着色。
6. 需要限制显示范围时启用 `Plot → Blanking → Value Blanking`，用坐标约束控制流线可见区，并在 Zone Style → Effects 中确认对象响应消隐。

## 解释边界

Value Blanking 只改变显示，不删除流线或原始数据。局部流线显示出回流或涡旋形态时，仍需结合速度梯度、壁面摩擦、涡量、时间分辨率和网格/时间步验证，不能仅凭图形宣布分离或涡结构已被物理确认。

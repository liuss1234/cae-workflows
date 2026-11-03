# 求解验收、后处理和交付

## 分开报告四种状态

| 状态 | 所需证据 |
|---|---|
| 文件链路有效 | CAD/网格检查，完整区与边界，QFX独立回读 |
| 求解完成 | 真实进程正常结束，日志，非初始化完整DAT，QFX/DAT来源一致 |
| 代数和工程量可接受 | 各有效方程残差、质量/能量守恒、工程量稳定窗 |
| 物理/网格精度充分 | 所需网格研究、近壁处理、模型适用性、基准/实验比较；不能由退出码推导 |

`solution_check.py` 仅检查配置的残差、守恒、稳定性及官方最终场回读来源。缺少必要项时返回2，不把未配置验收当通过。脚本报错返回1。`accepted=true` 不等于物理模型正确或工程认证。

## 可配置验收

残差：`validation.residual.file` 是阶段内历史文件，`columns` 是实际表头→阈值的映射，无固定方程数量。热算例包括有效温度/能量残差，湍流算例包括其有效方程。检查末迭代，不用初始下降幅度代替最终残差。

历史中曾有求解器末DAT比残差多1步的版本行为。默认不接受差异；仅在当前 stdout 同时明确 `Convergent: Residual` 与 `solver finished, code = 0`，差值恰为1，并在本次规则显式设置 `allow_final_iteration_offset=1` 时接受并记录证据。不能普遍放宽对齐。

质量：列出所有开口/源项的有符号求解器面通量，不把绝对值相加当收支。无质量源时误差百分比为 `100*abs(sum(mdot))/max(sum(positive),abs(sum(negative)))`。多支路内部截面不能与入口出口一起算外边界收支。

能量：`validation.energy_balance.terms` 可为 `{file,column,multiplier}` 或 `{constant_W,multiplier}`，按一致方向列出完整焓通量、热源、散热、轴功等；`normalization_W` 明确功率尺度，`limit_percent` 为误差限。例如热源输入用负号、外流焓净输出用正号。用户物理包含能量而未配置收支时报告未完成验收。

稳定性：`monitors` 列表各自有 `file,column,tail,relative_span_limit_percent,absolute_floor`。波动定义为窗口 `(max-min)/max(abs(mean),absolute_floor)*100%`。接近零的力分量/压差要报告绝对幅值及分母，不能用随意大下限掩盖不稳定。支路监测选择同物理方向、同统计口径。

阈值根据目标和物理确定，不把直管自检的1e-5、0.1%等套用全部任务。接受标准改变时保留原始日志，说明原因，不改写历史文件。

## 后处理与工程统计

1. 只用已完成场，通过官方 API 导出。确认网格区、字段和 QFX/DAT 哈希；初始化00000不是结果。
2. 优先用求解器原生监测通量/力/热流；节点/单元场重构积分另列方法、误差。映射原始网格和导出场时先核验节点排序/单元连接，不能凭数组长度相同就套用。
3. 云图标明变量、单位、截面位置、方向、色标和来源。质量/面积/体积加权均值不能混用。近壁峰值、压力参考和绝对/相对速度写清楚。
4. 多支路表至少包含支路ID、Q、占比、平均偏差和总量误差。优化比较同时给出基准、改后、差值/降幅及模型限制，不编造实验误差。

真实TET4截面例子：

```text
python tools/plot_vtu.py --case . --stage baseline --vtu <实际VTU相对路径> --field Pressure --unit Pa --axis y --position 0.005 --output post/pressure_slice.png
```

字段是 VTU 的实际 `DataArray Name`，可能是显示名 `Pressure` 而非内部 `p`；读取导出文件确认。自定义导出目录用 `--source-check <目录/check.json>`。不能拿脚本示意图充当云图。

## 最终工程说明

用适合任务的简短技术报告，至少包含：几何/简化和单位、材料来源及温度范围、边界条件表、网格规模与质量定义、湍流/能量/旋转模型、数值设置、收敛与守恒、用户要求结果、未完成/局限。网格收敛研究按用户范围决定；未做则明示，无须强制增加计算。

## 打包

更新 `delivery.json.files` 为实际文件的显式相对路径。推荐包括：最终STEP/FCStd、米制CGNS/必要MSH、源QFX、必要完整DAT、case.json、适配器/工具、CAD/网格/设置回读/验收JSON、stdout/stderr和监测、统计CSV、真实云图和说明。不要把旧场、失败缓存与最终结果混在同一级交付名中。

```text
python tools/package_artifacts.py create --root . --manifest delivery.json --output <新案例包.zip>
python tools/package_artifacts.py verify <案例包.zip>
```

打包脚本拒绝机器私有 `environment.json`、软件二进制和常见密钥后缀；显式清单仍须检查内容不含凭据。接收方重新填写自己的环境。ZIP内有逐文件SHA256和大小，外部生成ZIP SHA256，校验包含CRC与全部条目一致性。

无用户清理要求时不主动删除原案例。获准清理时先以交付清单确认最终STEP/网格/QFX/必要DAT/证据均可回读，再只清理已识别的重复中间文件；保留可恢复性并报告位置。

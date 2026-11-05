---
name: fan-cfd
description: 完成散热风机、轴流风扇及吊扇的 CFD 几何清理、流体分区、STAR/Gmsh 网格、QFlux 稳态 MRF 配置与计算验收；适用于 CAD 到风量和速度云图交付，以及无边界层、接口或旋向错误、求解发散排查。
---

# 风扇行业 CFD

从已确认的 CAD 和工况推进用户授权的阶段，保留真实叶型、外框内流边界和案例来源。优先继承对话中的转速、旋向观察方向、介质、网格要求及计算资源，不重复询问已知信息。独立使用本目录，不要求安装其他 CFD skill。

## 按阶段读取

| 当前任务 | 操作与资料 |
|---|---|
| 几何清理、流体域 | 阅读 [geometry-domains.md](references/geometry-domains.md)，保留源 CAD，记录修复与保形证据 |
| STAR 或 Gmsh 网格 | 阅读 [meshing.md](references/meshing.md)，参数化层厚、实际层数及质量门槛 |
| QFlux 工程与计算 | 阅读 [qflux.md](references/qflux.md)，显式绑定网格区、接口和壁面参考系，保存后独立回读 |
| 不稳定、速度超限、非正交 | 阅读 [diagnostics.md](references/diagnostics.md)，分阶段试验并记录实际开关 |
| 风量、云图、跨软件对比 | 阅读 [results-delivery.md](references/results-delivery.md)，使用真实最终场和统一统计口径 |
| 安装、脚本参数、迁移范围 | 阅读 [scripts-and-schema.md](references/scripts-and-schema.md) 与 [validation.md](references/validation.md) |

## 关键工程约束

- 清理依据实际流道：保留叶片、叶尖间隙、内框和静叶；用户允许时删除外部装饰及小安装特征。基本有效/封闭不能代替自交、保形和独立 STEP 回读检查。
- 流体域按物理和交付要求拆分。开放风机可用 `in/out/stator/rotor`；吊扇试验室可用房间和旋转区；名称与数量由模型决定。多个网格区可共同属于一个流体求解域。
- 固定外框、静叶及固定电机表面即使落在 MRF 区仍使用全局参考系；叶片和随转轮毂使用旋转相对参考系。不能根据边界名称前缀推断物理类型。
- 请求层数与实际层数分开交付。局部小角度允许减层或缩薄，但需报告面积加权层覆盖、实际厚度、最差位置与整体质量；缺层网格不能冒充已完成边界层。
- 混合网格导出保留全部四面体、棱柱、四棱锥、六面体或多面体及边界，核对各类型数量与总体积。单位以实际坐标/包围盒验证为米，不能仅改文件名。
- 分别证明网格导入、接口配对、MRF 配置、求解结束、监控稳定和性能有效。达到指定步数不自动代表收敛；失败阶段不能参与有效性能对比。
- 转速、旋向、域尺度、层数/层厚、湍流模型、迭代数和验收阈值均为案例参数。历史型号的 2000 rpm、500 步或 5/2 层不能作为行业默认值。

## 配套工具

普通 Python 3.8+ 可执行以下命令；所有路径均可使用 Windows/Linux 的实际路径：

```text
python scripts/fan_case.py init --case <新案例目录> --source <原始STEP>
python scripts/fan_case.py validate --case <案例目录>
python scripts/fan_case.py check-mesh --case <案例目录> --evidence <真实网格验收JSON>
python scripts/analyze_history.py --help
python scripts/self_test.py
```

初始化复制 [参数模板](assets/case.example.json)；未知参数保留 `null`，填完并核验后才进入计算。`check-mesh` 验证具名质量指标与实际层覆盖证据，不生成网格，也不替代原生网格检查。

`qflux_adapter.py setup/readback` 提供单转子、多网格区、多接口的等温稳态 MRF 适配，支持压力入口/出口及闭式壁面。`run_solver.py` 只从配置哈希和独立回读均一致的新阶段启动。使用厂商匹配 Python，按 [QFlux说明](references/qflux.md) 操作；其他湍流模型、多转子、滑移或瞬态先适配目标版本。

---
name: ceiling-fan-cfd
description: 建立和复核吊扇试验室CFD案例，涵盖保形几何清理、内外屏流体域、Gmsh命名表面、STAR多面体棱柱层、QFlux稳态MRF、检测面风量和真实结果交付；适用于多款吊扇复算、网格失败及底壳或吊杆失真排查。
metadata:
  version: "1.0.0"
---

# 吊扇 CFD 试验工作流

将CAD、试验布置与工况连接为可追溯的几何、米制网格、工程、最终场和检测量。继承用户已确认的型号范围、转速、方向、软件和计算地点。新产品需重新识别部件与面；不能复用旧装配面号。来源及边界见[验证范围](references/validation-scope.md)。

## 启动

1. 运行 `scripts/fan_case.py init --case <目录> --source <STEP>`，只复制原件、创建三个一级目录和配置，不生成产品几何或启动计算。
2. 填写 `03日志脚本/03工况配置/case.json`。转速、方向、实际扫掠直径和安装基准应有依据；模板房间与网格参数是项目示例。
3. 按[安装与数据契约](references/portability.md)配置软件，运行 `scripts/fan_case.py validate --case <目录>`。普通Python、FreeCAD Python和QFlux Python按实际ABI分开。

## 按阶段读取

| 阶段 | 资料与工具 |
|---|---|
| 保形清理、填腔、底壳/叶型、STEP异常 | [几何](references/geometry.md)；FreeCAD运行 `scripts/cad_audit.py`，保存深度检查诊断 |
| 试验室、MRF包络、安装位置和检测面 | [流体域](references/domain.md)；`build_room_domain.py`接收已清理、统一轴的产品 |
| Gmsh表面、STAR多面体和五层覆盖 | [网格](references/mesh.md)；`gmsh_surfaces.py`检查/显式标面，`render_star_macro.py`生成宏，`check_poly_mesh.py`独立核对CGNS |
| QFlux设置、MCP/后台、独立回读、远端 | [求解](references/solver.md)；`qflux_adapter.py`配置/回读，`fan_case.py run`运行显式命令清单 |
| 监控、残差、守恒、真实云图与比较 | [验收](references/results.md)；`analyze_history.py`统计实际历史 |
| 成对QFX/DAT、历史及多款交付 | `fan_case.py pack/verify`按显式清单打包并核对SHA256 |

## 关键工程判断

- **外形优先于面数。** 内腔、小装配槽和倒角按用户意图局部填实；底壳圆弧、叶型、叶尖、安装角、扫掠范围和吊杆用原件截线/见证尺寸核对。轴向半径闭运算曾在端部生成额外平底圆柱，不能作为通用清理算法。
- **CAD与网格分别校核。** 吊杆失真可能源于STAR表面重构误用远场尺寸；检查实际壁面杆径、长度覆盖和边长。旋转域里的固定杆段仍应绝对静止。
- **请求五层不等于生成五层。** 原生层号按真实叶片面积统计，回缩、抑制和拆出叶根面均在分母。历史接受99.28%仅适用已授权工况。层覆盖不代替首层厚度及y+验证。
- **区名、类型与物理关系均需回读。** 一个空气计算域可含静止/旋转两网格区。空接口组或仅设置Interface类型不证明配对。核对实际两侧、运动轴、物性及壁面参考系。
- **步数不代替验收。** 用户可按监控趋平判断稳定；分别报告运行完成、监控、残差、守恒和物理合理性。2000步、4核、一阶格式是本批参数，换工况可配置。修改几何/转速/数值时新建阶段。
- **完成后切换交付。** 明确QFX/DAT来源、步号、哈希、网格区和字段，官方API独立回读后再归档旧成对文件并更新该款索引，保护其他款。

不把项目内外屏布置称为已核实的测试标准，不将净向下圆面通量冒充任意标准风量。没有同口径实测就不给试验误差；没有网格无关性或y+核验就在报告明确。仅有实际MCP工具调用时称为MCP；API独立进程、SSH和GUI应分别记录。

# 安装、工具、数据契约

复制整个oven-fluid-cfd目录到宿主技能目录（Codex `~/.codex/skills/` 或 `$CODEX_HOME/skills/`，DeepSeek Harness `~/.dsh/skills/` 或 `$DSH_HOME/skills/`），保留相对结构；也可直接运行scripts。Python3.8+，合成自检不需要商业软件。独立技能不依赖其他技能安装；可用时结合cfd-case-workflow/qflux-slurm，但不能假定存在。

## 新案例

`oven_case.py init --output <新目录>`复制参数、命名清单及全部工具到tools；拒绝覆盖已有目录。新工况/单位/范围设为null或未确认；出口数量、真实边界清单、几何相关网格长度、离散方法与包围盒容差也留空。先依据当前模型填写`workflow.outlet_count`、`regions.json`中的实际边界及`mesh.wall_layer_spec`，再补齐长度、容差、单位、工况和依据；不能从公开模板推定产品数量或尺寸。填完后 `oven_case.py validate --case <目录>`：检查单流体域、1入口、匹配数量出口、唯一命名、全wall层参数、全部必要数值、路径限制与声明的假设。它不代替CAD或网格验收。

文件契约：

- `case.json`：geometry、physics、mesh、solver、files、validation、qflux_assertions和workflow；所有可调参数集中于此。
- `regions.json`：zones中name/kind/region/boundaries，每边界name/role；供风适配器使用fluid_supply网格区与air物理区；模板的boundaries为空，按实际CAD映射填写。
- `environment.json`：本地安装与连接配置，只在生成案例内填写，不能发布。
- `checks/cad_boundaries.json`：units=mm、bbox_mm=[[xmin,ymin,zmin],[xmax,ymax,zmax]]、volume_m3、groups=[{name,face_indices,...}]；必须先由真实几何适配器生成。
- `checks/<版本>_native_quality.json`：cells和quality，至少Volume.min、SkewnessAngle.max、FaceValidity.min。
- `checks/<版本>_<wall名>_layers.csv`：STAR原生面心、PrismLayerNumber、FirstPrismLayerHeight，列名保留，非手填请求层数。
- `checks/mesh.json`：cgns_sha256、units=m、zones内数量/bbox/面数和边界层面积审计、passed。
- `checks/diagnostic_authorization.json`（仅需要时）：authorized=true、reason、mesh_sha256，来自本次用户的明确诊断决定，不能工具自动填同意。
- `runs/<阶段>/finished.json`：官方导出前登记exit_code、qfx_sha256、final_data、final_data_sha256，值来自当前完整场实际核对。该记录不能单独证明收敛。

## 命令

```text
<FreeCAD-Python> scripts/cad_audit.py --input <STEP/BREP> --coordinate-units mm --output <新报告.json>
python scripts/render_star_macro.py --case <案例> --surface <命名ASCII-STL> --output <新目录>/MeshOven.java
python <案例>/tools/check_trimmed_mesh.py --case <案例> --mesh <相对CGNS> --output checks/mesh.json
<QFlux-Python> <案例>/tools/qflux_oven.py setup-basic --case <案例> --output checks/setup_R01
<QFlux-Python> <案例>/tools/qflux_oven.py inspect --case <案例> --output checks/readback_R01
python scripts/analyze_outlets.py --stage <阶段> --regions <清单> --region air --density <kg/m3> --window 100 --output <新目录>
```

宏渲染需要 `mesh.slot_boxes_m` 每项 `{name,low:[x,y,z],high:[x,y,z]}`，坐标以实际m几何确定，不含旧案例硬编码风嘴坐标。禁用slot_boxes_required只有明确无需窄缝局部加密时才做；不能偷偷用全局尺寸代替。

层覆盖检查需要 `assets/requirements-audit.txt` 的numpy/h5py；大网格在大内存机器运行。FreeCAD使用其可import Part的Python；QFlux使用与厂商ABI匹配的Python，不复制DLL。QFlux原生适配仅Windows实测，Linux用现场CLI/Slurm；普通初始化/统计为跨平台脚本。Java模板仅已实测18.06 API的参数化迁移，先独立小块验证。

## 公开包与来源

包中自编代码/文档继承仓库MIT许可。通用QFlux辅助来自本仓库cfd-case-workflow的本次项目快照，后续修复需留意两处；CGNS检查和STAR模板由本次实际案例参数化，未分发厂商实现。代码不是CAD特征自动识别器，几何清理须按新模型重建适配器。

单独ZIP包含技能顶层和逐文件SHA256清单，发布前CRC及SHA回读。公开内容只说明结构类型，历史真实结构数量/尺寸/逐部件清单不入包。合成自检的边界和长度仅验证程序行为。更换参数/数据后必须重跑相应阶段，合成自检不等于新模型可划分或可收敛。

逐壁面wall_layer_spec是表面尺寸、层数和总厚度的实际输入；修改全局base不会替换显式的局部壁面参数。导流板邻近点数在mesh.guide_proximity_points_in_gap配置。

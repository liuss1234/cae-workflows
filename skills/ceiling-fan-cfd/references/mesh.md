# 多面体、五层覆盖和吊杆

Gmsh在已验收流体CAD上建立Physical Volume/Surface，输出米制、每个solid有边界名的STL，各域单独文件。表面网格不等于带边界层体网格。

```text
python scripts/gmsh_surfaces.py inspect --case CASE --domain new_domain --output faces.json
# 根据面心/面积/包围盒与CAD核对，填写每区face_labels：{"tag":"wall_blades",...}。
python scripts/gmsh_surfaces.py mesh --case CASE --domain new_domain --labels faces.json --output new_surfaces
```

输入源哈希、Gmsh版本、单位变化或面标签不全时停止。需可视化核对产品面/接口，不把自动几何阈值当作通用装配识别。

STAR宏采用Surface Remesher + Polyhedral + Prism Layer，逐部件网格，两空气区独立，接口不挤壁面层。中间Dual过程可能使用四面体，最终类型以原生设置和导出NGON/NFACE为准。宏源自STAR-CCM+18.06.006（2310）验证；其他版本先查本机API并编译，不保证跨版本。

示例叶片5层、总厚1.2mm、增长1.2；h1=H(g−1)/(g^N−1)，g=1时H/N。只是设定厚度，不证明实际层数或y+。局部倒角/薄槽先定位并限域填实，不无限放宽挤层参数追求覆盖而引入负体积。

`check_poly_mesh.py --mesh fan.cgns --expect mesh_expect.json --output quality.json`只读检查。expect格式：

```json
{"zones":{"fluid_stationary_surfaces_m":{"cad_volume_m3":168.0,"boundaries":["wall_floor","wall_ceiling","wall_outer_screen","wall_inner_screen","wall_fan_fixed","if_rotor_stat"]},"fluid_rotating_surfaces_m":{"cad_volume_m3":0.1,"boundaries":["wall_blades","wall_hub","if_rotor_rot"]}},"max_volume_error_fraction":0.01,"max_relative_closure":1e-8,"blade_prefix":"wall_blades","requested_layers":5,"minimum_full_layer_fraction":0.9928,"layer_csv_directory":".","native_quality_json":"star_native_quality.json","max_skewness_angle_deg":90.0,"min_face_validity":0.95}
```

体积/门槛均为格式示意，使用真实CAD证据和用户接受标准。CSV由原生XyzInternalTable输出，按面心匹配PrismLayerNumber/FirstPrismLayerHeight。所有blade_prefix面均计入分母，缺CSV/不匹配不得跳过。非共面多边形体积使用统一面心逐边三角分片，闭合独立用有符号面积向量。

检查正体积、闭合、CAD体积差、边界完整、原生Volume/SkewnessAngle/FaceValidity；跨软件同名质量可能定义不同。五层覆盖不等于网格无关性。

吊杆失真曾来自0.12m远场尺寸误用到固定件。对固定件和转子内固定杆段加局部控制，核对实际杆径/覆盖长、边长P95/max、半径偏差和截面。4mm仅为历史示例，按真实杆径保留足够环向单元。修改几何后重新检查CAD→表面→体网格来源链。

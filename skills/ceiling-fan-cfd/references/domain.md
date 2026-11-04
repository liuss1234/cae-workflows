# 试验室、MRF和检测口径

历史项目示例为外室6.5×6.5×4m，内屏宽4.5m、底0.45m、顶3m、厚0.01m，上孔Φ1.8m，扇叶基准3m。它不是本技能确认的标准条款；新案例查试验报告中的屏材/开口/地面/顶面和安装基准。

指定基准面安装到目标高度，不能自动把几何最高点放到3m。记录源坐标→统一+Z轴→米制→试验室的变换。CAD可mm，网格节点必须实际m。

`build_room_domain.py`接受已经清理、轴为+Z、中心为X=Y=0的产品。配置还需填写`geometry.cleaned_blade_reference_z_cad`（源CAD单位）、`rotor_radius_m`、`rotor_z_range_m`、`fixed_split_z_m`。在FreeCAD兼容Python运行：

```text
<FreeCAD Python> scripts/build_room_domain.py --case CASE --fan cleaned.brep --output new_domain --audit domain_audit.json
```

其屏为四周实体薄壁＋顶板圆孔的参数化示例。实际为多孔、网布、开顶或不同缝隙时应修改域适配器，不能将示例屏阻力当作真实材料。

总空气A=房间−屏−固定件−转动产品；旋转空气Ar=A∩包络E，静止空气As=A−E。检查两域交叠为0、并集覆盖A、均正体积/封闭/深度有效。E包住完整扫掠体并留裕量；位于E内不等于固定吊杆也要旋转。

按邻接和实际外面恢复名称，不沿用布尔前face tag。语义为fluid_stationary/fluid_rotating、wall_floor/ceiling/outer_screen/inner_screen/fan_fixed/blades/hub、if_rotor_stat/rot。导出带后缀固定件仍保持静止。接口面积/位置应对应，非共形两侧面数可不同，实际配对才能求解。

已指定“离地1m、直径比风扇大0.8m”时：中心(0,0,1m)，Φ=D_swept+0.8m，法向−Z。不要与旧工况“扇下1.5D、Φ2D”混用。净通量∫U·n dA、仅向下分量、速度模积分和测点加权法要分清。m³/s转m³/min乘60；导出圆面积核对πr²，场重构与原生监测的差值另列。

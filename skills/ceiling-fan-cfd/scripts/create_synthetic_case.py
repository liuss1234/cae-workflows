# -*- coding: utf-8 -*-
"""FreeCAD合成几何迁移自检；只是矩形三叶演示，不代表真实产品或气动设计。"""
import argparse
import sys
from pathlib import Path
from fan_case import initialize,read_json,write_json,CONFIG_REL
from build_room_domain import build

# 合成自检参数，不供真实性能计算直接使用。
BLADE_COUNT=3
RPM=180
SWEPT_DIAMETER_M=.6021


def create(output):
    """在新目录生成简单封闭实体和示例双域，拒绝覆盖。"""
    import FreeCAD as App
    import Part
    root=Path(output).resolve()
    if root.exists():raise FileExistsError(root)
    root.mkdir(parents=True)
    fan=Part.makeCylinder(50,55,App.Vector(0,0,-30))
    for i in range(BLADE_COUNT):
        blade=Part.makeBox(280,50,4,App.Vector(20,-25,-2))
        blade.rotate(App.Vector(0,0,0),App.Vector(0,0,1),i*360/BLADE_COUNT)
        fan=fan.fuse(blade)
    fan=fan.fuse(Part.makeCylinder(8,130,App.Vector(0,0,20))).removeSplitter()
    source=root/'synthetic_fan_mm.brep';fan.exportBrep(str(source))
    case=root/'case';initialize(case,source);cfg=read_json(case/CONFIG_REL)
    cfg['operating'].update(rpm=RPM,direction_viewed_from_plus_z='clockwise')
    cfg['geometry'].update(swept_diameter_m=SWEPT_DIAMETER_M,cleaned_blade_reference_z_cad=0,
        rotor_radius_m=.36,rotor_z_range_m=[2.94,3.04],fixed_split_z_m=3.025)
    cfg['acceptance']['blade_full_layer_min_fraction']=.99;write_json(case/CONFIG_REL,cfg)
    output=case/'01模型文件/02清理后几何模型/synthetic/流体域'
    build(case,source,output,case/'03日志脚本/01日志与检查/synthetic_domain.json')
    print('SYNTHETIC_CAD_DOMAIN_PASS',case)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);a=p.parse_args()
    try:create(a.output)
    except Exception as exc:print(str(exc),file=sys.stderr);sys.exit(1)

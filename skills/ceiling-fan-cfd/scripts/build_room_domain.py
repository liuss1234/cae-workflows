# -*- coding: utf-8 -*-
"""在FreeCAD中从已验收、轴为+Z的清理产品建立参数化内外屏MRF双区。"""
import argparse
import math
import sys
from pathlib import Path
from fan_case import CONFIG_REL,read_json,write_json,validate_config,digest,positive


def build(case, fan_path, output, audit):
    """产品基准和包络必须显式填写；不识别或删改任意装配零件。"""
    import FreeCAD as App
    import Part
    cfg=read_json(Path(case)/CONFIG_REL);validate_config(cfg)
    g=cfg['geometry'];r=cfg['room'];out=Path(output)
    if out.exists():raise FileExistsError(out)
    reference=g.get('cleaned_blade_reference_z_cad')
    if not isinstance(reference,(int,float)) or not math.isfinite(reference):raise ValueError('需明确原清理CAD的扇叶基准z')
    radius=positive(g.get('rotor_radius_m'),'rotor_radius_m')*1000
    zrange=g.get('rotor_z_range_m');split=g.get('fixed_split_z_m')
    if not zrange or len(zrange)!=2 or not 0<zrange[0]<zrange[1]<r['height_m']:raise ValueError('需给出室内转子包络z范围')
    if not isinstance(split,(int,float)) or not 0<split<r['height_m']:raise ValueError('需明确固定/旋转产品的轴向分割面')
    if radius<=g['swept_diameter_m']*500:raise ValueError('转子半径未包住扫掠体')
    fan=Part.read(str(fan_path));scale=1. if cfg['units']['cad']=='mm' else 1000.
    if scale!=1:
        matrix=App.Matrix();matrix.scale(scale,scale,scale);fan=fan.transformGeometry(matrix)
    fan.translate(App.Vector(0,0,g['blade_reference_z_m']*1000-reference*scale))
    w=r['outer_width_m']*1000;h=r['height_m']*1000;inner=r['inner_width_m']*1000
    t=positive(r['screen_thickness_m'],'screen_thickness_m')*1000
    lo=r['screen_bottom_m']*1000;hi=r['screen_top_m']*1000
    if t>=hi-lo or t>=inner/2:raise ValueError('屏厚度不合理')
    room=Part.makeBox(w,w,h,App.Vector(-w/2,-w/2,0))
    shell=Part.makeBox(inner,inner,hi-lo,App.Vector(-inner/2,-inner/2,lo))
    cavity=Part.makeBox(inner-2*t,inner-2*t,hi-lo+2*t,App.Vector(-inner/2+t,-inner/2+t,lo-t))
    walls=shell.cut(cavity)
    lid=Part.makeBox(inner,inner,t,App.Vector(-inner/2,-inner/2,hi-t))
    aperture=Part.makeCylinder(positive(r['top_aperture_diameter_m'],'top_aperture_diameter_m')*500,3*t,App.Vector(0,0,hi-2*t))
    screen=walls.fuse(lid.cut(aperture)).removeSplitter()
    rotor=Part.makeCylinder(radius,(zrange[1]-zrange[0])*1000,App.Vector(0,0,zrange[0]*1000))
    def volume(shape):return 0. if shape.isNull() else abs(shape.Volume)
    if volume(fan.cut(room))>1e-3 or volume(fan.common(screen))>1e-3 or volume(rotor.common(screen))>1e-3:
        raise ValueError('产品超出房间或与屏碰撞，需校对安装/包络')
    air=room.cut(screen).cut(fan).removeSplitter()
    rotating=air.common(rotor).removeSplitter();stationary=air.cut(rotor).removeSplitter()
    top=Part.makeBox(w,w,h-split*1000,App.Vector(-w/2,-w/2,split*1000))
    shapes=dict(fluid_stationary=stationary,fluid_rotating=rotating,fan_product=fan,inner_screen=screen,
                wall_fan_fixed=fan.common(top).removeSplitter(),wall_fan_rotating=fan.cut(top).removeSplitter())
    reports={}
    for name,shape in shapes.items():
        if not shape.isValid() or not shape.isClosed() or shape.Volume<=0:raise ValueError('无效实体：'+name)
        shape.check(True)
        reports[name]=dict(volume_mm3=shape.Volume,solids=len(shape.Solids),faces=len(shape.Faces))
    overlap=volume(rotating.common(stationary));error=abs(rotating.Volume+stationary.Volume-air.Volume)/air.Volume
    if overlap>1e-3 or error>1e-8:raise ValueError('流体区交叠或体积不闭合')
    out.mkdir(parents=True)
    for name,shape in shapes.items():shape.exportBrep(str(out/(name+'_mm.brep')))
    result=dict(passed=True,source_sha256=digest(fan_path),units='mm',shapes=reports,
                overlap_mm3=overlap,volume_balance_relative=error,
                arrangement='parameterized project room; verify physical screen arrangement')
    write_json(audit,result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['case','fan','output','audit']:p.add_argument('--'+key,required=True)
    a=p.parse_args()
    try:build(a.case,a.fan,a.output,a.audit);print('DOMAIN_AUDIT_PASSED')
    except Exception as exc:print(type(exc).__name__+': '+str(exc),file=sys.stderr);sys.exit(1)

# -*- coding: utf-8 -*-
"""检查双区CAD后按显式面标签生成米制Gmsh表面；未知面不自动归wall。"""
import argparse
import json
import sys
from pathlib import Path
from fan_case import CONFIG_REL,read_json,write_json,validate_config,digest

# 本工具只输出线性三角表面，带棱柱层的体网格由STAR生成。
ZONES=('fluid_stationary','fluid_rotating')
TARGET_API_MAJOR=4


def imported(gmsh, path, name, scale):
    """每区单独模型，稳定记录该输入的面清单，不依赖上一产品面号。"""
    gmsh.clear();gmsh.model.add(name)
    volumes=gmsh.model.occ.importShapes(str(path))
    volumes=[x for x in volumes if x[0]==3]
    if len(volumes)!=1:raise ValueError('每个流体输入需一个实体：'+name)
    gmsh.model.occ.dilate(volumes,0,0,0,scale,scale,scale);gmsh.model.occ.synchronize()
    return volumes[0][1]


def run(action, case, domain, labels, output, cad_unit):
    """inspect生成待标注清单；mesh拒绝来源/版本不符及漏标面。"""
    import gmsh
    cfg=read_json(Path(case)/CONFIG_REL);validate_config(cfg);domain=Path(domain);out=Path(output)
    if out.exists():raise FileExistsError(out)
    scale=.001 if cad_unit=='mm' else 1.
    mapping=read_json(labels) if action=='mesh' else None
    gmsh.initialize();record=dict(gmsh_version=gmsh.__version__,cad_units=cad_unit,zones={})
    try:
        gmsh.option.setNumber('General.Terminal',0)
        if action=='mesh':
            if mapping['gmsh_version']!=gmsh.__version__ or mapping['cad_units']!=cad_unit:raise ValueError('面清单的Gmsh版本或单位已变化，请重新检查')
            out.mkdir(parents=True)
        for zone in ZONES:
            path=domain/(zone+'_mm.brep' if cad_unit=='mm' else zone+'_m.brep')
            sha=digest(path);vol=imported(gmsh,path,zone,scale)
            oriented={abs(tag):int(1 if tag>0 else -1) for dim,tag in gmsh.model.getBoundary([(3,vol)],oriented=True) if dim==2}
            faces=[]
            for tag in sorted(oriented):
                faces.append(dict(tag=tag,area_m2=gmsh.model.occ.getMass(2,tag),center_m=list(gmsh.model.occ.getCenterOfMass(2,tag)),bbox_m=list(gmsh.model.getBoundingBox(2,tag))))
            row=dict(source_sha256=sha,volume_m3=gmsh.model.occ.getMass(3,vol),faces=faces,face_labels={})
            if action=='mesh':
                expected=mapping['zones'][zone]
                if expected['source_sha256']!=sha:raise ValueError('CAD来源已改变，请重新标面')
                face_labels={int(k):v for k,v in expected['face_labels'].items()}
                if set(face_labels)!=set(oriented):raise ValueError('面标签有缺失或多余：'+zone)
                if any(not isinstance(n,str) or not n.startswith(('wall_','if_')) or not n.isascii() or not n.replace('_','').isalnum() for n in face_labels.values()):raise ValueError('边界名需为ASCII语义wall_/if_')
                groups={}
                for tag,name in face_labels.items():groups.setdefault(name,[]).append(tag)
                interface='if_rotor_rot' if zone=='fluid_rotating' else 'if_rotor_stat'
                if interface not in groups:raise ValueError('缺旋转接口侧：'+interface)
                for name,tags in groups.items():gmsh.model.addPhysicalGroup(2,tags,name=name)
                gmsh.model.addPhysicalGroup(3,[vol],name=zone)
                mesh=cfg['mesh'];surfaces=[t for t,n in face_labels.items() if n.startswith(('wall_blades','wall_hub','wall_fan_fixed'))]
                if not surfaces:raise ValueError('未标注任何产品表面')
                distance=gmsh.model.mesh.field.add('Distance');gmsh.model.mesh.field.setNumbers(distance,'SurfacesList',surfaces)
                gmsh.model.mesh.field.setNumber(distance,'Sampling',150)
                threshold=gmsh.model.mesh.field.add('Threshold')
                for key,value in dict(InField=distance,SizeMin=mesh['blade_size_m'],SizeMax=mesh['base_size_m'],DistMin=.015,DistMax=.65).items():gmsh.model.mesh.field.setNumber(threshold,key,value)
                gmsh.model.mesh.field.setAsBackgroundMesh(threshold)
                for key,value in {'Mesh.MeshSizeMin':mesh['blade_min_size_m'],'Mesh.MeshSizeMax':mesh['base_size_m'],'Mesh.MeshSizeFromPoints':0,'Mesh.MeshSizeFromCurvature':0,'Mesh.MeshSizeExtendFromBoundary':0,'Mesh.Algorithm':6,'Mesh.MshFileVersion':2.2}.items():gmsh.option.setNumber(key,value)
                gmsh.model.mesh.generate(2);gmsh.write(str(out/(zone+'_m.msh')))
                tags,coords,_=gmsh.model.mesh.getNodes();nodes={int(tag):coords[3*i:3*i+3] for i,tag in enumerate(tags)}
                counts={}
                with (out/(zone+'_surfaces_m.stl')).open('x',encoding='ascii') as stream:
                    for name,tags in groups.items():
                        stream.write('solid '+name+'\n');count=0
                        for tag in tags:
                            types,_,connections=gmsh.model.mesh.getElements(2,tag)
                            for kind,conn in zip(types,connections):
                                if kind!=2:raise ValueError('只接受TRI3表面，不静默丢弃高阶单元')
                                for i in range(0,len(conn),3):
                                    tri=list(conn[i:i+3])
                                    if oriented[tag]<0:tri[1],tri[2]=tri[2],tri[1]
                                    p=[nodes[int(k)] for k in tri];u=[p[1][j]-p[0][j] for j in range(3)];v=[p[2][j]-p[0][j] for j in range(3)]
                                    normal=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]];norm=sum(x*x for x in normal)**.5
                                    if norm==0:raise ValueError('退化三角形')
                                    stream.write('facet normal %.12g %.12g %.12g\nouter loop\n'%tuple(x/norm for x in normal))
                                    for point in p:stream.write('vertex %.12g %.12g %.12g\n'%tuple(point))
                                    stream.write('endloop\nendfacet\n');count+=1
                        stream.write('endsolid '+name+'\n');counts[name]=count
                row.update(face_labels=face_labels,triangles=counts)
            record['zones'][zone]=row
        if action=='inspect':write_json(out,record)
        else:write_json(out/'surface_audit.json',dict(record,passed=True,scope='surface only; no volume/prism mesh'))
        return record
    finally:gmsh.finalize()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['inspect','mesh'])
    for key in ['case','domain','output']:p.add_argument('--'+key,required=True)
    p.add_argument('--labels');p.add_argument('--cad-unit',choices=['mm','m'],default='mm');a=p.parse_args()
    if a.action=='mesh' and not a.labels:p.error('mesh需要--labels')
    try:run(a.action,a.case,a.domain,a.labels,a.output,a.cad_unit);print('GMSH_SURFACE_STAGE_COMPLETED')
    except Exception as exc:print(type(exc).__name__+': '+str(exc),file=sys.stderr);sys.exit(1)

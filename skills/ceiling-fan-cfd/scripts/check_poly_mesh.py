# -*- coding: utf-8 -*-
"""只读核对STAR导出的CGNS多面体体积、闭合、边界和实际棱柱层。"""
import argparse
import json
import sys
from pathlib import Path
from fan_case import digest,read_json,write_json

# 批大小和匹配精度为实现参数，验收门槛由expect JSON提供。
CHUNK_FACES=120000
LAYER_MATCH_DECIMALS=8


def check(mesh, expect, output):
    """完整检查所有预期区，未知/缺失边界、层号或非正体积均停止准入。"""
    import numpy as np
    import h5py
    mesh=Path(mesh);expect=Path(expect);cfg=read_json(expect);reports={};blade=[]
    layer_dir=(expect.parent/cfg['layer_csv_directory']).resolve()
    native=read_json(expect.parent/cfg['native_quality_json'])
    prefix=cfg['blade_prefix'];requested=cfg['requested_layers'];minimum=cfg['minimum_full_layer_fraction']
    if not 0<minimum<=1:raise ValueError('层覆盖门槛不合法')
    with h5py.File(mesh,'r') as f:
        zones={name:z for name,z in f['Base'].items() if isinstance(z,h5py.Group) and z.attrs.get('label')==b'Zone_t'}
        if set(zones)!=set(cfg['zones']):raise ValueError('实际区集合与预期不符')
        for name,z in zones.items():
            expected=cfg['zones'][name]
            xyz=np.column_stack([z['GridCoordinates/Coordinate'+axis+'/ data'][...] for axis in 'XYZ'])
            if not np.all(np.isfinite(xyz)):raise ValueError('节点非有限')
            sections={n:g for n,g in z.items() if isinstance(g,h5py.Group) and g.attrs.get('label')==b'Elements_t'}
            nfaces=[g for g in sections.values() if int(g[' data'][0])==23]
            if len(nfaces)!=1:raise ValueError('需要一个NFACE段；其他CGNS拓扑请先适配')
            nf=nfaces[0];offset=nf['ElementStartOffset/ data'][...].astype(np.int64);offset-=offset[0]
            refs=nf['ElementConnectivity/ data'][...].astype(np.int64)
            ngons={n:g for n,g in sections.items() if int(g[' data'][0])==22}
            count=max(int(g['ElementRange/ data'][1]) for g in ngons.values())
            moments=np.zeros(count);areas=np.zeros(count);normal=np.zeros((count,3));covered=np.zeros(count,dtype=bool)
            boundary_names={n for n in ngons if n.startswith(('wall_','if_'))}
            if boundary_names!=set(expected['boundaries']):raise ValueError('实际边界集合不符：'+name)
            label='rot' if 'rotating' in name else 'stat'
            for patch,g in ngons.items():
                _,_,mom,area,vector,centers=polygon_geometry(g,xyz)
                begin,end=g['ElementRange/ data'][...]-[1,0]
                if np.any(covered[begin:end]):raise ValueError('面段编号重叠')
                covered[begin:end]=True;moments[begin:end]=mom;areas[begin:end]=area;normal[begin:end]=vector
                if patch.startswith(prefix):
                    csv=layer_dir/(patch+'_'+label+'_native_layers.csv')
                    if not csv.exists():raise FileNotFoundError('叶片原生层号文件缺失：'+csv.name)
                    record,values=layers(g,xyz,centers,area,csv)
                    record['source']=csv.name
                    blade.append(record)
            ids=np.abs(refs)-1
            if np.any(ids<0) or np.any(ids>=count) or not np.all(covered[ids]):raise ValueError('单元引用缺面')
            volume=np.add.reduceat(moments[ids]*np.sign(refs),offset[:-1])
            closure=np.column_stack([np.add.reduceat(normal[ids,i]*np.sign(refs),offset[:-1]) for i in range(3)])
            cell_area=np.add.reduceat(areas[ids],offset[:-1])
            if np.any(cell_area<=0):raise ValueError('单元面积非正')
            ratio=np.linalg.norm(closure,axis=1)/cell_area
            cad=float(expected['cad_volume_m3'])
            if cad<=0:raise ValueError('CAD体积必须来自已验收正体积')
            q=native[name]
            finite=bool(np.all(np.isfinite(volume)) and np.all(np.isfinite(ratio)))
            valid=bool(finite and np.all(volume>0) and ratio.max()<cfg['max_relative_closure'] and
                abs(volume.sum()-cad)/cad<cfg['max_volume_error_fraction'] and q['Volume']['min']>0 and
                q['SkewnessAngle']['max']<cfg['max_skewness_angle_deg'] and q['FaceValidity']['min']>=cfg['min_face_validity'])
            reports[name]=dict(cells=len(volume),nodes=len(xyz),nonpositive_volume_count=int(np.sum(volume<=0)),
                volume_min_m3=float(volume.min()),volume_m3=float(volume.sum()),cad_volume_m3=cad,
                volume_relative_error=float(abs(volume.sum()-cad)/cad),max_relative_closure=float(ratio.max()),
                boundaries=sorted(boundary_names),native_quality=q,passed=valid)
    if not blade:raise ValueError('未发现叶片表面，不能计算覆盖率')
    area=sum(r['area_m2'] for r in blade)
    full=sum(r['area_m2']*r['layer_histogram'].get(str(requested),{}).get('area_fraction',0) for r in blade)/area
    unmatched=sum(r['unmatched_faces'] for r in blade)
    result=dict(mesh_name=mesh.name,mesh_sha256=digest(mesh),zones=reports,cells_total=sum(r['cells'] for r in reports.values()),
        blade_full_layer_area_fraction=full,blade_area_m2=area,blade_unmatched_faces=unmatched,
        requested_layers=requested,minimum_full_layer_fraction=minimum,
        passed=bool(all(r['passed'] for r in reports.values()) and unmatched==0 and full>=minimum),
        scope='CGNS/native-layer checks only; hanger shape, y+ and mesh sensitivity require separate evidence')
    write_json(output,result)
    if not result['passed']:raise RuntimeError('网格验收未通过，详见报告')
    return result

def polygon_geometry(section,xyz):
    """按顶点次序计算多边形面积向量、体积分量及边界面中心。"""
    import numpy as np
    offsets=section['ElementStartOffset/ data'][...].astype(np.int64)
    offsets-=offsets[0]
    conn=section['ElementConnectivity/ data'][...].astype(np.int64)-1
    sizes=np.diff(offsets);n=len(sizes)
    moment=np.empty(n);area=np.empty(n);normal=np.empty((n,3));centers=np.empty((n,3))
    reference=(xyz.min(axis=0)+xyz.max(axis=0))/2
    for begin in range(0,n,CHUNK_FACES):
        end=min(begin+CHUNK_FACES,n)
        for width in np.unique(sizes[begin:end]):
            ids=np.flatnonzero(sizes[begin:end]==width)+begin
            indices=offsets[ids,None]+np.arange(width)
            points=xyz[conn[indices]]
            centers[ids]=points.mean(axis=1)
            p=points-reference
            vector=np.cross(p[:,1:-1]-p[:,0,None],p[:,2:]-p[:,0,None])*.5
            normal[ids]=vector.sum(axis=1)
            area[ids]=np.linalg.norm(vector,axis=2).sum(axis=1)
            # STAR导出的多边形面可能不完全共面。用面心与逐边三角分片定义
            # 统一的面几何，避免首顶点扇形对扭曲多边形产生起点依赖的体积。
            # 平面多边形时此式与首顶点扇形严格等价；闭合检查仍独立计算。
            moment[ids]=np.einsum('ij,ij->i',p.mean(axis=1),normal[ids])/3
    return offsets,conn,moment,area,normal,centers


def layers(section,xyz,centers,areas,csv):
    """按面积加权STAR原生层号，并检查每个边界面都能匹配原生采样。"""
    import numpy as np
    native=np.genfromtxt(csv,delimiter=',',skip_header=1)
    header=csv.read_text(encoding='utf-8-sig').splitlines()[0].strip().split(',')
    # STAR的XyzInternalTable将两个场量置于坐标之前；用表头再次确认实际列。
    layer_col=next(i for i,name in enumerate(header) if 'PrismLayerNumber' in name or 'Prism Layer Number' in name)
    height_col=next(i for i,name in enumerate(header) if 'FirstPrismLayerHeight' in name or 'First Prism Layer Height' in name)
    xcol=next(i for i,name in enumerate(header) if name.strip().strip('"').startswith('X '))
    coord=native[:,xcol:xcol+3]
    mapping={tuple(np.round(v,LAYER_MATCH_DECIMALS)):i for i,v in enumerate(coord)}
    indices=np.asarray([mapping.get(tuple(np.round(v,LAYER_MATCH_DECIMALS)),-1) for v in centers])
    matched=indices>=0
    values=np.full(len(indices),np.nan);heights=np.full(len(indices),np.nan)
    values[matched]=native[indices[matched],layer_col];heights[matched]=native[indices[matched],height_col]
    histogram={str(int(k)):{'faces':int(np.sum(values==k)),'area_fraction':float(areas[values==k].sum()/areas.sum())}
               for k in np.unique(values[np.isfinite(values)])}
    good=heights[np.isfinite(heights)&(heights>0)]
    return {'faces':len(centers),'area_m2':float(areas.sum()),'layer_histogram':histogram,
            'unmatched_faces':int(np.sum(~matched)),'unmatched_area_fraction':float(areas[~matched].sum()/areas.sum()),
            'first_layer_height_m':{'min':float(good.min()),'median':float(np.median(good)),'max':float(good.max())} if len(good) else None,
            'source':str(csv),'header':header},values


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['mesh','expect','output']:p.add_argument('--'+key,required=True)
    a=p.parse_args()
    try:
        result=check(a.mesh,a.expect,a.output)
        print(json.dumps({k:v for k,v in result.items() if k!='zones'},ensure_ascii=False))
    except Exception as exc:print(type(exc).__name__+': '+str(exc),file=sys.stderr);sys.exit(1)



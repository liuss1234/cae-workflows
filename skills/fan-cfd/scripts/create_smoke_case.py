# -*- coding: utf-8 -*-
"""生成四区结构化方块的公开合成安装检查案例，仅用于 CGNS/QFlux API 链路，不用于风机性能。"""
import argparse
import json
import math
import sys
from pathlib import Path
from fan_case import TEMPLATE, digest, read_json, require, write_json
from export_cgns import export

# 全部参数仅用于安装检查；与真实风机几何、边界层和求解工况无关。
SIDE_M = .1
TEST_RPM = 60.
DIVISIONS = 2
ZONE_NAMES = ['upstream','rotating_block','fixed_block','downstream']
HEX_FACES = [[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]


def create(output, library, size_bytes):
    """实际生成可导入 CGNS；单元层数只描述此合成单块，不验证叶片棱柱层算法。"""
    import numpy as np
    root = Path(output).resolve()
    require(not root.exists(),'拒绝覆盖已有检查目录')
    (root/'01_geometry').mkdir(parents=True); (root/'02_mesh').mkdir()
    cfg = read_json(TEMPLATE); cfg['name'] = 'synthetic_api_smoke'; cfg['profile'] = 'custom'
    cfg['geometry'].update(diameter_m=SIDE_M,axis_origin_m=[.01,.02,.03])
    cfg['boundaries'] = {}; cfg['interface_pairs'] = []; cfg['mesh']['zones'] = {}; groups = []
    cfg['rotation'].update(zone=ZONE_NAMES[1],axis_unit=[0.,1.,0.],rpm=TEST_RPM,omega_rad_s=TEST_RPM*2*math.pi/60,view_direction_unit=[0.,1.,0.],sense_from_view='clockwise')
    cfg['physics'].update(density_kg_m3=1.2,viscosity_Pa_s=1.8e-5,temperature_K=300.,reference_pressure_Pa=101325.)
    cfg['solver'].update(cores=1,max_iterations=5,save_interval=5,momentum_scheme='FirstUpwind',nonorth_corrections=2,initial_k_m2_s2=.01,initial_epsilon_m2_s3=.01)
    cfg['solver']['relaxation'].update(pressure=.2,momentum=.4,turbulence=.4)
    cfg['mesh']['bbox_tolerance_m'] = 1e-8
    cfg['mesh']['limits'].update(max_nonorth_deg=10.,max_volume_error_fraction=1e-8)
    plan = {'input_units':'m','zones':{}}
    evidence = {'producer':'create_smoke_case: exact synthetic structured blocks','quality_method':'analytic cube volume/topology/orthogonality; installation fixture only',
                'zones':{},'boundaries':{}}
    for i,name in enumerate(ZONE_NAMES):
        xyz = np.array([[a/DIVISIONS,b/DIVISIONS,i+c/DIVISIONS] for c in range(DIVISIONS+1)
                        for b in range(DIVISIONS+1) for a in range(DIVISIONS+1)],dtype=float)*SIDE_M
        def node(a,b,c):
            """规则格点的局部节点索引。"""
            return c*(DIVISIONS+1)**2+b*(DIVISIONS+1)+a
        cells = []; quads = []; patches = []
        for c in range(DIVISIONS):
            for b in range(DIVISIONS):
                for a in range(DIVISIONS):
                    cell = [node(a,b,c),node(a+1,b,c),node(a+1,b+1,c),node(a,b+1,c),
                            node(a,b,c+1),node(a+1,b,c+1),node(a+1,b+1,c+1),node(a,b+1,c+1)]
                    cells.append(cell)
                    exposed = [c == 0,c == DIVISIONS-1,b == 0,a == DIVISIONS-1,b == DIVISIONS-1,a == 0]
                    for face,outer in enumerate(exposed):
                        if outer:
                            quads.append([cell[j] for j in HEX_FACES[face]])
                            patches.append(0 if face == 0 else 1 if face == 1 else 3 if i == 1 and face == 2 else 2)
        bottom = 'open_in' if i == 0 else name+'_bottom'
        top = 'open_out' if i == len(ZONE_NAMES)-1 else name+'_top'
        names = [bottom,top,name+'_wall']
        if i == 1:
            names.append('moving_test_wall')
        for n in names:
            kind = 'pressure_inlet' if n == 'open_in' else 'pressure_outlet' if n == 'open_out' else 'interface' if n in (bottom,top) else 'wall'
            b = {'zone':name,'kind':kind}
            if kind == 'wall':
                b['frame'] = 'rotating' if n == 'moving_test_wall' else 'global'; groups.append(n)
            if kind.startswith('pressure_'):
                b['pressure_Pa'] = 0.
            cfg['boundaries'][n] = b
            face_count = patches.count(names.index(n)); entry = {'zone':name,'faces':face_count}
            if kind == 'wall':
                area = face_count*(SIDE_M/DIVISIONS)**2
                entry.update(area_m2=area,layer_count_area_m2={str(DIVISIONS):area},unmatched_area_m2=0.,actual_total_thickness_m={'min':SIDE_M,'median':SIDE_M,'max':SIDE_M})
            evidence['boundaries'][n] = entry
        data = {'xyz':xyz,'hexa':np.array(cells,dtype=np.int64),'tri':np.empty((0,3),dtype=np.int64),
                'quad':np.array(quads,dtype=np.int64),'patch':np.empty(0,dtype=np.int64),'quad_patch':np.array(patches,dtype=np.int64),
                'metadata':json.dumps({'names':names})}
        for key,width in [('tetra',4),('pyramid',5),('prism',6)]:
            data[key] = np.empty((0,width),dtype=np.int64)
        np.savez(root/'02_mesh'/(name+'.npz'),**data)
        plan['zones'][name] = {'arrays':name+'.npz','boundaries':{n:cfg['boundaries'][n]['kind'] for n in names}}
        box = xyz.min(axis=0).tolist()+xyz.max(axis=0).tolist(); cfg['mesh']['zones'][name] = {'cells':len(cells),'bbox_m':box}
        evidence['zones'][name] = {'cells':len(cells),'bbox_m':box,'cell_types':{'hexa':len(cells)},
            'quality':{'nonpositive_cells':0,'invalid_topology_cells':0,'min_volume_m3':(SIDE_M/DIVISIONS)**3,'max_nonorth_deg':0.,'volume_error_fraction':0.}}
        if i > 0:
            cfg['interface_pairs'].append([ZONE_NAMES[i-1]+'_top',bottom])
    cfg['mesh']['layer_groups'] = [{'name':'synthetic_structured_rows','boundaries':groups,'requested_layers':DIVISIONS,
        'first_height_m':SIDE_M/DIVISIONS,'total_thickness_m':SIDE_M,'growth':1.,'minimum_full_layer_area_fraction':1.}]
    write_json(root/'02_mesh/export_plan.json',plan)
    result = export(root/'02_mesh/export_plan.json',root/'02_mesh/mesh.cgns',library,size_bytes)
    cfg['mesh']['sha256'] = result['mesh_sha256']; evidence['mesh_sha256'] = result['mesh_sha256']
    geometry = root/'01_geometry/synthetic_topology.json'
    write_json(geometry,{'scope':'four exact cube arrays; no product CAD or fan blades','zones':cfg['mesh']['zones']})
    cfg['source'] = {'file':'01_geometry/synthetic_topology.json','sha256':digest(geometry)}
    write_json(root/'case.json',cfg); write_json(root/'checks/mesh_evidence.json',evidence)
    print('已生成合成安装检查网格，禁止用于产品性能结论：'+str(root))


def main():
    """所有软件路径来自命令行，不复制厂商动态库。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True); parser.add_argument('--library',required=True)
    parser.add_argument('--cgsize-bytes',type=int,choices=[4,8],required=True)
    args = parser.parse_args(); create(args.output,args.library,args.cgsize_bytes)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('合成安装检查失败：'+str(error),file=sys.stderr); sys.exit(1)

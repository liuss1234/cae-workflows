# -*- coding: utf-8 -*-
"""用显式 CGNS C 库导出任意多区线性混合网格，保留全部体单元与三角/四边形边界。"""
import argparse
import ctypes as ct
import json
import os
import sys
from pathlib import Path
from fan_case import digest, number, read_json, require, write_json

# CGNS 标准枚举与 NPZ 数据列数；不支持的类型直接拒绝，不过滤丢失。
CELL_TYPES = {'tetra':(10,4), 'pyramid':(12,5), 'prism':(14,6), 'hexa':(17,8)}
BC_TYPES = {'wall':20,'interface':1,'pressure_inlet':9,'pressure_outlet':13}
RESERVED = {'GridCoordinates','ZoneBC','volume_tetra','volume_pyramid','volume_prism','volume_hexa'}


def load_arrays(path, spec, scale):
    """预先检查全部输入：有限坐标、整型连接、命名/归属、单元数和完整类型清单。"""
    import numpy as np
    with np.load(path,allow_pickle=False) as source:
        allowed = {'xyz','tri','quad','patch','quad_patch','metadata'} | set(CELL_TYPES)
        require(set(source.files) == allowed,'NPZ 必须包含全部约定字段，空单元类型用空数组')
        arrays = {k:source[k].copy() for k in source.files if k != 'metadata'}
        names = json.loads(str(source['metadata']))['names']
    require(isinstance(names,list) and len(names) == len(set(names)) and set(names) == set(spec['boundaries']),'边界元数据与显式映射不符')
    xyz = np.asarray(arrays['xyz'],dtype=np.float64)*scale
    require(xyz.ndim == 2 and xyz.shape[1] == 3 and len(xyz) >= 4 and np.isfinite(xyz).all(),'坐标格式错误')
    arrays['xyz'] = xyz
    for key,width in list((k,v[1]) for k,v in CELL_TYPES.items())+[('tri',3),('quad',4)]:
        a = arrays[key]
        require(a.ndim == 2 and a.shape[1] == width and a.dtype.kind in 'iu','连接数组格式错误：'+key)
        require(not len(a) or (a.min() >= 0 and a.max() < len(xyz)), '连接引用越界：'+key)
        require(not len(a) or np.all(np.diff(np.sort(a,axis=1),axis=1) > 0), '单元内存在重复节点：'+key)
    require(sum(len(arrays[k]) for k in CELL_TYPES) > 0, '没有体单元')
    for key,faces in [('patch','tri'),('quad_patch','quad')]:
        a = arrays[key]
        require(a.ndim == 1 and len(a) == len(arrays[faces]) and a.dtype.kind in 'iu','面组编号格式错误')
        require(not len(a) or (a.min() >= 0 and a.max() < len(names)), '面组编号越界')
    for i,name in enumerate(names):
        require(spec['boundaries'][name] in BC_TYPES,'未知边界类型：'+name)
        require(int((arrays['patch'] == i).sum()+(arrays['quad_patch'] == i).sum()) > 0,'空边界：'+name)
    return arrays,names


def export(plan_path, output, library, size_bytes):
    """全部检查后写新文件，失败保留 staging；导出不替代拓扑/层网格验收。"""
    import numpy as np
    plan_path = Path(plan_path).resolve(); output = Path(output).resolve(); library = Path(library).resolve()
    plan = read_json(plan_path)
    require(plan['input_units'] in ('m','mm'),'必须明确 m 或 mm')
    require(bool(plan['zones']),'网格区为空')
    scale = 1. if plan['input_units'] == 'm' else .001
    all_names = list(plan['zones']) + [n for z in plan['zones'].values() for n in z['boundaries']]
    require(len(all_names) == len(set(all_names)),'区名/边界名称必须全局唯一')
    for name in all_names:
        require(isinstance(name,str) and bool(name) and len(name.encode('ascii')) <= 32 and '/' not in name and name not in RESERVED,'CGNS 名称无效')
    prepared = {}
    for name,spec in plan['zones'].items():
        path = (plan_path.parent/spec['arrays']).resolve()
        prepared[name] = (load_arrays(path,spec,scale),digest(path))
    staging = output.with_name(output.name+'.staging')
    require(not output.exists() and not staging.exists(),'拒绝覆盖已有 CGNS 或未完成 staging')
    require(library.is_file(),'CGNS C 库不存在')
    cookie = os.add_dll_directory(str(library.parent)) if hasattr(os,'add_dll_directory') else None
    lib = ct.CDLL(str(library)); I = ct.c_int; S = ct.c_int64 if size_bytes == 8 else ct.c_int32
    dtype = np.int64 if size_bytes == 8 else np.int32; PI = ct.POINTER(I); PS = ct.POINTER(S)
    lib.cg_get_error.restype = ct.c_char_p
    signatures = {'cg_set_file_type':[I], 'cg_open':[ct.c_char_p,I,PI],'cg_close':[I],
        'cg_base_write':[I,ct.c_char_p,I,I,PI],'cg_zone_write':[I,I,ct.c_char_p,PS,I,PI],
        'cg_coord_write':[I,I,I,I,ct.c_char_p,ct.c_void_p,PI],
        'cg_section_write':[I,I,I,ct.c_char_p,I,S,S,I,PS,PI],
        'cg_poly_section_write':[I,I,I,ct.c_char_p,I,S,S,I,PS,PS,PI],
        'cg_boco_write':[I,I,I,ct.c_char_p,I,I,S,PS,PI],'cg_boco_gridlocation_write':[I,I,I,I,I],
        'cg_dataclass_write':[I],'cg_units_write':[I,I,I,I,I]}
    for name,args in signatures.items():
        getattr(lib,name).argtypes = args; getattr(lib,name).restype = I
    def call(name,*args):
        """抛出原生错误；不因子进程无输出就假定写入成功。"""
        require(getattr(lib,name)(*args) == 0,name+': '+str(lib.cg_get_error()))
    output.parent.mkdir(parents=True,exist_ok=True)
    fn = I(); base = I(); call('cg_set_file_type',2); call('cg_open',str(staging).encode(),1,ct.byref(fn))
    manifest = {'units':'m','zones':{},'scope':'export counts and dimensions only; topology and layer evidence separate'}
    try:
        call('cg_base_write',fn,b'FanCFD',3,3,ct.byref(base))
        # 声明 SI 量纲，避免目标软件在无单位元数据时按默认长度重新解释坐标。
        call('cg_goto',fn,base,ct.c_char_p(b'end'))
        call('cg_dataclass_write',2); call('cg_units_write',2,2,2,2,3)
        for name,((data,names),source_hash) in prepared.items():
            xyz = data['xyz']; cells = sum(len(data[k]) for k in CELL_TYPES)
            require(max(len(xyz),cells+len(data['tri'])+len(data['quad'])) < np.iinfo(dtype).max,'CGNS 整数 ABI 容量不足')
            sizes = np.array([len(xyz),cells,0],dtype=dtype); zone = I(); section = I()
            call('cg_zone_write',fn,base,name.encode(),sizes.ctypes.data_as(PS),3,ct.byref(zone))
            for axis,label in enumerate('XYZ'):
                a = np.ascontiguousarray(xyz[:,axis],dtype=np.float64); coordinate = I()
                call('cg_coord_write',fn,base,zone,4,('Coordinate'+label).encode(),ct.c_void_p(a.ctypes.data),ct.byref(coordinate))
            offset = 0
            for key,(kind,width) in CELL_TYPES.items():
                a = np.ascontiguousarray(data[key]+1,dtype=dtype)
                if len(a):
                    call('cg_section_write',fn,base,zone,('volume_'+key).encode(),kind,offset+1,offset+len(a),0,a.ctypes.data_as(PS),ct.byref(section))
                    offset += len(a)
            patches = {}
            for i,patch in enumerate(names):
                tri = data['tri'][data['patch'] == i]+1; quad = data['quad'][data['quad_patch'] == i]+1
                length = len(tri)+len(quad)
                if len(tri) and len(quad):
                    a = np.concatenate([np.column_stack([np.full(len(tri),5),tri]).ravel(),np.column_stack([np.full(len(quad),7),quad]).ravel()]).astype(dtype)
                    offsets = np.r_[np.arange(len(tri)+1)*4,len(tri)*4+np.arange(1,len(quad)+1)*5].astype(dtype)
                    call('cg_poly_section_write',fn,base,zone,patch.encode(),20,offset+1,offset+length,0,a.ctypes.data_as(PS),offsets.ctypes.data_as(PS),ct.byref(section))
                else:
                    a = np.ascontiguousarray(tri if len(tri) else quad,dtype=dtype)
                    call('cg_section_write',fn,base,zone,patch.encode(),5 if len(tri) else 7,offset+1,offset+length,0,a.ctypes.data_as(PS),ct.byref(section))
                span = np.array([offset+1,offset+length],dtype=dtype); boundary = I()
                call('cg_boco_write',fn,base,zone,patch.encode(),BC_TYPES[plan['zones'][name]['boundaries'][patch]],4,2,span.ctypes.data_as(PS),ct.byref(boundary))
                call('cg_boco_gridlocation_write',fn,base,zone,boundary,4)
                patches[patch] = {'faces':length,'triangles':len(tri),'quadrilaterals':len(quad)}; offset += length
            manifest['zones'][name] = {'cells':cells,'nodes':len(xyz),'cell_types':{k:len(data[k]) for k in CELL_TYPES},
                'bbox_m':xyz.min(axis=0).tolist()+xyz.max(axis=0).tolist(),'boundaries':patches,'source_arrays_sha256':source_hash}
    finally:
        call('cg_close',fn)
        if cookie is not None:
            cookie.close()
    os.replace(str(staging),str(output)); manifest['mesh_sha256'] = digest(output)
    write_json(output.with_name(output.name+'.manifest.json'),manifest)
    return manifest


def main():
    """numpy 只在执行导出时导入；帮助入口不依赖商业运行时。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',required=True); parser.add_argument('--output',required=True)
    parser.add_argument('--library',required=True); parser.add_argument('--cgsize-bytes',type=int,choices=[4,8],required=True)
    args = parser.parse_args(); result = export(args.plan,args.output,args.library,args.cgsize_bytes)
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('CGNS 导出失败：'+str(error),file=sys.stderr); sys.exit(1)

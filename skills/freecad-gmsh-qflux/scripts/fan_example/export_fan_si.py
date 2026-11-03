# -*- coding: utf-8 -*-
"""输出以 m 为单位、明确分区和边界的 CFD 网格：多区 CGNS 与 Gmsh ASCII。"""
# 本文件为七叶风扇参考实现；其他 CAD 必须重新映射零件与边界，不能直接套用。


# 可调参数统一列于此处；每次写入新目录，保留已生成的毫米版文件。
from pathlib import Path
import os
WORK_DIRECTORY = Path(os.environ["CFD_WORK_DIRECTORY"]).resolve()  # 由运行器指定独立项目目录
GMSH_API_DIRECTORY = Path(os.environ["CFD_GMSH_API"])
EXCHANGE_DIRECTORY = Path(os.environ["CFD_EXCHANGE_API"])
QFLUX_DIRECTORY = Path(os.environ["CFD_QFLUX_DIRECTORY"])
LENGTH_SCALE = 0.001
REGION_NAMES = {
    "fluid_stationary_inlet": "fluid_inlet",
    "fluid_rotating": "fluid_rotating",
    "fluid_stationary_outlet": "fluid_outlet",
}
BOUNDARY_NAMES = {
    "inlet": "inlet", "outlet": "outlet",
    "wall_rotor_rotating": "wall_rotor",
    "wall_stator_rotating": "wall_stator_rotating",
    "wall_stator_stationary_outlet": "wall_stator",
    "wall_duct_stationary_inlet": "wall_duct_upstream",
    "wall_duct_rotating": "wall_duct_rotating",
    "wall_duct_stationary_outlet": "wall_duct_downstream",
    "interface_inlet": "interface_inlet",
    "interface_outlet": "interface_outlet",
}

import datetime
import ctypes as ct
import json
import os
import sys
import traceback
sys.path.insert(0, str(GMSH_API_DIRECTORY))
sys.path.insert(0, str(EXCHANGE_DIRECTORY))
import gmsh
import h5py
import numpy as np


def row_keys(values):
    """为节点连接关系建立不依赖面方向的紧凑排序键。"""
    values = np.ascontiguousarray(values, dtype=np.uint32)
    return values.view(np.dtype([("a",np.uint32),("b",np.uint32),("c",np.uint32)])).ravel()


def outward_boundary(tets):
    """从正体积四面体提取每个区的外向三角面，包含区间接口。"""
    faces = tets[:, [[1,2,3],[0,3,2],[0,1,3],[0,2,1]]].reshape(-1,3)
    keys = row_keys(np.sort(faces,axis=1))
    unique, first, counts = np.unique(keys,return_index=True,return_counts=True)
    if np.any(counts > 2):
        raise RuntimeError("体区包含非流形面")
    selected = counts == 1
    return unique[selected], faces[first[selected]].copy()


def source_data(manifest):
    """从已验证源网格提取体单元与边界，维持节点和四面体连接。"""
    tags, xyz, _ = gmsh.model.mesh.getNodes(returnParametricCoord=False)
    coords = np.empty((int(tags.max())+1,3),dtype=float)
    coords[tags] = xyz.reshape(-1,3) * LENGTH_SCALE
    patches = {}
    for old_name, tag in manifest["physical_surfaces"].items():
        arrays = []
        for entity in gmsh.model.getEntitiesForPhysicalGroup(2,tag):
            types, _, connections = gmsh.model.mesh.getElements(2,int(entity))
            if list(types) != [2]:
                raise RuntimeError(f"非一阶三角形边界：{old_name}")
            arrays.append(connections[0].reshape(-1,3).astype(np.uint32))
        patches[old_name] = np.concatenate(arrays)
    zones = {}
    for old_region, entity in manifest["regions"].items():
        types, _, connections = gmsh.model.mesh.getElements(3,entity)
        if list(types) != [4]:
            raise RuntimeError(f"非一阶四面体区：{old_region}")
        tets = connections[0].reshape(-1,4).astype(np.uint32)
        global_nodes = np.unique(tets)
        local = np.zeros(len(coords), dtype=np.int64)
        local[global_nodes] = np.arange(1,len(global_nodes)+1)
        boundary_keys, boundary_faces = outward_boundary(tets)
        zone_patches = {}
        for old_name, triangles in patches.items():
            adjacent = next(m["adjacent_regions"] for m in manifest["surface_matching"] if m["patch"] == old_name)
            if old_region not in adjacent:
                continue
            target = BOUNDARY_NAMES[old_name]
            if old_name.startswith("interface_"):
                target += "_rotating" if old_region == "fluid_rotating" else "_stationary"
            index = np.searchsorted(boundary_keys,row_keys(np.sort(triangles,axis=1)))
            if np.any(index >= len(boundary_keys)) or not np.array_equal(boundary_keys[index],row_keys(np.sort(triangles,axis=1))):
                raise RuntimeError(f"面 {target} 不在区域 {old_region} 的边界")
            zone_patches[target] = {
                "local_faces":local[boundary_faces[index]],
                "global_faces":boundary_faces[index], "source_patch":old_name,
            }
        if sum(len(p["local_faces"]) for p in zone_patches.values()) != len(boundary_keys):
            raise RuntimeError(f"区域 {old_region} 有未命名边界面")
        zones[REGION_NAMES[old_region]] = {
            "global_nodes":global_nodes, "local_map":local, "coords":coords[global_nodes],
            "tets":local[tets], "global_tets":tets, "patches":zone_patches,
        }
    return zones, tags, coords


def write_cgns(path, zones):
    """使用 QFlux 自带 CGNS 库写入，确保文件结构与目标软件一致。"""
    cookie = os.add_dll_directory(str(QFLUX_DIRECTORY))
    lib = ct.CDLL(str(QFLUX_DIRECTORY/"qxcgns64.dll"))
    lib.cg_get_error.restype = ct.c_char_p
    integer = ct.c_int
    cgsize = ct.c_longlong
    p_int = ct.POINTER(integer)
    p_size = ct.POINTER(cgsize)
    signatures = {
        "cg_open":[ct.c_char_p,integer,p_int], "cg_close":[integer],
        "cg_base_write":[integer,ct.c_char_p,integer,integer,p_int],
        "cg_zone_write":[integer,integer,ct.c_char_p,p_size,integer,p_int],
        "cg_coord_write":[integer,integer,integer,integer,ct.c_char_p,ct.c_void_p,p_int],
        "cg_section_write":[integer,integer,integer,ct.c_char_p,integer,cgsize,cgsize,integer,p_size,p_int],
        "cg_boco_write":[integer,integer,integer,ct.c_char_p,integer,integer,cgsize,p_size,p_int],
        "cg_boco_gridlocation_write":[integer,integer,integer,integer,integer],
        "cg_conn_write":[integer,integer,integer,ct.c_char_p,integer,integer,integer,cgsize,p_size,
                         ct.c_char_p,integer,integer,integer,cgsize,p_size,p_int],
    }
    for name,args in signatures.items():
        getattr(lib,name).argtypes = args

    def call(function,*args):
        """将原生 CGNS 错误转为可定位的 Python 异常。"""
        status = getattr(lib,function)(*args)
        if status:
            raise RuntimeError(function+": "+lib.cg_get_error().decode("utf-8",errors="replace"))

    fn,base = integer(),integer()
    # 2 为 HDF5 文件格式；这不是模型长度单位。
    call("cg_set_file_type",2)
    call("cg_open",str(path).encode("utf-8"),1,ct.byref(fn))
    try:
        call("cg_base_write",fn,b"FanCFD",3,3,ct.byref(base))
        call("cg_goto",fn,base,ct.c_char_p(b"end"))
        call("cg_dataclass_write",2)
        call("cg_units_write",2,2,2,2,3)
        zone_indices = {}
        # 先建立所有区域，再写跨区域连接，避免指向尚不存在的 donor。
        for name,data in zones.items():
            index = integer()
            sizes = np.array([len(data["coords"]),len(data["tets"]),0],dtype=np.int64)
            call("cg_zone_write",fn,base,name.encode(),sizes.ctypes.data_as(p_size),3,ct.byref(index))
            zone_indices[name] = index.value
        for name,data in zones.items():
            zone = zone_indices[name]
            for axis,label in enumerate(("CoordinateX","CoordinateY","CoordinateZ")):
                index = integer()
                values = np.ascontiguousarray(data["coords"][:,axis],dtype=np.float64)
                call("cg_coord_write",fn,base,zone,4,label.encode(),ct.c_void_p(values.ctypes.data),ct.byref(index))
            section = integer()
            tets = np.ascontiguousarray(data["tets"],dtype=np.int64)
            call("cg_section_write",fn,base,zone,b"fluid_cells",10,1,len(tets),0,tets.ctypes.data_as(p_size),ct.byref(section))
            offset = len(tets)
            for patch_name,patch in data["patches"].items():
                faces = np.ascontiguousarray(patch["local_faces"],dtype=np.int64)
                call("cg_section_write",fn,base,zone,patch_name.encode(),5,offset+1,offset+len(faces),0,
                     faces.ctypes.data_as(p_size),ct.byref(section))
                face_range = np.array([offset+1,offset+len(faces)],dtype=np.int64)
                bc = integer()
                bc_type = 9 if patch_name == "inlet" else 13 if patch_name == "outlet" else 20 if patch_name.startswith("wall_") else 1
                call("cg_boco_write",fn,base,zone,patch_name.encode(),bc_type,4,2,face_range.ctypes.data_as(p_size),ct.byref(bc))
                call("cg_boco_gridlocation_write",fn,base,zone,bc,4)
                offset += len(faces)
            for interface,other in (("interface_inlet","fluid_inlet"),("interface_outlet","fluid_outlet")):
                if name == "fluid_rotating":
                    target,suffix = other,"_rotating"
                elif name == other:
                    target,suffix = "fluid_rotating","_stationary"
                else:
                    continue
                nodes = np.unique(data["patches"][interface+suffix]["global_faces"])
                own = np.ascontiguousarray(data["local_map"][nodes],dtype=np.int64)
                donor = np.ascontiguousarray(zones[target]["local_map"][nodes],dtype=np.int64)
                index = integer()
                call("cg_conn_write",fn,base,zone,(interface+suffix).encode(),2,4,2,len(own),own.ctypes.data_as(p_size),
                     target.encode(),3,3,6,len(donor),donor.ctypes.data_as(p_size),ct.byref(index))
    finally:
        call("cg_close",fn)
        cookie.close()


def validate_cgns(path,zones):
    """回读每个区的坐标、连接和外向面，验证两侧接口几何一致。"""
    results = {}
    with h5py.File(path,"r") as mesh:
        for name,source in zones.items():
            zone = mesh["FanCFD"][name]
            coords = np.column_stack([zone["GridCoordinates"][label][" data"][...] for label in ("CoordinateX","CoordinateY","CoordinateZ")])
            tets = zone["fluid_cells"]["ElementConnectivity"][" data"][...].reshape(-1,4)
            if not np.array_equal(coords,source["coords"]) or not np.array_equal(tets,source["tets"]):
                raise RuntimeError(f"CGNS 回读改变了 {name} 的坐标或体单元")
            volume = 0.0
            min_volume = float("inf")
            for start in range(0,len(tets),100000):
                p = coords[tets[start:start+100000]-1]
                v = np.einsum("ij,ij->i",np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),p[:,3]-p[:,0])/6
                volume += float(v.sum()); min_volume = min(min_volume,float(v.min()))
            if min_volume <= 0:
                raise RuntimeError(f"CGNS 区域 {name} 存在非正体积")
            boundaries = {}
            for patch, info in source["patches"].items():
                actual = zone[patch]["ElementConnectivity"][" data"][...].reshape(-1,3)
                if not np.array_equal(actual,info["local_faces"]):
                    raise RuntimeError(f"CGNS 边界连接回读错误：{patch}")
                boundaries[patch] = len(actual)
            results[name] = {"nodes":len(coords),"cells":len(tets),"volume_m3":volume,
                             "minimum_cell_volume_m3":min_volume,"bbox_m":[coords.min(axis=0).tolist(),coords.max(axis=0).tolist()],"boundaries":boundaries}
    return results


def main():
    """保存米制交付包，原有毫米模型和网格维持原样。"""
    source = Path(json.loads((WORK_DIRECTORY/"latest_mesh.json").read_text(encoding="utf-8"))["output_directory"])
    manifest = json.loads((source/"mesh_manifest.json").read_text(encoding="utf-8"))
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    directory = WORK_DIRECTORY/("qflux_si_"+stamp)
    directory.mkdir(exist_ok=False)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal",0)
        gmsh.open(str(source/"fan_cfd_mm.msh"))
        zones,tags,coords = source_data(manifest)
        cgns = directory/"fan_cfd_m.cgns"
        write_cgns(cgns,zones)
        checks = validate_cgns(cgns,zones)
        # 同时提供标准 Gmsh 兼容版，但 QFlux 优先使用显式多区 CGNS。
        matrix = [LENGTH_SCALE,0,0,0, 0,LENGTH_SCALE,0,0, 0,0,LENGTH_SCALE,0, 0,0,0,1]
        gmsh.model.mesh.affineTransform(matrix)
        for old_name,tag in manifest["physical_surfaces"].items():
            gmsh.model.removePhysicalName(old_name)
            gmsh.model.setPhysicalName(2,tag,BOUNDARY_NAMES[old_name])
        for old_name,tag in manifest["physical_volumes"].items():
            gmsh.model.removePhysicalName(old_name)
            gmsh.model.setPhysicalName(3,tag,REGION_NAMES[old_name])
        gmsh.option.setNumber("Mesh.MshFileVersion",2.2)
        gmsh.option.setNumber("Mesh.Binary",0)
        gmsh.option.setNumber("Mesh.SaveAll",0)
        gmsh.write(str(directory/"fan_cfd_m_gmsh22.msh"))
        # CGNS 再经独立 CAD/网格库加载，检查标准文件结构可解析。
        gmsh.clear()
        gmsh.open(str(cgns))
        _,element_tags,_ = gmsh.model.mesh.getElements(3)
        reimport_count = sum(len(x) for x in element_tags)
        if reimport_count != sum(len(z["tets"]) for z in zones.values()):
            raise RuntimeError("Gmsh 回读 CGNS 时体单元数变化")
        report = {"units":"m","scale_from_mm":LENGTH_SCALE,"source_directory":str(source),
                  "cgns_file":str(cgns),"gmsh_file":str(directory/"fan_cfd_m_gmsh22.msh"),
                  "regions":checks,"zone_count":len(checks),"boundary_side_count":sum(len(z["boundaries"]) for z in checks.values()),
                  "global_unique_nodes":len(tags),"tetrahedra":reimport_count,
                  "region_name_map":REGION_NAMES,"boundary_name_map":BOUNDARY_NAMES,
                  "rotation":{"axis":[0,0,1],"origin_m":[0,0,0],"rpm":None},
                  "stationary_walls_inside_rotating_zone":["wall_duct_rotating","wall_stator_rotating"]}
        (directory/"si_export_check.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        (WORK_DIRECTORY/"latest_qflux_si.json").write_text(json.dumps({"output_directory":str(directory)},indent=2),encoding="utf-8")
        print(json.dumps({"output_directory":str(directory),"zones":report["zone_count"],"boundary_sides":report["boundary_side_count"],"tetrahedra":reimport_count,"units":"m"},ensure_ascii=False),flush=True)
    finally:
        gmsh.finalize()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)

# -*- coding: utf-8 -*-
"""用目标软件同版本 CGNS 库写一阶六面体/四边形多区网格，并独立回读。"""
from pathlib import Path
from runtime_config import qflux_home
QFLUX_DIRECTORY=qflux_home()
CGNS_HEXA_8=17
CGNS_QUAD_4=7

import os
import ctypes as ct
import numpy as np
import h5py

def write_cgns(path,zones):
    """zones 含局部米制坐标、从 1 编号的 hex 单元和外向 quad 边界。"""
    cookie=os.add_dll_directory(str(QFLUX_DIRECTORY))
    lib=ct.CDLL(str(QFLUX_DIRECTORY/"qxcgns64.dll"))
    lib.cg_get_error.restype=ct.c_char_p
    integer=ct.c_int
    cgsize=ct.c_longlong
    pi,ps=ct.POINTER(integer),ct.POINTER(cgsize)
    signatures={
        "cg_open":[ct.c_char_p,integer,pi],"cg_close":[integer],
        "cg_base_write":[integer,ct.c_char_p,integer,integer,pi],
        "cg_zone_write":[integer,integer,ct.c_char_p,ps,integer,pi],
        "cg_coord_write":[integer,integer,integer,integer,ct.c_char_p,ct.c_void_p,pi],
        "cg_section_write":[integer,integer,integer,ct.c_char_p,integer,cgsize,cgsize,integer,ps,pi],
        "cg_boco_write":[integer,integer,integer,ct.c_char_p,integer,integer,cgsize,ps,pi],
        "cg_boco_gridlocation_write":[integer,integer,integer,integer,integer],
    }
    for name,args in signatures.items():
        getattr(lib,name).argtypes=args
    def call(name,*args):
        status=getattr(lib,name)(*args)
        if status:
            raise RuntimeError(name+": "+lib.cg_get_error().decode("utf-8",errors="replace"))
    fn,base=integer(),integer()
    call("cg_set_file_type",2)
    call("cg_open",str(path).encode("utf-8"),1,ct.byref(fn))
    try:
        call("cg_base_write",fn,b"LiquidCooling",3,3,ct.byref(base))
        call("cg_goto",fn,base,ct.c_char_p(b"end"))
        call("cg_dataclass_write",2)
        call("cg_units_write",2,2,2,2,3)
        for name,data in zones.items():
            z=integer()
            size=np.array([len(data["coords"]),len(data["cells"]),0],dtype=np.int64)
            call("cg_zone_write",fn,base,name.encode(),size.ctypes.data_as(ps),3,ct.byref(z))
            for axis,label in enumerate(["CoordinateX","CoordinateY","CoordinateZ"]):
                value=np.ascontiguousarray(data["coords"][:,axis],dtype=np.float64)
                ix=integer()
                call("cg_coord_write",fn,base,z,4,label.encode(),ct.c_void_p(value.ctypes.data),ct.byref(ix))
            cells=np.ascontiguousarray(data["cells"],dtype=np.int64)
            section=integer()
            call("cg_section_write",fn,base,z,b"volume_cells",CGNS_HEXA_8,1,len(cells),0,cells.ctypes.data_as(ps),ct.byref(section))
            offset=len(cells)
            for label,faces in data["patches"].items():
                faces=np.ascontiguousarray(faces,dtype=np.int64)
                call("cg_section_write",fn,base,z,label.encode(),CGNS_QUAD_4,offset+1,offset+len(faces),0,faces.ctypes.data_as(ps),ct.byref(section))
                bc=integer()
                rg=np.array([offset+1,offset+len(faces)],dtype=np.int64)
                kind=9 if label=="inlet" else 13 if label=="outlet" else 20
                call("cg_boco_write",fn,base,z,label.encode(),kind,4,2,rg.ctypes.data_as(ps),ct.byref(bc))
                call("cg_boco_gridlocation_write",fn,base,z,bc,4)
                offset+=len(faces)
    finally:
        call("cg_close",fn)
        cookie.close()
    # HDF5 只负责独立数据比对；文件标准由原生 CGNS writer 保证。
    with h5py.File(path,"r") as handle:
        for name,data in zones.items():
            z=handle["LiquidCooling"][name]
            xyz=np.column_stack([z["GridCoordinates"][label][" data"][...] for label in ["CoordinateX","CoordinateY","CoordinateZ"]])
            conn=z["volume_cells"]["ElementConnectivity"][" data"][...].reshape(-1,8)
            if not np.array_equal(xyz,data["coords"]) or not np.array_equal(conn,data["cells"]):
                raise RuntimeError("CGNS 回读坐标或单元连接不一致："+name)
            for label,faces in data["patches"].items():
                actual=z[label]["ElementConnectivity"][" data"][...].reshape(-1,4)
                if not np.array_equal(actual,faces):
                    raise RuntimeError("CGNS 回读边界不一致："+label)

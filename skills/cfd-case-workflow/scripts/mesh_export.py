# -*- coding: utf-8 -*-
"""按显式清单把任意数量 TET4/TRI3 区写成米制多区 CGNS，检查质量和边界覆盖。"""
from pathlib import Path
import argparse
import ctypes as ct
import os
import re
import sys
import traceback
from cfd_common import context, add_build_paths, inside, read_json, write_json, sha256

# CGNS 标准枚举；网格尺寸、阈值、输入单位、库 ABI 在 JSON 中配置。
BC_TYPES = {"velocity_inlet": 9, "pressure_inlet": 9, "pressure_outlet": 13,
            "wall": 20, "symmetry": 16, "interface": 1}
FACE_PATTERN = [[1, 2, 3], [0, 3, 2], [0, 1, 3], [0, 2, 1]]
RESERVED_NAMES = {"volume_cells", "GridCoordinates", "ZoneBC", "ZoneGridConnectivity"}


def face_keys(rows):
    """把三角形转为无方向、可排序索引，避免依赖导入顺序。"""
    import numpy as np
    return np.ascontiguousarray(np.sort(rows, axis=1), dtype=np.int64).view(
        np.dtype([("a", "i8"), ("b", "i8"), ("c", "i8")])).ravel()


def validate_manifest(manifest):
    """检查区域/边界唯一性；接口两侧必须显式且只出现一次。"""
    if manifest.get("units") != "m" or not manifest.get("zones"):
        raise ValueError("regions.json 需 units=m 和非空 zones")
    names, boundaries = set(), {}
    for zone in manifest["zones"]:
        for name in [zone["name"]] + [b["name"] for b in zone["boundaries"]]:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) or len(name.encode()) > 32 or name in RESERVED_NAMES or name in names:
                raise ValueError("名称重复、保留或不符合 CGNS 32 字节限制：" + name)
            names.add(name)
        if zone.get("kind") not in ["fluid", "solid"] or not zone.get("region"):
            raise ValueError("每区必须定义 kind 和 region")
        for patch in zone["boundaries"]:
            if patch["role"] not in BC_TYPES:
                raise ValueError("不支持的边界角色：" + patch["role"])
            boundaries[patch["name"]] = (zone["name"], patch)
    paired = []
    for pair in manifest.get("interfaces", []):
        if pair.get("kind") != "conformal" or pair["a"] == pair["b"]:
            raise ValueError("此交换器只支持双侧共形接口")
        for name in [pair["a"], pair["b"]]:
            if name not in boundaries or boundaries[name][1]["role"] != "interface":
                raise ValueError("接口侧不存在或角色错误：" + name)
            paired.append(name)
        if boundaries[pair["a"]][0] == boundaries[pair["b"]][0]:
            raise ValueError("接口两侧应属于不同网格区")
    expected = {name for name, (_, patch) in boundaries.items() if patch["role"] == "interface"}
    if set(paired) != expected or len(paired) != len(expected):
        raise ValueError("接口有漏配或重复配对")
    return boundaries


def extract_zones(gmsh, cfg, manifest):
    """检查体积、外表面覆盖、接口和基础四面体质量，真实进行单位缩放。"""
    import numpy as np
    units = cfg["mesh"]["input_units"]
    if units not in ["m", "mm"]:
        raise ValueError("仅接受显式输入单位 m 或 mm")
    scale = 1.0 if units == "m" else 0.001
    physical = {(dim, gmsh.model.getPhysicalName(dim, tag)): list(gmsh.model.getEntitiesForPhysicalGroup(dim, tag))
                for dim, tag in gmsh.model.getPhysicalGroups()}
    if len(physical) != len(gmsh.model.getPhysicalGroups()):
        raise ValueError("Physical Group 名称重复，无法唯一匹配")
    expected_groups = {(3, z["physical_volume"]) for z in manifest["zones"]} | {
        (2, b["physical_surface"]) for z in manifest["zones"] for b in z["boundaries"]}
    if set(physical) != expected_groups:
        raise ValueError("实际 Physical Groups 与区域清单不一致：" + repr(set(physical) ^ expected_groups))
    node_tags, xyz, _ = gmsh.model.mesh.getNodes(returnParametricCoord=False)
    order = np.argsort(node_tags)
    node_tags, xyz = node_tags[order], xyz.reshape(-1, 3)[order] * scale

    def elements(dim, entities, required_type, nodes_per_element):
        """不支持的单元立即报错；不能过滤后留下不完整体网格。"""
        arrays, ids = [], []
        for entity in entities:
            kinds, element_tags, connect = gmsh.model.mesh.getElements(dim, entity)
            if list(kinds) != [required_type]:
                raise ValueError("只支持 TET4/TRI3，实际类型：" + repr(list(kinds)))
            arrays.append(np.asarray(connect[0]).reshape(-1, nodes_per_element))
            ids.extend(element_tags[0])
        raw = np.concatenate(arrays)
        index = np.searchsorted(node_tags, raw)
        if np.any(index >= len(node_tags)) or not np.array_equal(node_tags[index], raw):
            raise ValueError("单元引用不存在节点")
        return index.astype(np.int64), ids

    zones, checks, owned = {}, {}, []
    for spec in manifest["zones"]:
        name = spec["name"]
        entities = physical[(3, spec["physical_volume"])]
        owned.extend(entities)
        cells, _ = elements(3, entities, 4, 4)
        points = xyz[cells]
        determinant = np.linalg.det(points[:, 1:] - points[:, :1])
        negative = determinant < 0
        cells[negative, 1:3] = cells[negative, 2:0:-1]
        points = xyz[cells]
        volume = np.linalg.det(points[:, 1:] - points[:, :1]) / 6.0
        if not np.all(np.isfinite(volume)) or np.min(volume) <= 0:
            raise ValueError("非正或非有限体积：" + name)
        all_faces = cells[:, FACE_PATTERN].reshape(-1, 3)
        unique, first, counts = np.unique(face_keys(all_faces), return_index=True, return_counts=True)
        if np.max(counts) > 2:
            raise ValueError("存在非流形面：" + name)
        outer = all_faces[first[counts == 1]]
        outer_keys = unique[counts == 1]
        patches = {}
        for patch in spec["boundaries"]:
            faces, _ = elements(2, physical[(2, patch["physical_surface"])], 2, 3)
            keys = face_keys(faces)
            indices = np.searchsorted(outer_keys, keys)
            if np.any(indices >= len(outer_keys)) or not np.array_equal(outer_keys[indices], keys):
                raise ValueError("边界不在所属区外表面：" + patch["name"])
            patches[patch["name"]] = {"global_faces": outer[indices], "role": patch["role"]}
        coverage = np.concatenate([face_keys(p["global_faces"]) for p in patches.values()])
        if len(coverage) != len(outer_keys) or len(np.unique(coverage)) != len(outer_keys):
            raise ValueError("存在漏标或重复边界：" + name)
        global_nodes = np.unique(cells)
        coords = xyz[global_nodes]
        local_map = np.full(len(xyz), -1, dtype=np.int64)
        local_map[global_nodes] = np.arange(1, len(global_nodes) + 1)
        for patch in patches.values():
            patch["local_faces"] = local_map[patch["global_faces"]]
        zones[name] = {"coords": coords, "cells": local_map[cells], "local_map": local_map, "patches": patches}
        bbox = [coords.min(axis=0).tolist(), coords.max(axis=0).tolist()]
        tolerance = cfg["validation"]["bbox_tolerance_m"]
        if "bbox_m" in spec and not np.allclose(bbox, spec["bbox_m"], rtol=0, atol=tolerance):
            raise ValueError("米制包围盒不符：" + name)
        edge_pairs = points[:, [[1, 0], [2, 0], [3, 0], [2, 1], [3, 1], [3, 2]]]
        lengths = np.linalg.norm(edge_pairs[:, :, 0] - edge_pairs[:, :, 1], axis=2)
        faces = points[:, FACE_PATTERN]
        areas = np.linalg.norm(np.cross(faces[:, :, 1] - faces[:, :, 0], faces[:, :, 2] - faces[:, :, 0]), axis=2) / 2
        aspect = np.sqrt(2.0 / 3) * lengths.max(axis=1) * areas.max(axis=1) / (3 * volume)
        delta = points[:, 1:] - points[:, :1]
        center = np.linalg.solve(2 * delta, np.sum(delta * delta, axis=2)[..., None])[..., 0]
        radius = np.linalg.norm(center, axis=1)
        skew = 1 - volume / (8 * radius ** 3 / (9 * np.sqrt(3)))
        if not np.all(np.isfinite(skew)) or not np.all(np.isfinite(aspect)):
            raise ValueError("非有限网格质量指标")
        check = {"nodes": len(coords), "cells": len(cells), "bbox_m": bbox, "volume_m3": float(volume.sum()),
                 "minimum_cell_volume_m3": float(volume.min()), "boundaries": {k: len(v["local_faces"]) for k, v in patches.items()},
                 "skewness_max": float(skew.max()), "skewness_p99": float(np.percentile(skew, 99)),
                 "aspect_ratio_max": float(aspect.max()), "aspect_ratio_p99": float(np.percentile(aspect, 99)),
                 "outward_boundary_coverage_complete": True}
        if "cad_volume_m3" in spec:
            check["cad_volume_error_percent"] = 100 * (float(volume.sum()) / spec["cad_volume_m3"] - 1)
        for metric in ["skewness_max", "aspect_ratio_max"]:
            limit = cfg["validation"].get(metric + "_limit")
            if limit is not None and check[metric] > limit:
                raise ValueError("网格质量超过配置阈值：%s %s=%g > %g" % (name, metric, check[metric], limit))
        checks[name] = check
    if sorted(owned) != sorted(tag for _, tag in gmsh.model.getEntities(3)):
        raise ValueError("有体区域未归属或重复归属")
    for pair in manifest.get("interfaces", []):
        sides = [(name, patch) for name, zone in zones.items() for patch in zone["patches"] if patch in [pair["a"], pair["b"]]]
        a, b = [zones[z]["patches"][p]["global_faces"] for z, p in sides]
        if not np.array_equal(np.sort(face_keys(a)), np.sort(face_keys(b))):
            raise ValueError("接口不是共享节点的共形面：" + pair["a"])
        na = np.cross(xyz[a[:, 1]] - xyz[a[:, 0]], xyz[a[:, 2]] - xyz[a[:, 0]]).sum(axis=0)
        nb = np.cross(xyz[b[:, 1]] - xyz[b[:, 0]], xyz[b[:, 2]] - xyz[b[:, 0]]).sum(axis=0)
        if np.linalg.norm(na + nb) > max(np.linalg.norm(na), 1e-30) * 1e-8:
            raise ValueError("接口两侧法向不相反")
    return zones, checks


def write_cgns(path, zones, manifest, env):
    """调用标准 CGNS C API；索引位宽必须与目标库一致，不重分发该库。"""
    import numpy as np
    home = env.get("qflux_home", "")
    library = env.get("cgns_library") or (str(Path(home) / "qxcgns64.dll") if home and os.name == "nt" else "")
    if not library or not Path(library).is_file() or env.get("cgns_index_bits") not in [32, 64]:
        raise ValueError("需配置 CGNS 库文件和正确 cgns_index_bits")
    cookie = os.add_dll_directory(str(Path(library).parent)) if os.name == "nt" else None
    lib = ct.CDLL(library)
    lib.cg_get_error.restype = ct.c_char_p
    integer = ct.c_int
    size = ct.c_longlong if env["cgns_index_bits"] == 64 else ct.c_int
    dtype = np.int64 if env["cgns_index_bits"] == 64 else np.int32
    pi, ps = ct.POINTER(integer), ct.POINTER(size)
    signatures = {"cg_open": [ct.c_char_p, integer, pi], "cg_close": [integer],
                  "cg_base_write": [integer, ct.c_char_p, integer, integer, pi],
                  "cg_zone_write": [integer, integer, ct.c_char_p, ps, integer, pi],
                  "cg_coord_write": [integer, integer, integer, integer, ct.c_char_p, ct.c_void_p, pi],
                  "cg_section_write": [integer, integer, integer, ct.c_char_p, integer, size, size, integer, ps, pi],
                  "cg_boco_write": [integer, integer, integer, ct.c_char_p, integer, integer, size, ps, pi],
                  "cg_boco_gridlocation_write": [integer, integer, integer, integer, integer],
                  "cg_conn_write": [integer, integer, integer, ct.c_char_p, integer, integer, integer, size, ps,
                                    ct.c_char_p, integer, integer, integer, size, ps, pi]}
    for name, signature in signatures.items():
        getattr(lib, name).argtypes = signature

    def call(name, *args):
        """保留原生错误信息，不能将写入失败当成有效交换文件。"""
        if getattr(lib, name)(*args):
            raise RuntimeError(name + ": " + lib.cg_get_error().decode("utf-8", errors="replace"))

    fn, base = integer(), integer()
    call("cg_set_file_type", 2)
    call("cg_open", str(path).encode("utf-8"), 1, ct.byref(fn))
    try:
        call("cg_base_write", fn, b"CFD", 3, 3, ct.byref(base))
        call("cg_goto", fn, base, ct.c_char_p(b"end"))
        call("cg_dataclass_write", 2)
        call("cg_units_write", 2, 2, 2, 2, 3)
        indices = {}
        for name, zone in zones.items():
            index = integer()
            sizes = np.array([len(zone["coords"]), len(zone["cells"]), 0], dtype=dtype)
            call("cg_zone_write", fn, base, name.encode(), sizes.ctypes.data_as(ps), 3, ct.byref(index))
            indices[name] = index.value
        for name, zone in zones.items():
            z = indices[name]
            index = integer()
            for axis, label in enumerate(["CoordinateX", "CoordinateY", "CoordinateZ"]):
                array = np.ascontiguousarray(zone["coords"][:, axis], dtype=np.float64)
                call("cg_coord_write", fn, base, z, 4, label.encode(), ct.c_void_p(array.ctypes.data), ct.byref(index))
            cells = np.ascontiguousarray(zone["cells"], dtype=dtype)
            call("cg_section_write", fn, base, z, b"volume_cells", 10, 1, len(cells), 0, cells.ctypes.data_as(ps), ct.byref(index))
            offset = len(cells)
            for patch_name, patch in zone["patches"].items():
                faces = np.ascontiguousarray(patch["local_faces"], dtype=dtype)
                call("cg_section_write", fn, base, z, patch_name.encode(), 5, offset + 1, offset + len(faces), 0, faces.ctypes.data_as(ps), ct.byref(index))
                extent = np.array([offset + 1, offset + len(faces)], dtype=dtype)
                bc = integer()
                call("cg_boco_write", fn, base, z, patch_name.encode(), BC_TYPES[patch["role"]], 4, 2, extent.ctypes.data_as(ps), ct.byref(bc))
                call("cg_boco_gridlocation_write", fn, base, z, bc, 4)
                offset += len(faces)
        lookup = {p: z for z, info in zones.items() for p in info["patches"]}
        for i, pair in enumerate(manifest.get("interfaces", [])):
            for side, (own, other) in enumerate([(pair["a"], pair["b"]), (pair["b"], pair["a"]) ]):
                a, b = lookup[own], lookup[other]
                nodes = np.unique(zones[a]["patches"][own]["global_faces"])
                own_nodes = np.ascontiguousarray(zones[a]["local_map"][nodes], dtype=dtype)
                donor = np.ascontiguousarray(zones[b]["local_map"][nodes], dtype=dtype)
                index = integer()
                call("cg_conn_write", fn, base, indices[a], ("conn_%d_%d" % (i, side)).encode(), 2, 4, 2, len(nodes), own_nodes.ctypes.data_as(ps),
                     b.encode(), 3, 3, 6 if env["cgns_index_bits"] == 64 else 2, len(nodes), donor.ctypes.data_as(ps), ct.byref(index))
    finally:
        call("cg_close", fn)
        if cookie:
            cookie.close()


def verify_cgns(path, zones, manifest):
    """通过独立 HDF5 读路比对坐标、连接和边界；QFlux 回读另做。"""
    import numpy as np
    import h5py
    with h5py.File(path, "r") as handle:
        for name, source in zones.items():
            z = handle["CFD/" + name]
            coords = np.column_stack([z["GridCoordinates/" + axis + "/ data"][...] for axis in ["CoordinateX", "CoordinateY", "CoordinateZ"]])
            cells = z["volume_cells/ElementConnectivity/ data"][...].reshape(-1, 4)
            if not np.array_equal(coords, source["coords"]) or not np.array_equal(cells, source["cells"]):
                raise ValueError("CGNS 回读坐标/体连接改变：" + name)
            for patch, info in source["patches"].items():
                if not np.array_equal(z[patch + "/ElementConnectivity/ data"][...].reshape(-1, 3), info["local_faces"]):
                    raise ValueError("CGNS 边界连接改变：" + patch)
        lookup = {p: z for z, data in zones.items() for p in data["patches"]}
        for i, pair in enumerate(manifest.get("interfaces", [])):
            for side, (own, other) in enumerate([(pair["a"], pair["b"]), (pair["b"], pair["a"]) ]):
                a, b = lookup[own], lookup[other]
                nodes = np.unique(zones[a]["patches"][own]["global_faces"])
                conn = handle["CFD/" + a + "/ZoneGridConnectivity/conn_%d_%d" % (i, side)]
                if not np.array_equal(conn["PointList/ data"][...].ravel(), zones[a]["local_map"][nodes]) or not np.array_equal(conn["PointListDonor/ data"][...].ravel(), zones[b]["local_map"][nodes]):
                    raise ValueError("CGNS 接口节点连接改变：" + own)


def main():
    """输出机器可读检查记录，阈值来自本案例而非某个历史模型。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    args = parser.parse_args()
    root, cfg, env = context(args.case)
    add_build_paths(env)
    # Windows 下先导入 h5py，避免厂商 CGNS 的同名 HDF5 DLL 抢占其依赖。
    import h5py
    import gmsh
    manifest = read_json(inside(root, cfg["files"]["regions"]))
    validate_manifest(manifest)
    output = inside(root, cfg["files"]["mesh_cgns"])
    check = inside(root, cfg["files"]["mesh_check"])
    if output.exists() or check.exists():
        raise FileExistsError("CGNS 或检查文件已存在，请使用新案例/输出配置")
    output.parent.mkdir(parents=True, exist_ok=True)
    gmsh.initialize()
    try:
        gmsh.open(str(inside(root, cfg["files"]["mesh_msh"])))
        zones, checks = extract_zones(gmsh, cfg, manifest)
        write_cgns(output, zones, manifest, env)
        verify_cgns(output, zones, manifest)
    finally:
        gmsh.finalize()
    report = {"units": "m", "zones": checks, "cgns_sha256": sha256(output), "interface_count": len(manifest.get("interfaces", [])),
              "skewness_definition": "1 - V/V_equilateral_same_circumsphere", "aspect_ratio_definition": "sqrt(2/3)*longest_edge/minimum_altitude",
              "prism_layers": cfg["mesh"].get("prism_layers"), "grid_convergence_study": cfg["mesh"].get("grid_convergence_study"),
              "qflux_readback_verified": False}
    write_json(check, report)
    print("CGNS_EXPORT_COMPLETE", sum(z["cells"] for z in checks.values()), "cells", len(zones), "zones")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)

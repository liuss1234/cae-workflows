"""检查STAR导出的单区NGON/NFACE网格及原生边界层采样，不改变单元拓扑。"""
from pathlib import Path
import argparse
import hashlib
import json

# 可调参数集中设置；目标边界层数来自case.json，覆盖率是本次工程验收要求。
ROOT = Path(__file__).resolve().parents[1]
CHUNK_FACES = 100000
LAYER_MATCH_DECIMALS = 9
MIN_FULL_LAYER_AREA = 0.95


def digest(path):
    """分块计算文件哈希，避免把大型网格全部读入内存。"""
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def polygon_geometry(section, xyz):
    """按原有顶点顺序计算面面积向量、体积分量和面心。"""
    import numpy as np
    offsets = section["ElementStartOffset/ data"][...].astype(np.int64)
    offsets -= offsets[0]
    conn = section["ElementConnectivity/ data"][...].astype(np.int64) - 1
    widths = np.diff(offsets)
    n = len(widths)
    moment = np.empty(n);area = np.empty(n)
    normal = np.empty((n, 3));centers = np.empty((n, 3))
    reference = (xyz.min(axis=0) + xyz.max(axis=0)) / 2
    for begin in range(0, n, CHUNK_FACES):
        end = min(begin + CHUNK_FACES, n)
        for width in np.unique(widths[begin:end]):
            if width < 3:
                raise ValueError("存在少于3个顶点的面")
            ids = np.flatnonzero(widths[begin:end] == width) + begin
            points = xyz[conn[offsets[ids, None] + np.arange(width)]]
            centers[ids] = points.mean(axis=1)
            p = points - reference
            vector = np.cross(p[:, 1:-1] - p[:, 0, None], p[:, 2:] - p[:, 0, None]) * .5
            normal[ids] = vector.sum(axis=1)
            area[ids] = np.linalg.norm(vector, axis=2).sum(axis=1)
            moment[ids] = np.einsum("ij,ij->i", p.mean(axis=1), normal[ids]) / 3
    return moment, area, normal, centers


def layer_statistics(centers, areas, csv, requested):
    """以STAR实际壁面层号计算面积覆盖率，拒绝用请求值替代实际生成结果。"""
    import numpy as np
    native = np.atleast_2d(np.genfromtxt(csv, delimiter=",", skip_header=1))
    header = csv.read_text(encoding="utf-8-sig").splitlines()[0].split(",")
    lc = next(i for i, name in enumerate(header) if "PrismLayerNumber" in name or "Prism Layer Number" in name)
    hc = next(i for i, name in enumerate(header) if "FirstPrismLayerHeight" in name or "First Prism Layer Height" in name)
    xc = next(i for i, name in enumerate(header) if name.strip().strip('"').startswith("X "))
    keys = [tuple(np.round(v, LAYER_MATCH_DECIMALS)) for v in native[:, xc:xc+3]]
    if len(keys) != len(set(keys)):
        raise ValueError("原生面心匹配出现重复或多义坐标，需增加匹配信息")
    mapping = {key: i for i, key in enumerate(keys)}
    indices = np.asarray([mapping.get(tuple(np.round(v, LAYER_MATCH_DECIMALS)), -1) for v in centers])
    matched = indices >= 0
    values = np.full(len(indices), np.nan);heights = np.full(len(indices), np.nan)
    values[matched] = native[indices[matched], lc];heights[matched] = native[indices[matched], hc]
    histogram = {str(int(k)): {"faces": int(np.sum(values == k)), "area_fraction": float(areas[values == k].sum()/areas.sum())}
                 for k in np.unique(values[np.isfinite(values)])}
    # 层号正确但首层为零/非有限时也不能算完整层覆盖。
    full = float(areas[(values == requested) & np.isfinite(heights) & (heights > 0)].sum()/areas.sum())
    good = heights[np.isfinite(heights) & (heights > 0)]
    return {"source": str(csv.relative_to(ROOT)), "faces": len(areas), "area_m2": float(areas.sum()),
            "requested_layers": requested, "actual_layer_histogram": histogram,
            "full_layer_area_fraction": full, "minimum_full_layer_area_fraction": MIN_FULL_LAYER_AREA,
            "unmatched_faces": int(np.sum(~matched)),
            "first_layer_height_m": {"min": float(good.min()), "median": float(np.median(good)), "max": float(good.max())} if len(good) else None,
            "passed": bool(np.all(matched) and full >= MIN_FULL_LAYER_AREA)}


def main():
    """核对体积、闭合、连接拓扑、边界完整性及原生质量；只对当前文件签名。"""
    global ROOT, MIN_FULL_LAYER_AREA
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--mesh", required=True)
    parser.add_argument("--native", default=None)
    parser.add_argument("--output", default="checks/mesh.json")
    args = parser.parse_args()
    import h5py
    import numpy as np
    ROOT = Path(args.case).resolve()
    target_output = (ROOT / args.output).resolve()
    target_output.relative_to(ROOT)
    if target_output.exists():
        raise FileExistsError(target_output)
    cfg = json.loads((ROOT/"case.json").read_text(encoding="utf-8"))
    MIN_FULL_LAYER_AREA = cfg["validation"]["minimum_full_prism_layer_area_fraction"]
    version = cfg["mesh"]["version"]
    args.native = args.native or "checks/"+version+"_native_quality.json"
    meta = json.loads((ROOT/"checks/cad_boundaries.json").read_text(encoding="utf-8"))
    if meta.get("units") != "mm" or not np.isfinite(meta["volume_m3"]) or meta["volume_m3"] <= 0:
        raise ValueError("CAD审计必须为已确认mm坐标和正的米制体积")
    native = json.loads((ROOT/args.native).read_text(encoding="utf-8"))
    mesh = ROOT/args.mesh
    expected = {b["name"] for b in meta["groups"]}
    thresholds = cfg["validation"]
    zones = {};layers = {}
    with h5py.File(mesh, "r") as handle:
        bases = [g for g in handle.values() if isinstance(g, h5py.Group) and g.attrs.get("label") == b"CGNSBase_t"]
        actual = [(name, g) for base in bases for name, g in base.items() if isinstance(g, h5py.Group) and g.attrs.get("label") == b"Zone_t"]
        if len(actual) != 1 or actual[0][0] != "fluid_supply":
            raise ValueError("需要唯一fluid_supply网格区："+str([n for n, _ in actual]))
        name, zone = actual[0]
        xyz = np.column_stack([zone["GridCoordinates/Coordinate"+a+"/ data"][...] for a in "XYZ"])
        if not np.all(np.isfinite(xyz)):
            raise ValueError("存在非有限节点")
        sections = {n: g for n, g in zone.items() if isinstance(g, h5py.Group) and g.attrs.get("label") == b"Elements_t"}
        nf = [g for g in sections.values() if int(g[" data"][0]) == 23]
        ng = {n: g for n, g in sections.items() if int(g[" data"][0]) == 22}
        if len(nf) != 1 or len(nf)+len(ng) != len(sections):
            raise ValueError("仅支持完整NGON/NFACE导出，发现其他拓扑需明确适配")
        nf = nf[0]
        offset = nf["ElementStartOffset/ data"][...].astype(np.int64);offset -= offset[0]
        refs = nf["ElementConnectivity/ data"][...].astype(np.int64)
        if len(offset) < 2 or np.any(np.diff(offset) < 4) or offset[0] != 0 or offset[-1] != len(refs):
            raise ValueError("NFACE偏移或单元面数错误")
        count = max(int(g["ElementRange/ data"][1]) for g in ng.values())
        moments = np.zeros(count);areas = np.zeros(count);normals = np.zeros((count, 3));covered = np.zeros(count, dtype=bool)
        boundary_counts = {};boundary_areas = {};boundary_mask = np.zeros(count, dtype=bool)
        for patch, section in ng.items():
            moment, area, normal, center = polygon_geometry(section, xyz)
            begin, end = section["ElementRange/ data"][...] - [1, 0]
            if np.any(covered[begin:end]):raise ValueError("面编号重叠")
            covered[begin:end] = True;moments[begin:end] = moment;areas[begin:end] = area;normals[begin:end] = normal
            if patch in expected:
                boundary_counts[patch] = len(area);boundary_areas[patch] = float(area.sum())
                boundary_mask[begin:end] = True
            if patch in cfg["mesh"]["wall_layer_spec"]:
                spec = cfg["mesh"]["wall_layer_spec"].get(patch)
                if spec is None:
                    raise ValueError("壁面缺少独立边界层要求："+patch)
                requested = spec["layers"]
                csv = ROOT/"checks"/(version+"_"+patch+"_layers.csv")
                layers[patch] = layer_statistics(center, area, csv, requested)
            print("CHECKED_FACE_SECTION", patch, len(area), flush=True)
        if set(boundary_counts) != expected or any(v <= 0 for v in boundary_counts.values()):
            raise ValueError("预期边界缺失、为空或多余")
        ids = np.abs(refs)-1;signs = np.sign(refs)
        if np.any(ids < 0) or np.any(ids >= count) or not np.all(covered[ids]):raise ValueError("单元引用缺失面")
        use = np.bincount(ids, minlength=count)
        if np.any(use[covered] < 1) or np.any(use[covered] > 2):raise ValueError("非流形面连接")
        if not np.array_equal(use == 1, boundary_mask):raise ValueError("实际外边界与命名面覆盖不一致")
        signed_use = np.bincount(ids, weights=signs, minlength=count)
        if np.any(signed_use[use == 2] != 0):raise ValueError("共享面的两侧引用方向不相反")
        volume = np.add.reduceat(moments[ids]*signs, offset[:-1])
        closure = np.column_stack([np.add.reduceat(normals[ids, i]*signs, offset[:-1]) for i in range(3)])
        cell_area = np.add.reduceat(areas[ids], offset[:-1])
        ratio = np.linalg.norm(closure, axis=1)/cell_area
        cad = meta["volume_m3"];q = native["quality"]
        volume_error = float(abs(volume.sum()-cad)/cad)
        bbox = [xyz.min(0).tolist(), xyz.max(0).tolist()]
        target = np.asarray(meta["bbox_mm"]).reshape(2, 3)*.001
        bbox_error = float(np.max(np.abs(np.asarray(bbox)-target)))
        passed = bool(np.all(np.isfinite(volume)) and np.all(volume > 0) and np.all(cell_area > 0)
                      and np.all(np.isfinite(ratio)) and ratio.max() < thresholds["max_relative_closure"]
                      and volume_error <= thresholds["max_volume_error_fraction"] and bbox_error <= thresholds.get("cad_bbox_tolerance_m", .00025)
                      and q["Volume"]["min"] > 0 and q["SkewnessAngle"]["max"] < thresholds["max_skewness_angle_deg"]
                      and q["FaceValidity"]["min"] >= thresholds["min_face_validity"] and len(volume) == native["cells"])
        zones[name] = {"cells": len(volume), "nodes": len(xyz), "boundaries": boundary_counts, "boundary_area_m2": boundary_areas,
                       "bbox_m": bbox, "bbox_error_m": bbox_error, "cell_topology": "NGON_n/NFACE_n",
                       "nonpositive_volume_count": int(np.sum(volume <= 0)), "volume_m3": float(volume.sum()),
                       "cad_volume_m3": cad, "volume_relative_error": volume_error, "volume_min_m3": float(volume.min()),
                       "max_relative_closure": float(ratio.max()), "native_quality": q, "passed": passed}
    result = {"units": "m", "cgns_sha256": digest(mesh), "zones": zones, "boundary_layers": layers,
              "cells_total": sum(z["cells"] for z in zones.values()), "mesh_generator": "STAR_CCM_TrimmedCell_Prism",
              "mesh_version": version,
              "passed": bool(all(z["passed"] for z in zones.values()) and set(layers) == set(cfg["mesh"]["wall_layer_spec"]) and all(layer["passed"] for layer in layers.values())),
              "scope": "actual topology, closed cell volumes, native quality and wall prism coverage; y+ and grid sensitivity assessed separately"}
    target_output.parent.mkdir(parents=True, exist_ok=True)
    with target_output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({k: v for k, v in result.items() if k not in ["zones"]}, ensure_ascii=False), flush=True)
    if not result["passed"]:raise RuntimeError("网格验收未通过，请检查实际质量和层覆盖结果")


if __name__ == "__main__":
    main()

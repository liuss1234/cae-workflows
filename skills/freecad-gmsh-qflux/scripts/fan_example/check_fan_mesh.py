# -*- coding: utf-8 -*-
"""独立重新读取 Gmsh 网格，检查体积、形状质量、边界覆盖与接口共形性。"""
# 本文件为七叶风扇参考实现；其他 CAD 必须重新映射零件与边界，不能直接套用。


# 可调参数：分块处理控制内存，不把观察分档值作为通用求解器验收标准。
from pathlib import Path
import os
WORK_DIRECTORY = Path(os.environ["CFD_WORK_DIRECTORY"]).resolve()  # 由运行器指定独立项目目录
API_DIRECTORY = Path(os.environ["CFD_GMSH_API"])
CHUNK_SIZE = 100000
ZERO_VOLUME_TOL_MM3 = 1.0e-15
SICN_OBSERVATION_LEVELS = (0.1, 0.2, 0.3)
PERCENTILES = (0, 1, 5, 50, 95, 99, 100)

import argparse
import gc
import json
import sys
import time
import traceback
sys.path.insert(0, str(API_DIRECTORY))
import gmsh
import numpy as np


def summary(values):
    """统一输出实际统计分位数，保留最差值。"""
    return {f"p{p}": float(v) for p, v in zip(PERCENTILES, np.percentile(values, PERCENTILES))}


def key_rows(rows):
    """将节点三元组转成可排序键，避免使用百万级 Python 元组。"""
    array = np.ascontiguousarray(rows, dtype=np.uint32)
    dtype = np.dtype([(f"n{i}", np.uint32) for i in range(array.shape[1])])
    return array.view(dtype).ravel()


def calculate_metrics(tets, coords):
    """分块计算有符号体积、形心、边长比和明确限定定义的二面角偏斜度。"""
    count = len(tets)
    volume = np.empty(count)
    centers = np.empty((count, 3))
    edge_ratio = np.empty(count)
    angle_skew = np.empty(count)
    ideal = np.arccos(1.0 / 3.0)
    for start in range(0, count, CHUNK_SIZE):
        end = min(start + CHUNK_SIZE, count)
        points = coords[tets[start:end]]
        v1 = points[:, 1] - points[:, 0]
        v2 = points[:, 2] - points[:, 0]
        v3 = points[:, 3] - points[:, 0]
        volume[start:end] = np.einsum("ij,ij->i", np.cross(v1, v2), v3) / 6.0
        centers[start:end] = np.mean(points, axis=1)
        lengths = np.stack([np.linalg.norm(points[:, a] - points[:, b], axis=1)
                            for a, b in ((0,1),(0,2),(0,3),(1,2),(1,3),(2,3))], axis=1)
        edge_ratio[start:end] = lengths.max(axis=1) / lengths.min(axis=1)
        normals = np.stack([np.cross(points[:, b]-points[:, a], points[:, c]-points[:, a])
                            for a,b,c in ((1,2,3),(0,3,2),(0,1,3),(0,2,1))], axis=1)
        normals /= np.maximum(np.linalg.norm(normals, axis=2, keepdims=True), 1.0e-300)
        angles = np.stack([np.arccos(np.clip(-np.einsum("ij,ij->i", normals[:, a], normals[:, b]),-1,1))
                           for a,b in ((0,1),(0,2),(0,3),(1,2),(1,3),(2,3))], axis=1)
        angle_skew[start:end] = np.maximum((angles.max(axis=1)-ideal)/(np.pi-ideal),
                                           (ideal-angles.min(axis=1))/ideal)
    return volume, centers, edge_ratio, angle_skew


def check_topology(tets, zones, coords, centers, volume, manifest):
    """逐面统计四面体邻接，并验证每个已命名三角形的两侧区域。"""
    faces = tets[:, [[0,1,2],[0,1,3],[0,2,3],[1,2,3]]].reshape(-1,3).copy()
    faces.sort(axis=1)
    keys = key_rows(faces)
    order = np.argsort(keys, kind="quicksort")
    sorted_keys = keys[order]
    # 排序位置除以 4 得到该面的所属单元索引。
    boundaries = np.r_[0, np.flatnonzero(sorted_keys[1:] != sorted_keys[:-1])+1, len(keys)]
    incidence = np.diff(boundaries)
    unique_count = len(incidence)
    boundary_count = int(np.count_nonzero(incidence == 1))
    internal_count = int(np.count_nonzero(incidence == 2))
    result = {"unique_tetrahedron_faces": unique_count, "external_faces": boundary_count,
              "internal_faces": internal_count, "nonmanifold_faces": int(np.count_nonzero(incidence > 2))}
    print("TOPOLOGY face incidence counted", flush=True)
    physical = {}
    all_triangles = []
    exterior_triangles = 0
    interface_triangles = 0
    region_entities = manifest["regions"]
    for name, physical_tag in manifest["physical_surfaces"].items():
        entities = gmsh.model.getEntitiesForPhysicalGroup(2, physical_tag)
        blocks = []
        for entity in entities:
            types, _, node_blocks = gmsh.model.mesh.getElements(2, int(entity))
            for typ, nodes in zip(types, node_blocks):
                if typ != 2:
                    raise RuntimeError(f"边界 {name} 存在非三节点三角形：type={typ}")
                blocks.append(np.asarray(nodes, dtype=np.uint32).reshape(-1,3))
        triangles = np.concatenate(blocks)
        triangles.sort(axis=1)
        tri_keys = key_rows(triangles)
        left = np.searchsorted(sorted_keys, tri_keys, side="left")
        right = np.searchsorted(sorted_keys, tri_keys, side="right")
        required_incidence = 2 if name.startswith("interface_") else 1
        bad_incidence = int(np.count_nonzero(right-left != required_incidence))
        if name.startswith("interface_"):
            interface_triangles += len(triangles)
            other = "fluid_stationary_inlet" if name == "interface_inlet" else "fluid_stationary_outlet"
            expected_zones = np.sort([region_entities["fluid_rotating"],region_entities[other]])
            valid = right-left == 2
            actual_zones = np.sort(np.stack([zones[order[left[valid]]//4],
                                            zones[order[left[valid]+1]//4]],axis=1),axis=1)
            wrong_zones = int(np.count_nonzero(np.any(actual_zones != expected_zones,axis=1)))
        else:
            exterior_triangles += len(triangles)
            expected_region = next(item["adjacent_regions"][0] for item in manifest["surface_matching"] if item["patch"] == name)
            valid = right-left == 1
            wrong_zones = int(np.count_nonzero(zones[order[left[valid]]//4] != region_entities[expected_region]))
        physical[name] = {"triangles": len(triangles), "nodes": len(np.unique(triangles)),
                          "incorrect_face_incidence": bad_incidence, "incorrect_neighbor_regions": wrong_zones,
                          "expected_tetrahedra_per_triangle": required_incidence}
        all_triangles.append(triangles)
    surface_keys = key_rows(np.concatenate(all_triangles))
    result.update(physical_surface_triangles=len(surface_keys), external_named_triangles=exterior_triangles,
                  interface_named_triangles=interface_triangles,
                  duplicate_surface_triangles=len(surface_keys)-len(np.unique(surface_keys)),
                  unlabelled_external_faces=boundary_count-exterior_triangles)
    del all_triangles, surface_keys, triangles, faces, keys
    gc.collect()
    # 内部面非正交角：面法向与两单元形心连线的夹角，取绝对值后为 0~90 度。
    start_positions = boundaries[:-1][incidence == 2]
    nonorth = np.empty(len(start_positions))
    volume_ratio = np.empty(len(start_positions))
    worst_face = None
    worst_angle = -1.0
    for start in range(0, len(start_positions), CHUNK_SIZE):
        end = min(start+CHUNK_SIZE,len(start_positions))
        positions = start_positions[start:end]
        owner = order[positions]//4
        neighbor = order[positions+1]//4
        face_nodes = sorted_keys[positions].view(np.uint32).reshape(-1,3)
        points = coords[face_nodes]
        normals = np.cross(points[:,1]-points[:,0],points[:,2]-points[:,0])
        delta = centers[neighbor]-centers[owner]
        cosine = np.abs(np.einsum("ij,ij->i",normals,delta)) / np.maximum(
            np.linalg.norm(normals,axis=1)*np.linalg.norm(delta,axis=1),1.0e-300)
        values = np.degrees(np.arccos(np.clip(cosine,0,1)))
        nonorth[start:end] = values
        a = np.abs(volume[owner]); b = np.abs(volume[neighbor])
        volume_ratio[start:end] = np.maximum(a,b)/np.maximum(np.minimum(a,b),1.0e-300)
        worst_index = int(np.argmax(values))
        if values[worst_index] > worst_angle:
            worst_angle = float(values[worst_index])
            worst_face = {"center_mm": points[worst_index].mean(axis=0).tolist(),
                          "region_entities": [int(zones[owner[worst_index]]), int(zones[neighbor[worst_index]])]}
    result["internal_face_nonorthogonality_deg"] = summary(nonorth)
    result["adjacent_cell_volume_ratio"] = summary(volume_ratio)
    result["worst_nonorthogonal_face"] = worst_face
    result["nonorthogonality_definition"] = "acos(abs(n dot (neighbor_centroid-owner_centroid))/(|n| |delta|)), degrees"
    return result, physical


def write_report(directory, report, manifest):
    """输出可供后续求解器导入复核的中文技术记录。"""
    quality = report["quality"]
    topology = report["topology"]
    lines = [
        "# 风扇 CFD 初始网格检查报告", "",
        f"使用用户指定的 Gmsh 4.14.1 生成；网格为 MSH 4.1 二进制，坐标单位 mm。",
        f"节点 **{report['nodes']:,}**；一阶四面体 **{report['tetrahedra']:,}**；三个流体体区域，十个面物理组（含两个内部接口）。",
        "", "## 几何与网格参数", "",
        "| 项目 | 数值或说明 |", "|---|---|",
        "| 管径 / 轴向范围 | 130 mm；z = −675 至 +276 mm |",
        "| 旋转区 | z = −10.5 至 +18 mm；轴线 +Z，原点 (0,0,0) |",
        "| 流向 | +Z 入口至 −Z 出口 |",
        "| 叶尖最小设计间隙 | 2.549027 mm，保留 |",
        "| 目标网格尺寸 | 叶片 1.2 mm；叶尖 0.65 mm；支撑 0.8 mm；后轮毂接口 0.4 mm；远端 15 mm |",
        "| 生成方法 | 二维 Frontal-Delaunay；三维 HXT；局部连续尺寸场 |",
        "| 边界层 / 湍流模型 / 转速 | 未设置；本次不假定工况 |",
        "", "## 区域统计与 CAD 体积比较", "",
        "| 区域 | 四面体数 | 网格体积 mm³ | 相对 CAD 偏差 % |", "|---|---:|---:|---:|",
    ]
    for name, item in report["regions"].items():
        lines.append(f"| {name} | {item['tetrahedra']:,} | {item['mesh_volume_mm3']:.6f} | {item['volume_relative_error_percent']:.6f} |")
    lines += ["", "曲面采用平面三角形逼近，因此网格与 CAD 体积可能有小幅差异。", "", "## 质量与拓扑", "",
        "| 指标 | 实测结果 |", "|---|---|",
        f"| 负体积 / 零体积 | {quality['negative_volume_count']} / {quality['near_zero_volume_count']} |",
        f"| 最小有符号单元体积 | {quality['volume_mm3']['p0']:.8g} mm³ |",
        f"| minSICN 最小 / P1 / 中位数 | {quality['minSICN']['p0']:.5f} / {quality['minSICN']['p1']:.5f} / {quality['minSICN']['p50']:.5f} |",
        f"| 最长边/最短边 最大值 | {quality['max_edge_over_min_edge']['p100']:.4f} |",
        f"| 二面角等角偏斜度 P99 / 最大值 | {quality['dihedral_equiangular_skewness']['p99']:.5f} / {quality['dihedral_equiangular_skewness']['p100']:.5f} |",
        f"| 内部面非正交角 P99 / 最大值 | {topology['internal_face_nonorthogonality_deg']['p99']:.3f}° / {topology['internal_face_nonorthogonality_deg']['p100']:.3f}° |",
        f"| 相邻单元体积比 P99 / 最大值 | {topology['adjacent_cell_volume_ratio']['p99']:.3f} / {topology['adjacent_cell_volume_ratio']['p100']:.3f} |",
        f"| 非流形面 / 未命名外边界面 | {topology['nonmanifold_faces']} / {topology['unlabelled_external_faces']} |",
        f"| 重复四面体 / 重复面单元 | {report['duplicate_tetrahedra']} / {topology['duplicate_surface_triangles']} |",
        "", "minSICN 是 Gmsh 的有符号逆条件数质量指标，越接近 1 形状越好；分档数量仅用于观察。",
        "二面角等角偏斜度使用理想四面体二面角 acos(1/3) 归一化，不能直接替代特定求解器的 skewness 定义。",
        "非正交角按面法向与相邻单元形心连线计算；实际导入后仍须按目标求解器复核。",
        f"最差 minSICN 单元：{json.dumps(quality['worst_sicn_element'], ensure_ascii=False)}。",
        f"最大非正交角位置：{json.dumps(topology['worst_nonorthogonal_face'], ensure_ascii=False)}。",
        "", "## 边界与共形接口", "",
        "| 物理组 | 三角形数 | 邻接错误 | 区域配对错误 |", "|---|---:|---:|---:|",
    ]
    for name, item in report["surface_groups"].items():
        lines.append(f"| {name} | {item['triangles']:,} | {item['incorrect_face_incidence']} | {item['incorrect_neighbor_regions']} |")
    lines += [
        "", "两个 interface 面组均要求每个三角形恰好属于两侧各一个四面体，节点编号与三角形连接完全共用。",
        "wall_rotor_rotating 是转子壁；wall_duct_rotating 和 wall_stator_rotating 均须设为绝对静止壁。",
        "", "## 使用限制与后续复核", "",
        "- 本网格用于几何、接口及初步计算验证，不含棱柱边界层，也没有完成网格无关性研究。",
        "- 本次建立共形 MRF 区域；瞬态滑移网格需要在目标求解器中按其要求分离/配对接口并验证相对旋转。",
        "- 目标求解器尚未指定。此 .msh 是 Gmsh MSH 4.1，不是 Fluent 原生 .msh；需按求解器格式导入或转换。",
        "- 按 mm 导入，若求解器以 m 工作，应缩放坐标 0.001，并复核管径为 0.130 m。",
        "- 获得转速、流量/压力、物性及壁面处理后，再确定 y+、首层高度、层数和总厚度；这些条件目前未提供。",
        "- 建议后续按局部尺寸倍率 1.3 / 1.0 / 0.77 规划粗/中/细网格，保持几何和工况一致，对压升、流量与扭矩报告相邻网格相对变化；尚未执行该研究。",
        "- 基础有效性检查通过不等于已达到特定求解器或最终 CFD 精度要求。",
        "", "## 文件与复现", "",
        "- fan_cfd_mm.msh：完整三域体网格。",
        "- fan_cfd_mm_ascii22.msh：Gmsh 2.2 ASCII 兼容版本；已另存到桌面同名 fan_cfd_mm.msh，适合优先尝试 QFlux 导入。ascii_conversion_check.json 记录格式转换后的连接关系复核；尚未在 QFlux 内实际导入验证。",
        "- view_rotating_section.geo：旋转流体区剖切显示，切面显示与剖切面相交的完整四面体，锯齿来自单元显示方式。",
        "- view_blades.geo：仅显示叶片、轮毂与支撑的壁面三角形，便于观察局部加密；体网格并未删除。",
        "- view_domains.geo：完整入口、旋转区、出口区域外表面网格。用 Gmsh 的 File > Open 打开任一视图脚本。",
        "- fan_cfd.geo / fluid_conformal_mm.brep：可重复划分输入。",
        "- mesh_manifest.json：原始几何参数、面名称映射、所有网格设置。",
        "- mesh_quality.json：完整分位数、区域和接口检查数据。",
        "- gmsh_mesh.log / mesh_process.json：实际可执行路径、退出码和生成日志。",
        "- 依赖：Python 3.11、NumPy、Gmsh 4.14.1 Python API；生成网格调用用户指定的 gmsh.exe。",
        "- 运行：python mesh_fan_gmsh.py；复核：python check_fan_mesh.py。脚本位于上一级目录，每次完整生成使用新输出目录。",
    ]
    (directory / "网格检查报告.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def main():
    """重新加载已落盘网格，只有全部基础检查通过才标记通过。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    options = parser.parse_args()
    directory = options.directory or Path(json.loads((WORK_DIRECTORY/"latest_mesh.json").read_text(encoding="utf-8"))["output_directory"])
    manifest = json.loads((directory/"mesh_manifest.json").read_text(encoding="utf-8"))
    started = time.perf_counter()
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal",0)
        gmsh.open(str(directory/"fan_cfd_mm.msh"))
        expected_groups = {(2,p,n) for n,p in manifest["physical_surfaces"].items()}
        expected_groups |= {(3,p,n) for n,p in manifest["physical_volumes"].items()}
        actual_groups = {(d,p,gmsh.model.getPhysicalName(d,p)) for d,p in gmsh.model.getPhysicalGroups()}
        if actual_groups != expected_groups:
            raise RuntimeError("导出的物理组与预期不一致")
        node_tags, coordinates, _ = gmsh.model.mesh.getNodes(returnParametricCoord=False)
        coords = np.full((int(max(node_tags))+1,3),np.nan)
        coords[node_tags] = coordinates.reshape(-1,3)
        tags, tetrahedra, zone_arrays = [], [], []
        regions = {}
        for name, entity in manifest["regions"].items():
            types, tag_blocks, nodes = gmsh.model.mesh.getElements(3, entity)
            if list(types) != [4]:
                raise RuntimeError(f"{name} 不是单一一阶四面体网格：{types}")
            tags.append(tag_blocks[0])
            tetrahedra.append(np.asarray(nodes[0],dtype=np.uint32).reshape(-1,4))
            zone_arrays.append(np.full(len(tag_blocks[0]),entity,dtype=np.int32))
        element_tags = np.concatenate(tags)
        tets = np.concatenate(tetrahedra)
        zones = np.concatenate(zone_arrays)
        del tags, tetrahedra, zone_arrays, nodes, tag_blocks
        print(f"LOADED nodes={len(node_tags)} tetrahedra={len(tets)}",flush=True)
        volumes, centers, edge_ratio, skew = calculate_metrics(tets,coords)
        sicn = gmsh.model.mesh.getElementQualities(element_tags,"minSICN")
        jacobian = gmsh.model.mesh.getElementQualities(element_tags,"minDetJac")
        worst = int(np.argmin(sicn))
        names_by_tag = {tag:name for name,tag in manifest["regions"].items()}
        quality = {
            "negative_volume_count": int(np.count_nonzero(volumes < 0)),
            "near_zero_volume_count": int(np.count_nonzero(np.abs(volumes) <= ZERO_VOLUME_TOL_MM3)),
            "nonpositive_jacobian_count": int(np.count_nonzero(jacobian <= 0)),
            "volume_mm3": summary(volumes), "minDetJac_mm3": summary(jacobian),
            "minSICN": summary(sicn), "max_edge_over_min_edge": summary(edge_ratio),
            "dihedral_equiangular_skewness": summary(skew),
            "minSICN_counts_below": {str(x):int(np.count_nonzero(sicn<x)) for x in SICN_OBSERVATION_LEVELS},
            "worst_sicn_element": {"element_tag":int(element_tags[worst]), "quality":float(sicn[worst]),
                "region":names_by_tag[int(zones[worst])], "centroid_mm":centers[worst].tolist()},
        }
        for name, entity in manifest["regions"].items():
            selected = zones == entity
            cad = manifest["region_measures"][name]["volume_mm3"]
            volume = float(volumes[selected].sum())
            regions[name] = {"tetrahedra":int(selected.sum()), "mesh_volume_mm3":volume,
                            "cad_volume_mm3":cad,"volume_relative_error_percent":(volume/cad-1)*100,
                            "minSICN":summary(sicn[selected])}
        sorted_tets = np.sort(tets,axis=1)
        duplicate_tets = len(tets)-len(np.unique(key_rows(sorted_tets)))
        del sorted_tets, jacobian, sicn, edge_ratio, skew
        gc.collect()
        topology, physical = check_topology(tets,zones,coords,centers,volumes,manifest)
        basic_pass = (quality["negative_volume_count"] == 0 and quality["near_zero_volume_count"] == 0
            and quality["nonpositive_jacobian_count"] == 0 and duplicate_tets == 0
            and topology["nonmanifold_faces"] == 0 and topology["unlabelled_external_faces"] == 0
            and topology["duplicate_surface_triangles"] == 0
            and all(p["incorrect_face_incidence"] == 0 and p["incorrect_neighbor_regions"] == 0 for p in physical.values()))
        report = {"gmsh_api_version":gmsh.__version__,"mesh_file":str(directory/"fan_cfd_mm.msh"),
                  "units":"mm","nodes":len(node_tags),"tetrahedra":len(tets),
                  "duplicate_tetrahedra":duplicate_tets,"quality":quality,"regions":regions,
                  "topology":topology,"surface_groups":physical,"basic_checks_passed":basic_pass,
                  "elapsed_seconds":time.perf_counter()-started}
        (directory/"mesh_quality.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        write_report(directory,report,manifest)
        print(json.dumps({"nodes":report["nodes"],"tetrahedra":report["tetrahedra"],
                          "minSICN":quality["minSICN"],"negative_volumes":quality["negative_volume_count"],
                          "basic_checks_passed":basic_pass,"elapsed_seconds":report["elapsed_seconds"]},ensure_ascii=False),flush=True)
        if not basic_pass:
            raise RuntimeError("基础拓扑或有效性检查未通过，请查看 mesh_quality.json")
    finally:
        gmsh.finalize()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)

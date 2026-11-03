# -*- coding: utf-8 -*-
"""准备风扇共形流体域，并调用指定 Gmsh 可执行程序生成初始四面体网格。"""
# 本文件为七叶风扇参考实现；其他 CAD 必须重新映射零件与边界，不能直接套用。


# 可调参数集中在此；所有长度均为 mm，原始 FreeCAD/STEP 文件保持不变。
from pathlib import Path
import os
WORK_DIRECTORY = Path(os.environ["CFD_WORK_DIRECTORY"]).resolve()  # 由运行器指定独立项目目录
API_DIRECTORY = Path(os.environ["CFD_GMSH_API"])
GMSH_EXECUTABLE = Path(os.environ["CFD_GMSH_EXE"])
THREAD_COUNT = 4
FAR_SIZE = 15.0
ROTOR_SIZE = 1.2
STATOR_SIZE = 0.8
TIP_SIZE = 0.65
MIN_SIZE = 0.35
DISTANCE_SAMPLING = 180
FACE_AREA_REL_TOL = 1.0e-4
FACE_CENTER_TOL = 1.0e-3
VOLUME_REL_TOL = 1.0e-6

import argparse
import datetime
import json
import math
import os
import subprocess
import sys
import time
import traceback

sys.path.insert(0, str(API_DIRECTORY))
import gmsh


def save_json(path, value):
    """输出可审查的 UTF-8 记录。"""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def classify_volumes(report):
    """按体积与轴向位置恢复三个区域；不假设导入实体编号不变。"""
    regions = {}
    measurements = {}
    for dim, tag in gmsh.model.getEntities(3):
        center = gmsh.model.occ.getCenterOfMass(dim, tag)
        mass = gmsh.model.occ.getMass(dim, tag)
        if center[2] > report["domain"]["rotor_z_max_mm"]:
            name = "fluid_stationary_inlet"
        elif center[2] < report["domain"]["rotor_z_min_mm"]:
            name = "fluid_stationary_outlet"
        else:
            name = "fluid_rotating"
        expected = report["fluid_regions"][name]["volume_mm3"]
        error = abs(mass - expected) / expected
        if name in regions or error > VOLUME_REL_TOL:
            raise RuntimeError(f"区域拓扑或体积不一致：{name}, tag={tag}, relative_error={error}")
        regions[name] = int(tag)
        measurements[name] = {"entity": int(tag), "volume_mm3": mass,
                              "center_mm": list(center), "volume_relative_error": error}
    if len(regions) != 3:
        raise RuntimeError(f"预期三个流体域，实际 {len(regions)}")
    return regions, measurements


def classify_surfaces(regions, signatures):
    """用邻接关系识别接口，其余面按所属区域、面积及形心严格匹配。"""
    names_by_tag = {tag: name for name, tag in regions.items()}
    groups = {}
    matches = []
    used_signatures = set()
    for _, tag in gmsh.model.getEntities(2):
        upward, _ = gmsh.model.getAdjacencies(2, tag)
        adjacent = sorted(names_by_tag[int(t)] for t in upward)
        center = gmsh.model.occ.getCenterOfMass(2, tag)
        area = gmsh.model.occ.getMass(2, tag)
        record = {"entity": int(tag), "adjacent_regions": adjacent,
                  "area_mm2": area, "center_mm": list(center)}
        if len(adjacent) == 2:
            if set(adjacent) == {"fluid_rotating", "fluid_stationary_inlet"}:
                patch = "interface_inlet"
            elif set(adjacent) == {"fluid_rotating", "fluid_stationary_outlet"}:
                patch = "interface_outlet"
            else:
                raise RuntimeError(f"不合理区域接口：{adjacent}")
        elif len(adjacent) == 1:
            candidates = []
            for index, item in enumerate(signatures):
                if item["region"] != adjacent[0] or item["patch"].startswith("interface_"):
                    continue
                area_error = abs(area - item["area_mm2"]) / max(item["area_mm2"], 1.0e-12)
                distance = math.dist(center, item["center_mm"])
                if area_error <= FACE_AREA_REL_TOL and distance <= FACE_CENTER_TOL:
                    candidates.append((index, item, area_error, distance))
            if len(candidates) != 1:
                raise RuntimeError(f"面 {tag} 名称匹配数量为 {len(candidates)}，面积 {area}，形心 {center}")
            index, item, area_error, distance = candidates[0]
            if index in used_signatures:
                raise RuntimeError(f"原始面被重复匹配：{item}")
            used_signatures.add(index)
            patch = item["patch"]
            record.update(source_face=item["face"], area_relative_error=area_error,
                          center_distance_mm=distance)
        else:
            raise RuntimeError(f"面 {tag} 有 {len(adjacent)} 个相邻体")
        groups.setdefault(patch, []).append(int(tag))
        record["patch"] = patch
        matches.append(record)
    required = {i["patch"] for i in signatures if not i["patch"].startswith("interface_")}
    required.update(["interface_inlet", "interface_outlet"])
    if set(groups) != required or len(used_signatures) != len(signatures) - 4:
        raise RuntimeError("边界面覆盖不完整")
    return groups, matches


def geo_script(groups, regions):
    """生成可直接用 Gmsh GUI/命令行重复执行的几何和网格尺寸脚本。"""
    lines = [
        "// 风扇 CFD 初始体网格；长度单位 mm；由 mesh_fan_gmsh.py 生成。",
        'SetFactory("OpenCASCADE");',
        'Merge "fluid_conformal_mm.brep";',
        f"General.NumThreads = {THREAD_COUNT};",
        f"Mesh.MaxNumThreads1D = {THREAD_COUNT};",
        f"Mesh.MaxNumThreads2D = {THREAD_COUNT};",
        f"Mesh.MaxNumThreads3D = {THREAD_COUNT};",
        "Mesh.Algorithm = 6; // 二维 Frontal-Delaunay",
        "Mesh.Algorithm3D = 10; // 三维 HXT 四面体",
        "Mesh.ElementOrder = 1;",
        "Mesh.Optimize = 1;",
        "Mesh.OptimizeNetgen = 0;",
        "Mesh.MshFileVersion = 4.1;",
        "Mesh.Binary = 1;",
        "Mesh.SaveAll = 0;",
        "Mesh.MeshSizeFromPoints = 0;",
        "Mesh.MeshSizeFromCurvature = 20;",
        "Mesh.MeshSizeExtendFromBoundary = 0;",
        f"Mesh.MeshSizeMin = {MIN_SIZE};",
        f"Mesh.MeshSizeMax = {FAR_SIZE};",
    ]
    for index, (name, tags) in enumerate(sorted(groups.items()), 101):
        values = ", ".join(map(str, tags))
        lines.append(f'Physical Surface("{name}", {index}) = {{{values}}};')
    for index, (name, tag) in enumerate(sorted(regions.items()), 201):
        lines.append(f'Physical Volume("{name}", {index}) = {{{tag}}};')
    rotor_tags = ", ".join(map(str, groups["wall_rotor_rotating"]))
    stator_tags = ", ".join(map(str, groups["wall_stator_rotating"] + groups["wall_stator_stationary_outlet"]))
    lines += [
        "// 叶片、轮毂及锥罩表面附近加密。",
        "Field[1] = Distance;",
        f"Field[1].SurfacesList = {{{rotor_tags}}};",
        f"Field[1].Sampling = {DISTANCE_SAMPLING};",
        "Field[2] = Threshold; Field[2].InField = 1;",
        f"Field[2].SizeMin = {ROTOR_SIZE}; Field[2].SizeMax = {FAR_SIZE};",
        "Field[2].DistMin = 1; Field[2].DistMax = 32;",
        "// 电机、支撑臂及轴向接口附近加密。",
        "Field[3] = Distance;",
        f"Field[3].SurfacesList = {{{stator_tags}}};",
        f"Field[3].Sampling = {DISTANCE_SAMPLING};",
        "Field[4] = Threshold; Field[4].InField = 3;",
        f"Field[4].SizeMin = {STATOR_SIZE}; Field[4].SizeMax = {FAR_SIZE};",
        "Field[4].DistMin = 0.8; Field[4].DistMax = 28;",
        "// 连续解析尺寸场控制叶尖环隙，避免圆柱面采样稀疏。",
        "Field[5] = MathEval;",
        f'Field[5].F = "{TIP_SIZE} + 0.35*Max(0,62-Sqrt(x*x+y*y)) + 0.5*Max(0,Abs(z-3.75)-14.25)";',
        "// 后接口与转子、支撑各相距 0.5 mm，在轮毂附近额外细化。",
        "Field[6] = MathEval;",
        'Field[6].F = "0.4 + 0.4*Max(0,Sqrt(x*x+y*y)-21) + 0.5*Max(0,Abs(z+10.5)-1.5)";',
        "Field[7] = Min; Field[7].FieldsList = {2, 4, 5, 6};",
        "Background Field = 7;",
        "// 此网格不含棱柱边界层。MRF 旋转区的管壁及电机壁须设为绝对静止。",
    ]
    return "\n".join(lines) + "\n"


def prepare():
    """共享接口拓扑并保存可追溯输入；使用新目录保护前一版结果。"""
    location = json.loads((WORK_DIRECTORY / "latest_output.json").read_text(encoding="utf-8-sig"))
    source = Path(location["output_directory"])
    report = json.loads((source / "geometry_report.json").read_text(encoding="utf-8-sig"))
    signatures = json.loads((source / "face_signatures.json").read_text(encoding="utf-8-sig"))
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = WORK_DIRECTORY / f"mesh_{stamp}"
    destination.mkdir(exist_ok=False)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
        imported = gmsh.model.occ.importShapes(str(source / "fluid_regions.step"))
        volumes = [(d, t) for d, t in imported if d == 3]
        if len(volumes) != 3:
            raise RuntimeError(f"STEP 应有三个体，实际 {len(volumes)}")
        gmsh.model.occ.fragment(volumes[:1], volumes[1:], removeObject=True, removeTool=True)
        gmsh.model.occ.synchronize()
        classify_volumes(report)
        # 重新导入 BREP，保证后续独立 gmsh.exe 打开时实体编号一致。
        brep = destination / "fluid_conformal_mm.brep"
        gmsh.write(str(brep))
        gmsh.clear()
        gmsh.model.occ.importShapes(str(brep))
        gmsh.model.occ.synchronize()
        regions, measures = classify_volumes(report)
        groups, matches = classify_surfaces(regions, signatures)
        (destination / "fan_cfd.geo").write_text(geo_script(groups, regions), encoding="utf-8")
        manifest = {
            "source_directory": str(source), "output_directory": str(destination),
            "gmsh_executable": str(GMSH_EXECUTABLE), "gmsh_api_version": gmsh.__version__,
            "units": "mm", "regions": regions, "region_measures": measures,
            "surface_groups": groups, "surface_matching": matches,
            "physical_surfaces": {name: i for i, name in enumerate(sorted(groups), 101)},
            "physical_volumes": {name: i for i, name in enumerate(sorted(regions), 201)},
            "geometry_report": report,
            "mesh_parameters": {"far_mm": FAR_SIZE, "rotor_mm": ROTOR_SIZE,
                "stator_mm": STATOR_SIZE, "tip_mm": TIP_SIZE, "hub_interface_mm": 0.4,
                "min_mm": MIN_SIZE, "threads": THREAD_COUNT, "algorithm_3d": "HXT",
                "boundary_layers": False, "element_order": 1},
        }
        save_json(destination / "mesh_manifest.json", manifest)
        save_json(WORK_DIRECTORY / "latest_mesh.json", {"output_directory": str(destination)})
        print(f"PREPARED {destination}", flush=True)
        print(f"VOLUMES {len(regions)}; SURFACES {len(matches)}; PATCHES {len(groups)}", flush=True)
    finally:
        gmsh.finalize()
    return destination


def run_mesher(destination):
    """由用户指定的可执行文件实际生成网格；保存退出状态和完整日志。"""
    if not GMSH_EXECUTABLE.is_file():
        raise FileNotFoundError(GMSH_EXECUTABLE)
    mesh_path = destination / "fan_cfd_mm.msh"
    args = [str(GMSH_EXECUTABLE), str(destination / "fan_cfd.geo"), "-3", "-format", "msh4",
            "-o", str(mesh_path), "-nt", str(THREAD_COUNT), "-v", "4",
            "-log", str(destination / "gmsh_mesh.log")]
    started = time.perf_counter()
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    with (destination / "process_output.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(args, cwd=destination, stdout=log, stderr=subprocess.STDOUT, **kwargs)
        save_json(destination / "mesh_process.json", {"pid": process.pid, "command": args, "state": "running"})
        print(f"GMSH_MESHING pid={process.pid}", flush=True)
        exit_code = process.wait()
    result = {"pid": process.pid, "command": args, "exit_code": exit_code,
              "elapsed_seconds": time.perf_counter() - started,
              "mesh_file": str(mesh_path), "mesh_exists": mesh_path.is_file()}
    save_json(destination / "mesh_process.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if exit_code or not mesh_path.is_file():
        raise RuntimeError(f"Gmsh 网格生成失败，请检查 {destination / 'gmsh_mesh.log'}")


def main():
    """支持只准备、复用已有输入和完整生成三种运行方式。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--existing", type=Path, help="复用指定输出目录内的 fan_cfd.geo")
    options = parser.parse_args()
    destination = options.existing or prepare()
    if not options.prepare_only:
        run_mesher(destination.resolve())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)

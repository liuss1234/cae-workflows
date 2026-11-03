# -*- coding: utf-8 -*-
"""安装自检适配器：毫米 CAD、米制矩形管网格，可切换任意数量串联共形区。"""
from pathlib import Path
import argparse
import sys
import traceback

# 工况和尺寸统一从案例配置读取；工具路径相对当前脚本，无机器绝对路径。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from cfd_common import context, add_build_paths, inside, write_json


def main():
    """生成有命名的 STEP/MSH 与区域清单，不自动配置物理接口或求解。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    args = parser.parse_args()
    root, cfg, env = context(args.case)
    add_build_paths(env)
    import gmsh
    geometry = cfg["geometry"]
    length, width, height = [float(geometry[k]) for k in ["length_m", "width_m", "height_m"]]
    count = int(geometry["segments"])
    if min(length, width, height) <= 0 or count < 1 or count != geometry["segments"]:
        raise ValueError("尺寸必须为正，segments 必须为正整数")
    cad = inside(root, "cad/model_mm.step")
    mesh = inside(root, cfg["files"]["mesh_msh"])
    regions_path = inside(root, cfg["files"]["regions"])
    if any(path.exists() for path in [cad, mesh, regions_path]):
        raise FileExistsError("已有 CAD、网格或区域清单；请用新案例目录")
    gmsh.initialize()
    try:
        gmsh.model.add(cfg["name"])
        # STEP 按常规 mm 几何导出；网格生成前真实缩放为 m。
        volumes = [(3, gmsh.model.occ.addBox(i * length * 1000 / count, 0, 0,
                                          length * 1000 / count, width * 1000, height * 1000)) for i in range(count)]
        if count > 1:
            gmsh.model.occ.fragment(volumes[:1], volumes[1:])
        gmsh.model.occ.synchronize()
        gmsh.write(str(cad))
        gmsh.model.occ.dilate(gmsh.model.getEntities(3), 0, 0, 0, 0.001, 0.001, 0.001)
        gmsh.model.occ.synchronize()
        volumes = sorted(gmsh.model.getEntities(3), key=lambda x: gmsh.model.occ.getCenterOfMass(*x)[0])
        if len(volumes) != count:
            raise ValueError("布尔后实体数量与预期不符")
        surface_owners = {}
        for i, volume in enumerate(volumes):
            for dim, surface in gmsh.model.getBoundary([volume], oriented=False):
                surface_owners.setdefault(surface, []).append(i)
        physical = {}

        def group(dimension, entities, name):
            """物理组使用稳定名称；后续不依赖 OCC 的临时面编号。"""
            index = gmsh.model.addPhysicalGroup(dimension, entities)
            gmsh.model.setPhysicalName(dimension, index, name)
            return name

        zones, interfaces = [], []
        for i, volume in enumerate(volumes):
            name = "fluid_main" if count == 1 else "fluid_%02d" % (i + 1)
            group(3, [volume[1]], name)
            patches = []
            walls = []
            for dim, surface in gmsh.model.getBoundary([volume], oriented=False):
                owners = surface_owners[surface]
                if len(owners) == 2:
                    other = next(j for j in owners if j != i)
                    shared = "if_%02d_%02d" % (min(i, other) + 1, max(i, other) + 1)
                    if shared not in physical:
                        group(2, [surface], shared)
                        physical[shared] = surface
                    patch_name = "interface_%02d_to_%02d" % (i + 1, other + 1)
                    patches.append({"name": patch_name, "physical_surface": shared, "role": "interface", "condition_class": "CBCInterfaceBoundary"})
                    if i < other:
                        interfaces.append({"a": patch_name, "b": "interface_%02d_to_%02d" % (other + 1, i + 1), "kind": "conformal"})
                    continue
                box = gmsh.model.getBoundingBox(dim, surface)
                if abs(box[0]) < 1e-6 and abs(box[3]) < 1e-6:
                    patch, role, condition = "inlet", "velocity_inlet", "CBCVeloInlet"
                elif abs(box[0] - length) < 1e-6 and abs(box[3] - length) < 1e-6:
                    patch, role, condition = "outlet", "pressure_outlet", "CBCPressOutlet"
                else:
                    walls.append(surface)
                    continue
                group(2, [surface], patch)
                patches.append({"name": patch, "physical_surface": patch, "role": role, "condition_class": condition})
            wall_name = "wall_duct" if count == 1 else "wall_duct_%02d" % (i + 1)
            group(2, walls, wall_name)
            patches.append({"name": wall_name, "physical_surface": wall_name, "role": "wall", "condition_class": "CBCWall"})
            zones.append({"name": name, "physical_volume": name, "kind": "fluid", "region": "fluid", "boundaries": patches,
                          "bbox_m": [[i * length / count, 0, 0], [(i + 1) * length / count, width, height]],
                          "cad_volume_m3": gmsh.model.occ.getMass(*volume)})
        size = float(cfg["mesh"]["size_m"])
        for key, value in {"General.NumThreads": cfg["mesh"]["threads"], "Mesh.MeshSizeMin": size,
                           "Mesh.MeshSizeMax": size, "Mesh.ElementOrder": 1, "Mesh.MshFileVersion": 2.2,
                           "Mesh.Binary": 0, "Mesh.Algorithm3D": 1}.items():
            gmsh.option.setNumber(key, value)
        gmsh.model.mesh.generate(3)
        gmsh.model.mesh.optimize("Netgen")
        gmsh.write(str(mesh))
        write_json(regions_path, {"units": "m", "zones": zones, "interfaces": interfaces})
        write_json(root / "checks/cad.json", {"valid_volume_count": len(volumes), "cad_units": "mm", "mesh_units": "m",
                   "expected_volume_m3": length * width * height, "volume_m3": sum(z["cad_volume_m3"] for z in zones),
                   "geometry_source": "analytic demonstration", "cleanup_operations": []})
        print("GEOMETRY_MESH_COMPLETE", len(zones))
    finally:
        gmsh.finalize()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)

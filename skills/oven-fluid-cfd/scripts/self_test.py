# -*- coding: utf-8 -*-
"""在临时目录用合成输入验证工程逻辑；不运行CAD、STAR、QFlux或SSH。"""
import argparse
import json
import math
import tempfile
from pathlib import Path
from analyze_outlets import analyze, read_table, write_report
from cad_audit import normalized_metrics
from cfd_common import read_json, sha256
from oven_case import authorize_mesh, boundary_map, initialize, validate_case
from render_star_macro import render

# 以下参数与边界均为独立人工测试输入，不代表产品结构、尺寸或性能。
DENSITY = 1.2
WINDOW = 4
TEST_BOUNDARIES = (
    ("inlet_test", "velocity_inlet"),
    ("outlet_test_a", "pressure_outlet"),
    ("outlet_test_b", "pressure_outlet"),
    ("wall_test", "wall"),
)
TEST_MESH_LENGTHS = {
    "base_size_m": .04,
    "plenum_surface_size_m": .012,
    "slot_core_size_m": .005,
    "other_wall_total_thickness_m": .0008,
    "minimum_surface_size_m": .0007,
    "guide_minimum_surface_size_m": .00035,
}


def must_fail(function, *args):
    """要求失败分支确实拒绝输入，避免只检查返回字符串。"""
    try:
        function(*args)
    except (ValueError, FileExistsError, FileNotFoundError):
        return
    raise AssertionError("应拒绝此输入")


def complete_configuration(case):
    """显式填写人工测试工况；这些值不填回发布模板。"""
    cfg = read_json(case / "case.json")
    manifest = read_json(case / "regions.json")
    manifest["zones"][0]["boundaries"] = [{"name": name, "role": role} for name, role in TEST_BOUNDARIES]
    (case / "regions.json").write_text(json.dumps(manifest), encoding="utf-8")
    outlet_count = sum(role == "pressure_outlet" for _, role in TEST_BOUNDARIES)
    cfg["workflow"].update(scope_confirmed=True, geometry_units_confirmed=True,
                           assumptions_confirmed=True, outlet_count=outlet_count)
    cfg["geometry"].update(length_units="mm", return_air_included=False)
    cfg["physics"].update(temperature_K=293.15, temperature_source="synthetic test only",
                          reference_pressure_Pa=101325, inlet_speed_m_s=10,
                          inlet_direction="inward_boundary_normal", outlet_gauge_pressure_Pa=0,
                          turbulence_intensity_percent=5, turbulence_viscosity_ratio=10,
                          initial_k_m2_s2=.00375, initial_epsilon_m2_s3=.00835)
    cfg["physics"]["material"].update(Density=DENSITY, Viscosity=1.8e-5, SpecialHeat=1006, ThermalConduct=.026)
    cfg["solver"].update(cores=2, max_iterations=100, save_interval=20)
    cfg["mesh"].update(TEST_MESH_LENGTHS)
    cfg["mesh"]["wall_layer_spec"] = {
        name: {"layers": 2, "total_thickness_m": .0008, "surface_size_m": .012}
        for name, role in TEST_BOUNDARIES if role == "wall"
    }
    cfg["mesh"]["exchange_surface_method"] = "synthetic_test_only"
    cfg["validation"].update(bbox_tolerance_m=2e-6, cad_bbox_tolerance_m=.0008,
                             cad_bbox_tolerance_basis="synthetic test only")
    cfg["mesh"]["slot_boxes_m"] = [{"name": "synthetic_slot", "low": [0, 0, 0], "high": [.01, .01, .01]}]
    (case / "case.json").write_text(json.dumps(cfg), encoding="utf-8")
    return cfg


def fixture(stage, manifest, density=DENSITY):
    """根据人工清单构造等流出口，覆盖共用迭代与不完整尾行。"""
    folder = stage / "dat"
    folder.mkdir(parents=True)
    paths = {}
    patches = boundary_map(manifest)
    outlet_count = list(patches.values()).count("pressure_outlet")
    for name, role in patches.items():
        if role == "wall":
            continue
        value = -density if role == "velocity_inlet" else density / outlet_count
        path = folder / ("air-mass_" + name + ".dat")
        path.write_text("#iter value\n" + "".join("{} {:.16g}\n".format(i, value) for i in range(1, 7)), encoding="utf-8")
        paths[name] = path
    # 只有一个出口提前写到7步，入口末行8步不完整，统计仍应取3–6。
    first = paths["outlet_test_a"]
    with first.open("a", encoding="utf-8") as stream:
        stream.write("7 {:.16g}\n".format(density / outlet_count))
    with paths["inlet_test"].open("a", encoding="utf-8") as stream:
        stream.write("8 -1")
    return paths


def replace_sample(text, iteration, value):
    """按迭代编号修改或删除合成记录，不依赖具体流量文本。"""
    lines = text.splitlines()
    target = next(i for i, line in enumerate(lines) if line.startswith(str(iteration) + " "))
    if value is None:
        del lines[target]
    else:
        lines[target] = "{} {}".format(iteration, value)
    return "\n".join(lines) + "\n"


def main():
    """验证可观察行为、错误路径、来源追溯和不覆盖原件。"""
    argparse.ArgumentParser(description=__doc__).parse_args()
    passed = []
    with tempfile.TemporaryDirectory(prefix="oven-synthetic-") as temp:
        root = Path(temp)
        case = root / "case"
        initialize(case)
        empty = read_json(case / "case.json")
        assert empty["workflow"]["outlet_count"] is None and not empty["mesh"]["wall_layer_spec"]
        assert all(empty["mesh"][key] is None for key in TEST_MESH_LENGTHS)
        assert not read_json(case / "regions.json")["zones"][0]["boundaries"]
        before = sha256(case / "case.json")
        must_fail(initialize, case)
        assert sha256(case / "case.json") == before
        must_fail(validate_case, case)
        cfg = complete_configuration(case)
        _, manifest = validate_case(case)
        passed.append("初始化拒绝覆盖；未填工况拒绝；完整命名和物性准入")
        scaled = normalized_metrics([[0, 0, 0], [1000, 2000, 3000]], 6e9, "mm")
        assert scaled["bbox_m"][1] == [1, 2, 3] and math.isclose(scaled["volume_m3"], 6)
        passed.append("mm到m的长度和体积立方缩放")
        mesh = {"passed": False, "cgns_sha256": "a" * 64}
        must_fail(authorize_mesh, case, cfg, mesh)
        cfg["workflow"]["diagnostic_authorization_file"] = "checks/auth.json"
        auth = case / "checks/auth.json"
        auth.write_text(json.dumps({"authorized": True, "reason": "synthetic test", "mesh_sha256": "b" * 64}), encoding="utf-8")
        must_fail(authorize_mesh, case, cfg, mesh)
        auth.write_text(json.dumps({"authorized": True, "reason": "synthetic test", "mesh_sha256": "a" * 64}), encoding="utf-8")
        authorize_mesh(case, cfg, mesh)
        assert mesh["passed"] is False
        passed.append("诊断授权绑定哈希且不改网格失败结论")
        surface = root / "synthetic_names_only.stl"
        surface.write_text("".join("solid {}\nendsolid {}\n".format(n, n) for n in boundary_map(manifest)), encoding="utf-8")
        macro = render(case, surface)
        assert "@SURFACE_CONTROLS@" not in macro and "NOZZLE_X" not in macro
        cfg = read_json(case / "case.json")
        cfg["mesh"]["prism_gap_fill_percent"] = 50
        (case / "case.json").write_text(json.dumps(cfg), encoding="utf-8")
        must_fail(render, case, surface)
        cfg["mesh"]["prism_gap_fill_percent"] = 40
        cfg["mesh"]["slot_boxes_m"] = []
        (case / "case.json").write_text(json.dumps(cfg), encoding="utf-8")
        must_fail(render, case, surface)
        passed.append("宏命名与参数渲染；50%填隙和空局部盒拒绝；未运行STAR")
        stage = root / "stage"
        paths = fixture(stage, manifest)
        result = analyze(stage, manifest, "air", DENSITY, WINDOW)
        assert (result["window_start"], result["window_end"], result["samples"]) == (3, 6, 4)
        assert result["monitor_checks_passed"] and math.isclose(result["outlets_total_mean_m3_h"], 3600)
        assert result["cv_percent"] < 1e-10 and result["maximum_step_mass_balance_error_percent"] < 1e-10
        write_report(result, root / "report")
        must_fail(write_report, result, root / "report")
        assert (root / "report/outlets.csv").is_file()
        passed.append("全部开口共同迭代、单位流量、窗口均值和报告拒绝覆盖")
        target = paths["outlet_test_b"]
        saved = target.read_text(encoding="utf-8")
        target.write_text(replace_sample(saved, 4, None), encoding="utf-8")
        incomplete = analyze(stage, manifest, "air", DENSITY, WINDOW)
        assert not incomplete["complete_window"] and not incomplete["monitor_checks_passed"]
        target.write_text(replace_sample(saved, 5, "NaN"), encoding="utf-8")
        must_fail(analyze, stage, manifest, "air", DENSITY, WINDOW)
        target.write_text(replace_sample(saved, 5, "Inf"), encoding="utf-8")
        must_fail(analyze, stage, manifest, "air", DENSITY, WINDOW)
        target.write_text(replace_sample(saved, 5, -DENSITY), encoding="utf-8")
        backflow = analyze(stage, manifest, "air", DENSITY, WINDOW)
        assert not backflow["direction_passed"] and "outlet_test_b" in backflow["outlets_with_backflow"]
        target.unlink()
        must_fail(analyze, stage, manifest, "air", DENSITY, WINDOW)
        must_fail(analyze, stage, manifest, "air", 0, WINDOW)
        passed.append("缺步、NaN、反向出口、缺文件和无效密度的失败路径")
        conflict = root / "conflict.dat"
        conflict.write_text("#iter value\n1 1\n1 2\n", encoding="utf-8")
        must_fail(read_table, conflict)
        for path in paths.values():
            path.write_text("#iter value\n" + "".join("{} 0\n".format(i) for i in range(1, 7)), encoding="utf-8")
        zero = analyze(stage, manifest, "air", DENSITY, WINDOW)
        assert zero["cv_percent"] is None and not zero["direction_passed"]
        assert not zero["monitor_checks_passed"]
        # 真实公开数值摘要与工具的合成自检分开，避免测试伪造产品结果。
        assert result["scope"].startswith("仅监控诊断")
    print(json.dumps({"synthetic_only": True, "passed": True, "checks": passed,
                      "not_run": ["FreeCAD内核", "STAR编译/网格", "QFlux原生API", "Slurm", "真实物理求解"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

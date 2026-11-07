# -*- coding: utf-8 -*-
"""初始化烘箱案例、核对工况与命名；不自动建模、划网格或提交计算。"""
import argparse
import json
import math
import re
import shutil
import sys
from pathlib import Path
from cfd_common import inside, read_json, sha256

# 可调工程参数放在案例case.json；模板的几何相关参数按当前项目填写。
SKILL_ROOT = Path(__file__).resolve().parents[1]
NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def positive(value, label, zero=False):
    """拒绝空值、布尔值、非有限数及错误符号，避免生成貌似可用的工况。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + "必须填写有限数值")
    if (value < 0 if zero else value <= 0):
        raise ValueError(label + "超出允许范围")
    return value


def boundary_map(manifest):
    """单流体无接口模型的边界命名不得重复或为空。"""
    zones = manifest.get("zones", [])
    if len(zones) != 1 or zones[0].get("kind") != "fluid" or manifest.get("interfaces"):
        raise ValueError("当前工具仅支持单流体无接口烘箱供风域")
    zone = zones[0]
    for key in ("name", "region"):
        if not NAME_PATTERN.fullmatch(zone.get(key, "")):
            raise ValueError("网格区/计算域名称无效")
    result = {}
    for patch in zone.get("boundaries", []):
        name, role = patch.get("name", ""), patch.get("role")
        if not NAME_PATTERN.fullmatch(name) or name in result:
            raise ValueError("边界名称为空、重复或含不支持的字符：" + name)
        if role not in ("velocity_inlet", "pressure_outlet", "wall"):
            raise ValueError("不支持的边界角色：" + str(role))
        result[name] = role
    if not result:
        raise ValueError("边界清单为空")
    return result


def validate_case(root):
    """核对人工确认及物理参数；不将通过解释为几何、网格或求解验收。"""
    root = Path(root).resolve()
    cfg = read_json(root / "case.json")
    workflow = cfg["workflow"]
    for key in ("scope_confirmed", "geometry_units_confirmed", "assumptions_confirmed"):
        if workflow.get(key) is not True:
            raise ValueError("必须按当前项目确认workflow." + key)
    if cfg["geometry"]["length_units"] not in ("mm", "m"):
        raise ValueError("geometry.length_units需明确mm或m")
    if not isinstance(cfg["geometry"].get("return_air_included"), bool):
        raise ValueError("需明确是否包括回风区")
    if cfg["geometry"]["return_air_included"]:
        raise ValueError("当前供风适配器不自动扩展回风全域")
    for value in cfg["files"].values():
        inside(root, value)
    physics = cfg["physics"]
    if physics.get("energy") is not False or physics.get("gravity") is not False:
        raise ValueError("当前自动适配限无重力等温供风")
    if (physics.get("turbulence"), physics.get("turbulence_subtype")) != ("KE", "Realizable"):
        raise ValueError("当前适配器仅写Realizable k-epsilon")
    if physics.get("wall_treatment") != "two_layer_all_yplus":
        raise ValueError("当前适配器只写双层近壁处理")
    for key in ("temperature_K", "reference_pressure_Pa", "inlet_speed_m_s", "turbulence_intensity_percent",
                "turbulence_viscosity_ratio", "initial_k_m2_s2", "initial_epsilon_m2_s3"):
        positive(physics.get(key), "physics." + key)
    pressure = physics.get("outlet_gauge_pressure_Pa")
    if isinstance(pressure, bool) or not isinstance(pressure, (int, float)) or not math.isfinite(pressure):
        raise ValueError("出口表压需为有限数值，可为0")
    if not physics.get("inlet_direction") or not physics.get("temperature_source"):
        raise ValueError("入口方向与温度依据需记录")
    if physics.get("inlet_direction") != "inward_boundary_normal":
        raise ValueError("当前QFlux入口只支持内法向；其他方向需另写适配器")
    for key in ("Density", "Viscosity", "SpecialHeat", "ThermalConduct"):
        positive(physics["material"].get(key), "material." + key)
    for key in ("cores", "max_iterations", "save_interval"):
        value = cfg["solver"].get(key)
        positive(value, "solver." + key)
        if not isinstance(value, int):
            raise ValueError("迭代数/核数必须为整数")
    positive(cfg["solver"].get("residual_limit"), "residual_limit")
    manifest = read_json(inside(root, cfg["files"]["regions"]))
    patches = boundary_map(manifest)
    n = workflow["outlet_count"]
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError("outlet_count必须为正整数")
    if list(patches.values()).count("velocity_inlet") != 1 or list(patches.values()).count("pressure_outlet") != n:
        raise ValueError("入口/出口数与供风范围不一致")
    walls = {name for name, role in patches.items() if role == "wall"}
    if not walls or walls != set(cfg["mesh"]["wall_layer_spec"]):
        raise ValueError("所有壁面需各有一组层参数且无多余组")
    for name, spec in cfg["mesh"]["wall_layer_spec"].items():
        if not isinstance(spec["layers"], int) or isinstance(spec["layers"], bool) or spec["layers"] < 1:
            raise ValueError("壁面请求层数无效：" + name)
        positive(spec["total_thickness_m"], name + ".total_thickness_m")
        positive(spec["surface_size_m"], name + ".surface_size_m")
    return cfg, manifest


def authorize_mesh(root, cfg, mesh):
    """诊断授权只允许同一哈希失败网格继续设置，不改变质量passed。"""
    if mesh.get("passed") is True:
        return
    target = cfg["workflow"].get("diagnostic_authorization_file")
    if not target:
        raise ValueError("网格未通过；只有当前用户明确诊断授权才可设置")
    authorization = read_json(inside(root, target))
    if (authorization.get("authorized") is not True or not authorization.get("reason")
            or authorization.get("mesh_sha256") != mesh.get("cgns_sha256")
            or not mesh.get("cgns_sha256")):
        raise ValueError("诊断授权缺失、范围不明或网格哈希不匹配")


def initialize(output):
    """创建可移走的案例；只复制工具和配置，不访问原CAD或远端。"""
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("案例目录已存在：" + str(output))
    required = [SKILL_ROOT / "assets" / name for name in
                ("case.template.json", "regions.template.json", "environment.example.json")]
    if not all(path.is_file() for path in required):
        raise FileNotFoundError("请从完整技能目录运行init")
    output.mkdir(parents=True)
    for folder in ("cad", "mesh", "checks", "runs", "post", "tools", "assets"):
        (output / folder).mkdir()
    for source, name in zip(required, ("case.json", "regions.json", "environment.json")):
        shutil.copy2(source, output / name)
    for path in (SKILL_ROOT / "scripts").glob("*.py"):
        shutil.copy2(path, output / "tools" / path.name)
    shutil.copy2(SKILL_ROOT / "assets/MeshOven.java.in", output / "assets/MeshOven.java.in")
    return {"initialized": True, "scope": "未填写工况的新供风案例", "case_files": 3,
            "template_sha256": sha256(required[0])}


def main():
    """命令只产生新案例或只读核对，不触发商业软件和SSH。"""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("init").add_argument("--output", required=True)
    sub.add_parser("validate").add_argument("--case", required=True)
    args = parser.parse_args()
    if args.action == "init":
        result = initialize(args.output)
    else:
        _, manifest = validate_case(args.case)
        result = {"configuration_passed": True, "boundaries": len(boundary_map(manifest)),
                  "scope": "参数及命名；未审计几何网格和物理精度"}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("案例操作失败：" + str(error), file=sys.stderr)
        sys.exit(1)

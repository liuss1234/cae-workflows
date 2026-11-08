# -*- coding: utf-8 -*-
"""渲染已实测STAR 18.06 API的烘箱网格模板；本工具不启动STAR。"""
import argparse
import json
import math
import re
import sys
from pathlib import Path
from cfd_common import read_json, sha256
from oven_case import boundary_map, positive

# Java类名与文件名须一致；目标软件版本和编码由实际环境核对。
CLASS_NAME = "MeshOven"
TEMPLATE = Path(__file__).resolve().parents[1] / "assets/MeshOven.java.in"


def literal(value):
    """生成合法Java字符串；路径统一斜线，不把路径内容当成代码拼接。"""
    return json.dumps(str(value).replace("\\", "/"), ensure_ascii=True)


def number(value, name, zero=False):
    """所有长度都为m；拒绝NaN、Inf和负尺寸。"""
    return repr(float(positive(value, name, zero=zero)))


def surface_names(path):
    """逐行只检查命名ASCII STL的solid/endsolid；拓扑仍需独立几何审计。"""
    names, ended = [], []
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line in stream:
            line = line.strip()
            if line.startswith("solid "):
                names.append(line[6:].strip())
            elif line.startswith("endsolid "):
                ended.append(line[9:].strip())
    if not names or names != ended or len(names) != len(set(names)):
        raise ValueError("需要非重复、闭合段落的命名ASCII STL；不接受未分组二进制输入")
    return set(names)


def render(root, surface):
    """按清单逐面生成控制，未登记边界报错；局部加密盒必须由当前几何给定。"""
    root, surface = Path(root).resolve(), Path(surface).resolve()
    cfg = read_json(root / "case.json")
    manifest = read_json(root / cfg["files"]["regions"])
    patches = boundary_map(manifest)
    if manifest["zones"][0]["name"] != "fluid_supply":
        raise ValueError("当前STAR/CGNS适配约定网格区名fluid_supply")
    if surface_names(surface) != set(patches):
        raise ValueError("STL命名集合与regions.json不一致")
    mesh = cfg["mesh"]
    if mesh.get("input_units") != "m":
        raise ValueError("须先实际缩放并确认交换表面坐标为m")
    version = mesh["version"]
    if not re.fullmatch(r"[A-Za-z0-9_]+", version):
        raise ValueError("版本名含不支持的字符")
    walls = {name for name, role in patches.items() if role == "wall"}
    if walls != set(mesh["wall_layer_spec"]):
        raise ValueError("壁面层控制不完整")
    gap_fill = positive(mesh["prism_gap_fill_percent"], "gap fill", zero=True)
    if gap_fill >= 50:
        raise ValueError("此STAR版本gap fill必须严格小于50%")
    controls = []
    for index, (name, role) in enumerate(patches.items()):
        if role == "wall":
            spec = mesh["wall_layer_spec"][name]
            layers = spec["layers"]
            if not isinstance(layers, int) or isinstance(layers, bool) or layers < 1:
                raise ValueError("壁面层数必须为正整数")
            size = number(spec["surface_size_m"], name + " size")
            thick = number(spec["total_thickness_m"], name + " thickness")
        else:
            layers, thick = 0, "0.0"
            size = number(mesh["slot_core_size_m"] if role == "pressure_outlet" else mesh["plenum_surface_size_m"], name + " size")
        guide = name == "wall_plenum_guides"
        minimum = number(mesh["guide_minimum_surface_size_m"] if guide else mesh["minimum_surface_size_m"], "minimum size")
        if float(minimum) > float(size):
            raise ValueError("最小表面尺寸大于目标尺寸：" + name)
        controls.append("        %s(name.equals(%s))surface(op,list,name,%s,%d,%s,%s,%s);" % (
            "if" if index == 0 else "else if", literal(name), size, layers, thick, minimum, str(guide).lower()))
    controls.append('        else throw new RuntimeException("Unregistered patch "+name);')
    boxes = mesh.get("slot_boxes_m", [])
    if mesh.get("slot_boxes_required", True) and not boxes:
        raise ValueError("缺少基于当前风嘴位置的slot_boxes_m，不能使用旧坐标")
    volumes, names = [], set()
    for box in boxes:
        low, high, name = box["low"], box["high"], box["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) or name in names:
            raise ValueError("局部盒名称重复或无效")
        names.add(name)
        if len(low) != 3 or len(high) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in low + high):
            raise ValueError("局部盒坐标须为3个有限数")
        if any(a >= b for a, b in zip(low, high)):
            raise ValueError("局部盒必须有正体积")
        volumes.append('      volume(op,%s,new double[]{%s},new double[]{%s},GAP_CORE);' % (
            literal(name), ",".join(repr(float(v)) for v in low), ",".join(repr(float(v)) for v in high)))
    substitutions = {
        "ROOT": literal(root), "SURFACE": literal(surface), "VERSION": version,
        "BASE": number(mesh["base_size_m"], "base"),
        "PLENUM_SURFACE": number(mesh["plenum_surface_size_m"], "plenum surface"),
        "PLENUM_PRISM": number(mesh["other_wall_total_thickness_m"], "plenum prism"),
        "GAP_CORE": number(mesh["slot_core_size_m"], "slot core"),
        "GAP_FILL": repr(float(gap_fill)), "MIN_PRISM": number(mesh["minimum_prism_thickness_percent"], "minimum prism"),
        "REDUCTION": number(mesh["prism_layer_reduction_percent"], "reduction", zero=True),
        "NEAR_CORE": number(mesh["near_core_layer_aspect_ratio"], "near core", zero=True),
        "GROWTH": number(mesh["prism_growth"], "growth"), "PROXIMITY_POINTS": number(mesh["guide_proximity_points_in_gap"], "guide proximity points"),
        "PATCH_NAMES": ",".join(literal(name) for name in patches),
        "SURFACE_CONTROLS": "\n".join(controls), "SLOT_CONTROLS": "\n".join(volumes)}
    source = TEMPLATE.read_text(encoding="utf-8")
    required = set(re.findall(r"@([A-Z_]+)@", source))
    if required != set(substitutions):
        raise ValueError("模板参数清单漂移：" + str(required.symmetric_difference(substitutions)))
    # 单次替换，不对路径或名称中出现的字符作二次求值。
    return re.sub(r"@([A-Z_]+)@", lambda match: substitutions[match.group(1)], source)


def main():
    """生成新宏与来源收据；已有输出不覆盖，不在目标机器执行。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--surface", type=Path, help="已命名米制ASCII STL，默认案例mesh/named_m.stl")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--encoding", choices=("utf-8", "gb18030"), default="utf-8")
    args = parser.parse_args()
    if args.output.name != CLASS_NAME + ".java":
        raise ValueError("输出文件名必须为MeshOven.java")
    receipt = args.output.with_suffix(".render.json")
    if args.output.exists() or receipt.exists():
        raise FileExistsError("宏或渲染收据已存在")
    surface = args.surface or args.case / "mesh/named_m.stl"
    source = render(args.case, surface)
    payload = source.encode(args.encoding)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(payload)
    record = {"case_sha256": sha256(args.case / "case.json"), "surface_sha256": sha256(surface),
              "macro_sha256": sha256(args.output), "encoding": args.encoding,
              "scope": "仅参数渲染，未编译、未运行STAR、未生成网格"}
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("STAR宏渲染失败：" + str(error), file=sys.stderr)
        sys.exit(1)

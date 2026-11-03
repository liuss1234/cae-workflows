# -*- coding: utf-8 -*-
"""从官方 ASCII TET4 VTU 绘制真实平面切片；不使用示意或跨实体外插场。"""
from pathlib import Path
import argparse
import sys
import traceback
import xml.etree.ElementTree as ET
from cfd_common import context, add_build_paths, inside, read_json, write_json, sha256

# 切片位置、方向、变量、颜色范围均由命令行指定，网格数据不硬编码。
AXES = {"x": 0, "y": 1, "z": 2}
EDGES = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]


def read_piece(path, field):
    """读取已验证的一阶四面体，明确拒绝未支持的编码、混合网格和多 piece。"""
    import numpy as np
    tree = ET.parse(path)
    pieces = tree.findall(".//Piece")
    if len(pieces) != 1:
        raise ValueError("本绘图器仅处理单 Piece VTU，请为该导出编写适配器")
    piece = pieces[0]

    def array(element, dtype=float):
        """不猜测压缩或 appended 编码，避免错误解析后生成假云图。"""
        if element is None or element.get("format", "ascii").lower() != "ascii":
            raise ValueError("仅支持官方 ASCII DataArray")
        return np.fromstring(element.text or "", sep=" ", dtype=dtype)

    coords = array(piece.find("Points/DataArray")).reshape(-1, 3)
    cells = piece.find("Cells")
    connectivity = array(cells.find("DataArray[@Name='connectivity']"), np.int64)
    offsets = array(cells.find("DataArray[@Name='offsets']"), np.int64)
    types = array(cells.find("DataArray[@Name='types']"), np.int64)
    if not len(types) or not np.all(types == 10) or not np.array_equal(offsets, np.arange(1, len(types) + 1) * 4):
        raise ValueError("本切片器只支持纯 TET4，不丢弃其他单元")
    tetra = connectivity.reshape(-1, 4)
    if tetra.min() < 0 or tetra.max() >= len(coords) or len(coords) != int(piece.get("NumberOfPoints")) or len(tetra) != int(piece.get("NumberOfCells")):
        raise ValueError("VTU 连接或数量无效")
    matches = []
    available = []
    for parent, count, association in [("PointData", len(coords), "point"), ("CellData", len(tetra), "cell")]:
        for element in piece.findall(parent + "/DataArray"):
            available.append(parent + ":" + element.get("Name", ""))
            if element.get("Name") == field:
                if int(element.get("NumberOfComponents", 1)) != 1:
                    raise ValueError("请选择标量或显式编写向量分量适配器")
                values = array(element)
                if len(values) != count or not np.all(np.isfinite(values)):
                    raise ValueError("场变量长度错误或非有限")
                matches.append((association, values))
    # 同时有节点和单元值时优先节点插值，并在记录中写明，不能混用两种顺序。
    if not matches:
        raise ValueError("找不到场变量 %s；实际变量 %s" % (field, available))
    if not np.all(np.isfinite(coords)):
        raise ValueError("坐标非有限")
    return coords, tetra, matches[0][0], matches[0][1]


def cut_plane(coords, tetra, association, values, axis, position):
    """逐四面体求交，节点场线性插值、单元场分片常值，保持流体空洞。"""
    import numpy as np
    remaining = [i for i in range(3) if i != axis]
    epsilon = max(float(np.ptp(coords, axis=0).max()) * 1e-10, 1e-14)
    vertices, colors, triangles = [], [], []
    for index, tet in enumerate(tetra):
        points = coords[tet]
        distances = points[:, axis] - position
        if distances.min() > epsilon or distances.max() < -epsilon:
            continue
        hits = {}
        for a, b in EDGES:
            if abs(distances[a]) <= epsilon:
                t = 0.0
            elif abs(distances[b]) <= epsilon:
                t = 1.0
            elif distances[a] * distances[b] < 0:
                t = distances[a] / (distances[a] - distances[b])
            else:
                continue
            p = points[a] + t * (points[b] - points[a])
            value = values[tet[a]] * (1 - t) + values[tet[b]] * t if association == "point" else values[index]
            hits[tuple(np.round(p / epsilon).astype(np.int64))] = (p[remaining], float(value))
        if len(hits) < 3:
            continue
        polygon = list(hits.values())
        center = np.mean([p for p, _ in polygon], axis=0)
        polygon.sort(key=lambda item: np.arctan2(item[0][1] - center[1], item[0][0] - center[0]))
        start = len(vertices)
        vertices.extend(p for p, _ in polygon)
        colors.extend(v for _, v in polygon)
        for i in range(1, len(polygon) - 1):
            a, b, c = [polygon[j][0] for j in [0, i, i + 1]]
            if abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) > epsilon ** 2:
                triangles.append([start, start + i, start + i + 1])
    if not triangles:
        raise ValueError("指定平面没有有效单元截面")
    return np.asarray(vertices), np.asarray(triangles), np.asarray(colors), remaining


def main():
    """要求官方导出来源校验，图旁保存同名 JSON 便于报告追溯。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--stage", default="baseline")
    parser.add_argument("--vtu", required=True, help="案例内实际 VTU 路径，可位于 VTM 子目录")
    parser.add_argument("--source-check", help="官方导出检查文件，默认 post/<stage>/check.json")
    parser.add_argument("--field", required=True, help="VTU 中实际 DataArray 名称")
    parser.add_argument("--unit", required=True, help="色标单位，例如 Pa 或 m/s")
    parser.add_argument("--axis", choices=list(AXES), required=True)
    parser.add_argument("--position", type=float, required=True, help="切片位置 m")
    parser.add_argument("--output", required=True, help="案例内新 PNG 文件")
    args = parser.parse_args()
    root, cfg, env = context(args.case)
    add_build_paths(env)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.tri as mtri
    vtu = inside(root, args.vtu)
    check = read_json(inside(root, args.source_check or ("post/" + args.stage + "/check.json")))
    records = {item["path"].replace("\\", "/"): item["sha256"] for item in check.get("exported_vtu", [])}
    relative = vtu.relative_to(root).as_posix()
    if not check.get("passed") or records.get(relative) != sha256(vtu):
        raise ValueError("VTU 不在成功官方导出记录中或内容已变更")
    output = inside(root, args.output)
    if output.exists() or output.with_suffix(".json").exists():
        raise FileExistsError(output)
    coords, tetra, association, values = read_piece(vtu, args.field)
    xy, triangles, color, remaining = cut_plane(coords, tetra, association, values, AXES[args.axis], args.position)
    fig, ax = plt.subplots(figsize=(10, 4.5), constrained_layout=True)
    image = ax.tripcolor(mtri.Triangulation(xy[:, 0], xy[:, 1], triangles), color,
                         shading="gouraud" if association == "point" else "flat", cmap="viridis")
    fig.colorbar(image, ax=ax, label=args.field + " [" + args.unit + "]")
    labels = "xyz"
    ax.set(xlabel=labels[remaining[0]] + " [m]", ylabel=labels[remaining[1]] + " [m]",
           title="%s, %s = %g m (%s data)" % (args.field, args.axis, args.position, association))
    ax.set_aspect("equal")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200)
    plt.close(fig)
    write_json(output.with_suffix(".json"), {"source_vtu": relative, "vtu_sha256": sha256(vtu), "source_qfx_sha256": check["source_sha256"],
               "source_data_sha256": check["source_data_sha256"], "field": args.field, "association": association,
               "axis": args.axis, "position_m": args.position, "slice_triangles": len(triangles),
               "slice_min": float(color.min()), "slice_max": float(color.max()), "unit": args.unit})
    print("TRUE_PLANE_SLICE_COMPLETE", str(output))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)

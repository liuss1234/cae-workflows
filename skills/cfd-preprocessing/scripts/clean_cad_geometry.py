#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""使用 Gmsh OCC 内核执行可重复的 CAD 几何基础清理。

支持 STEP、IGES/IGS 和 BREP。脚本只做拓扑修复、重复实体清理和合法性报告，
不会根据尺寸擅自删除孔、圆角或薄壁特征；这类简化应由工程师明确指定。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# ===== 可调参数（命令行参数优先） =====
DEFAULT_TOLERANCE = 1.0e-8       # OCC 修复容差，单位与 CAD 文件一致
DEFAULT_FIX_SMALL_EDGES = True   # 尝试修复小边，不等于删除物理特征
DEFAULT_FIX_SMALL_FACES = True   # 尝试修复小面
DEFAULT_SEW_FACES = True         # 缝合相邻面
DEFAULT_MAKE_SOLIDS = True       # 尝试将闭合壳构造成实体


def load_gmsh() -> Any:
    """导入 Gmsh Python API；缺少依赖时给出明确安装命令。"""
    try:
        import gmsh  # type: ignore
        return gmsh
    except ImportError as exc:
        raise RuntimeError(
            "未找到 gmsh Python 包。请执行：python -m pip install gmsh"
        ) from exc


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="清理并检查 STEP/IGES/BREP 几何")
    parser.add_argument("input", type=Path, help="输入 CAD 文件")
    parser.add_argument("-o", "--output", type=Path, help="输出文件，建议使用 .step 或 .brep")
    parser.add_argument(
        "--tolerance", type=float, default=DEFAULT_TOLERANCE,
        help=f"OCC 修复容差，默认 {DEFAULT_TOLERANCE:g}"
    )
    parser.add_argument("--no-small-edge-fix", action="store_true", help="关闭小边修复")
    parser.add_argument("--no-small-face-fix", action="store_true", help="关闭小面修复")
    parser.add_argument("--no-sew", action="store_true", help="关闭相邻面缝合")
    parser.add_argument("--no-make-solids", action="store_true", help="关闭实体构造")
    parser.add_argument("--force", action="store_true", help="允许覆盖已存在的输出文件")
    parser.add_argument("--report", type=Path, help="JSON 检查报告路径")
    return parser.parse_args()


def entity_summary(gmsh: Any) -> dict[str, int]:
    """统计当前模型中点、线、面、实体的数量。"""
    return {
        str(dim): len(gmsh.model.getEntities(dim))
        for dim in range(4)
    }


def bounding_box(gmsh: Any) -> list[float] | None:
    """返回模型包围盒；没有几何实体时返回 None。"""
    entities = gmsh.model.getEntities()
    if not entities:
        return None
    boxes = [gmsh.model.getBoundingBox(dim, tag) for dim, tag in entities]
    return [
        min(box[0] for box in boxes), min(box[1] for box in boxes), min(box[2] for box in boxes),
        max(box[3] for box in boxes), max(box[4] for box in boxes), max(box[5] for box in boxes),
    ]


def clean_geometry(gmsh: Any, args: argparse.Namespace) -> dict[str, Any]:
    """导入、修复、同步并检查几何，返回可序列化报告。"""
    input_path = args.input.resolve()
    gmsh.model.add(input_path.stem)
    imported = gmsh.model.occ.importShapes(str(input_path), highestDimOnly=False)
    gmsh.model.occ.synchronize()
    before = entity_summary(gmsh)
    before_box = bounding_box(gmsh)

    # OCC 修复接口可能因 Gmsh 版本返回不同内容，因此只依赖其副作用。
    gmsh.model.occ.healShapes(
        imported,
        args.tolerance,
        True,
        not args.no_small_edge_fix,
        not args.no_small_face_fix,
        not args.no_sew,
        not args.no_make_solids,
    )
    gmsh.model.occ.removeAllDuplicates()
    gmsh.model.occ.synchronize()

    after = entity_summary(gmsh)
    after_box = bounding_box(gmsh)
    highest_dim = max((dim for dim, count in after.items() if count), default="-1")
    return {
        "input": str(input_path),
        "tolerance": args.tolerance,
        "options": {
            "fix_small_edges": not args.no_small_edge_fix,
            "fix_small_faces": not args.no_small_face_fix,
            "sew_faces": not args.no_sew,
            "make_solids": not args.no_make_solids,
        },
        "entities_before": before,
        "entities_after": after,
        "highest_dimension": highest_dim,
        "bounding_box_before": before_box,
        "bounding_box_after": after_box,
        "warnings": [
            "几何清理不等于物理特征简化；请人工确认孔、间隙、圆角和薄壁是否应保留。",
            "输出几何仍需在目标前处理器中检查封闭性、连通性、单位和流体域。",
        ],
    }


def main() -> int:
    """程序入口，负责参数校验、异常捕获和输出。"""
    args = parse_args()
    try:
        if not args.input.is_file():
            raise FileNotFoundError(f"输入文件不存在：{args.input}")
        if args.tolerance <= 0:
            raise ValueError("--tolerance 必须为正数")
        if args.output is None:
            args.output = args.input.with_name(f"{args.input.stem}_cleaned.step")
        args.output = args.output.resolve()
        if args.output == args.input.resolve():
            raise ValueError("输出文件不能覆盖输入文件，请使用新的输出路径")
        if args.output.exists() and not args.force:
            raise FileExistsError(f"输出文件已存在：{args.output}；如需覆盖请使用 --force")
        if args.report is None:
            args.report = args.output.with_suffix(".json")
        args.report = args.report.resolve()

        gmsh = load_gmsh()
        gmsh.initialize([sys.argv[0], "-no_popup"])
        gmsh.option.setNumber("General.Terminal", 0)
        try:
            report = clean_geometry(gmsh, args)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            gmsh.write(str(args.output))
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            gmsh.finalize()

        print(f"清理完成：{args.output}")
        print(f"检查报告：{args.report}")
        return 0
    except Exception as exc:  # noqa: BLE001 - 命令行工具需要把错误转成可读信息
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

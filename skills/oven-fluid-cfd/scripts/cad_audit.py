# -*- coding: utf-8 -*-
"""在FreeCAD兼容Python中只读回读STEP/BREP；单位指回读后内核坐标。"""
import argparse
import contextlib
import io
import json
import sys
from pathlib import Path
from cfd_common import sha256

# 转换因子只适用于已由已知尺寸确认的内核坐标，不猜STEP文本单位。
METRES_PER_COORDINATE = {"mm": 0.001, "m": 1.0}


def normalized_metrics(bbox, volume, units):
    """长度/体积同步缩放，防止mm网格只改标签未改坐标。"""
    factor = METRES_PER_COORDINATE[units]
    return {"bbox_m": [[value * factor for value in row] for row in bbox],
            "volume_m3": volume * factor ** 3}


def main():
    """不愈合、不转实体、不修改输入；源装配与流体实体分别判断。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--coordinate-units", required=True, choices=sorted(METRES_PER_COORDINATE))
    parser.add_argument("--expected-solids", type=int, default=1)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.expected_solids < 1:
        raise ValueError("此准入用于流体实体；初始0实体装配请单独检查")
    import Part
    source_hash = sha256(args.input)
    shape = Part.read(str(args.input))
    box = shape.BoundBox
    captured, errors = io.StringIO(), []
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            response = shape.check(True)
        if response:
            errors.append(str(response))
    except Exception as error:
        errors.append(str(error))
    diagnostic = captured.getvalue()
    if "error" in diagnostic.lower() or "invalid" in diagnostic.lower():
        errors.append(diagnostic)
    metrics = normalized_metrics([[box.XMin, box.YMin, box.ZMin], [box.XMax, box.YMax, box.ZMax]],
                                 float(shape.Volume), args.coordinate_units)
    passed = bool(shape.isValid() and shape.isClosed() and len(shape.Solids) == args.expected_solids
                  and shape.Volume > 0 and not errors)
    result = dict(metrics, source_name=args.input.name, sha256=source_hash,
                  coordinate_units=args.coordinate_units, valid=shape.isValid(), closed=shape.isClosed(),
                  solids=len(shape.Solids), shells=len(shape.Shells), faces=len(shape.Faces), edges=len(shape.Edges),
                  deep_check_passed=not errors, deep_diagnostics=errors, captured=diagnostic, passed=passed,
                  scope="几何只读准入，不证明流道范围和功能特征完整")
    if sha256(args.input) != source_hash:
        raise RuntimeError("审计期间源文件发生变化")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(result, ensure_ascii=False))
    if not passed:
        raise RuntimeError("几何审计未通过，报告已保存")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("CAD审计失败：" + str(error), file=sys.stderr)
        sys.exit(1)

# -*- coding: utf-8 -*-
"""在 FreeCAD 兼容 Python 中只读回读 STEP，检查有效性/深度诊断及米制尺寸。"""
import argparse
import contextlib
import io
import sys
from pathlib import Path
# FreeCAD/嵌入式 Python 也应能找到随技能安装的公共工具。
sys.path.insert(0,str(Path(__file__).resolve().parent))
from fan_case import digest, number, require, write_json


def main():
    """长度换算由命令行明确给出，深度通过不代替保形偏差验证。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True)
    parser.add_argument('--length-to-m',type=float,required=True,help='OCC导入后的坐标到米的倍率')
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    number(args.length_to_m,'length-to-m',1e-30)
    source = Path(args.input).resolve(); target = Path(args.output).resolve()
    require(source != target, '检查输出不能覆盖原始 CAD')
    import FreeCAD
    import Part
    shape = Part.read(str(source)); box = shape.BoundBox; capture = io.StringIO(); errors = []
    try:
        with contextlib.redirect_stdout(capture),contextlib.redirect_stderr(capture):
            returned = shape.check(True)
        if returned:
            errors.append(str(returned))
    except Exception as error:
        errors.append(str(error))
    diagnostic = capture.getvalue()
    if 'error' in diagnostic.lower() or 'invalid' in diagnostic.lower():
        errors.append(diagnostic)
    basic = shape.isValid() and shape.isClosed() and shape.Volume > 0 and len(shape.Solids) > 0
    result = {'file':source.name,'sha256':digest(source),'valid':shape.isValid(),'closed':shape.isClosed(),
              'solids':len(shape.Solids),'faces':len(shape.Faces),'volume_m3':float(shape.Volume)*args.length_to_m**3,
              'bbox_m':[float(v)*args.length_to_m for v in [box.XMin,box.YMin,box.ZMin,box.XMax,box.YMax,box.ZMax]],
              'deep_check_passed':not errors,'deep_diagnostics':errors,'captured':diagnostic,
              'passed':bool(basic and not errors),'scope':'CAD topology only; shape preservation requires separate comparison'}
    write_json(target,result)
    require(result['passed'],'CAD 检查未通过，见输出诊断')
    print('CAD_TOPOLOGY_PASSED')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error),file=sys.stderr); sys.exit(1)

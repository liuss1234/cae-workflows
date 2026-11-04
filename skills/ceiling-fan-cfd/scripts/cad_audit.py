# -*- coding: utf-8 -*-
"""在FreeCAD兼容Python中独立回读CAD，保存基本/深度检查和来源哈希。"""
import argparse
import contextlib
import io
import json
import sys
from pathlib import Path
from fan_case import digest, write_json


def main():
    """不修复、不修改输入，不将基本有效冒充深度通过。"""
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True)
    p.add_argument('--output',required=True);a=p.parse_args()
    import Part
    source=Path(a.input);shape=Part.read(str(source))
    b=shape.BoundBox;capture=io.StringIO();errors=[]
    try:
        with contextlib.redirect_stdout(capture),contextlib.redirect_stderr(capture):
            returned=shape.check(True)
        if returned:errors.append(str(returned))
    except Exception as exc:errors.append(str(exc))
    diagnostic=capture.getvalue()
    if 'error' in diagnostic.lower() or 'invalid' in diagnostic.lower():errors.append(diagnostic)
    basic=shape.isValid() and shape.isClosed() and shape.Volume>0 and len(shape.Solids)>0
    result=dict(source_name=source.name,sha256=digest(source),valid=shape.isValid(),closed=shape.isClosed(),
        solids=len(shape.Solids),faces=len(shape.Faces),volume=float(shape.Volume),
        bbox=[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax],input_units='as supplied; verify metadata',
        deep_check_passed=not errors,deep_diagnostics=errors,captured=diagnostic,passed=bool(basic and not errors))
    write_json(a.output,result);print(json.dumps(result,ensure_ascii=False))
    if not result['passed']:raise RuntimeError('CAD检查未通过')


if __name__=='__main__':
    try:main()
    except Exception as exc:print(str(exc),file=sys.stderr);sys.exit(1)

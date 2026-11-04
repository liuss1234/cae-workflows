# -*- coding: utf-8 -*-
"""用本案例参数生成STAR多面体＋棱柱层宏，禁止覆盖既有宏或模型结果。"""
import argparse
import json
import re
import sys
from pathlib import Path
from fan_case import CONFIG_REL, SKILL, read_json, validate_config


def render(case, mesh_dir, log_dir, output):
    """只生成宏；商业网格软件仍需单独安装和执行。"""
    cfg=read_json(Path(case)/CONFIG_REL);validate_config(cfg)
    mesh=Path(mesh_dir).resolve();log=Path(log_dir).resolve();out=Path(output)
    if out.exists():raise FileExistsError(out)
    if out.name!='MeshCeilingFan.java':raise ValueError('Java文件名必须匹配MeshCeilingFan类')
    values=dict(cfg['mesh'],MESH_DIR=mesh.as_posix(),LOG_DIR=log.as_posix())
    def replace(match):
        """路径通过JSON转义为Java字符串内容，数值必须有限正值。"""
        key=match.group(1)
        if key not in values:raise KeyError(key)
        value=values[key]
        return json.dumps(value,ensure_ascii=True)[1:-1] if isinstance(value,str) else str(value)
    content=re.sub(r'@@([A-Za-z_0-9]+)@@',replace,(SKILL/'assets/MeshCeilingFan.java.in').read_text(encoding='ascii'))
    if '@@' in content:raise ValueError('未解析的宏参数')
    out.parent.mkdir(parents=True,exist_ok=True);log.mkdir(parents=True,exist_ok=True);mesh.mkdir(parents=True,exist_ok=True)
    with out.open('x',encoding='ascii') as f:f.write(content)
    return dict(macro=str(out),meshing_executed=False,requires='named stationary/rotating metre STL files and compatible STAR installation')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['case','mesh-dir','log-dir','output']:p.add_argument('--'+key,required=True)
    a=p.parse_args()
    try:print(json.dumps(render(a.case,a.mesh_dir,a.log_dir,a.output),ensure_ascii=False))
    except Exception as exc:print(str(exc),file=sys.stderr);sys.exit(1)

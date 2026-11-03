# -*- coding: utf-8 -*-
"""只读探测两个 Python 环境及软件文件；不安装软件、不占用求解许可。"""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys

MODULES = ['numpy','gmsh','h5py','matplotlib']


def probe(executable, code, env=None):
    """子进程隔离原生模块，避免不同 Python ABI 混载。"""
    try:
        result=subprocess.run([executable,'-c',code],capture_output=True,text=True,timeout=45,env=env)
        return {'passed':result.returncode==0,'stdout':result.stdout.strip(),'stderr':result.stderr.strip()}
    except Exception as exc:return {'passed':False,'error':str(exc)}


def main():
    """区分通用建模 Python 和 QFlux 匹配 ABI 的 Python。"""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--check-api',action='store_true',help='额外导入厂商 API，不初始化求解器')
    args=parser.parse_args()
    cfg=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))['software']
    build=cfg['build_python'] or sys.executable
    extra=cfg['extra_python_paths']
    code='import sys,json,importlib; sys.path[:0]='+repr(extra)+'; names='+repr(MODULES)+'; print(sys.version); print(json.dumps({n:getattr(importlib.import_module(n),"__version__","available") for n in names}))'
    report={'build_python':probe(build,code),'configured_files':{}}
    home=os.environ.get('QFLUX_HOME') or cfg['qflux_home']
    if home:
        for name in ['QSolver.exe','qxcgns64.dll','python38.dll']:
            report['configured_files'][name]=(Path(home)/name).is_file()
    report['freecad_configured']=bool(cfg['freecad_exe'] and Path(cfg['freecad_exe']).is_file())
    if args.check_api:
        if not home or not cfg['qflux_python']:raise ValueError('需配置 qflux_home 和 qflux_python')
        code='import os,sys; p='+repr(home)+'; sys.path.insert(0,p); cookie=os.add_dll_directory(p); from qfxPyApi import qxcmd; print(sys.version); print("QFLUX_API_IMPORT_OK")'
        env=os.environ.copy();env['PATH']=home+os.pathsep+env.get('PATH','')
        report['qflux_api']=probe(cfg['qflux_python'],code,env)
    report['passed']=report['build_python']['passed'] and all(report['configured_files'].values()) and bool(home)
    if args.check_api:report['passed']=report['passed'] and report['qflux_api']['passed']
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':sys.exit(main())

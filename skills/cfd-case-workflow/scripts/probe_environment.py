# -*- coding: utf-8 -*-
"""只读环境检测，隔离 Python ABI；不启动求解器、不安装或下载软件。"""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys
from cfd_common import context, write_json

# 超时仅用于检测原生导入，不是求解超时。
IMPORT_TIMEOUT_SECONDS = 45
BUILD_MODULES = ["numpy", "gmsh", "h5py"]


def probe(executable, code, env=None):
    """子进程捕获 DLL/ABI 导入失败，避免拖垮主工作进程。"""
    try:
        result = subprocess.run([executable, "-c", code], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=IMPORT_TIMEOUT_SECONDS, env=env)
        return {"passed": result.returncode == 0, "returncode": result.returncode,
                "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except Exception as exc:
        return {"passed": False, "error": str(exc)}


def main():
    """必要项按本包默认 Gmsh/QFlux 后端检测，FreeCAD 和绘图为可选。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--environment")
    parser.add_argument("--check-api", action="store_true")
    parser.add_argument("--output", help="可选新报告文件，默认只打印")
    args = parser.parse_args()
    root, cfg, env = context(args.case, args.environment)
    build = env.get("build_python") or sys.executable
    code = ("import sys,json,importlib,struct;sys.path[:0]=" + repr(env.get("extra_python_paths", [])) +
            ";names=" + repr(BUILD_MODULES) + ";print(sys.version);print(struct.calcsize('P')*8);" +
            "print(json.dumps({n:getattr(importlib.import_module(n),'__version__','available') for n in names}))")
    report = {"platform": sys.platform, "build": probe(build, code), "optional": {}}
    for key in ["freecad_cmd", "freecad_gui", "gmsh_exe"]:
        path = env.get(key, "")
        report["optional"][key] = bool(path and (Path(path).is_file() or shutil.which(path)))
    home = env.get("qflux_home", "")
    library = env.get("cgns_library") or (str(Path(home) / "qxcgns64.dll") if home and os.name == "nt" else "")
    solver = Path(home) / ("QSolver.exe" if os.name == "nt" else "QSolver")
    report["qflux"] = {"home_exists": bool(home and Path(home).is_dir()), "solver_exists": bool(home and solver.is_file()),
                         "cgns_library_exists": bool(library and Path(library).is_file()), "cgns_index_bits": env.get("cgns_index_bits")}
    report["passed"] = report["build"]["passed"] and all(report["qflux"][k] for k in ["home_exists", "solver_exists", "cgns_library_exists"]) and env.get("cgns_index_bits") in [32, 64]
    if args.check_api:
        if os.name != "nt":
            report["api"] = {"passed": False, "error": "本包 QFlux 原生 API 仅验证 Windows；Linux 按厂商发行版另行适配"}
        elif not home or not env.get("qflux_python"):
            report["api"] = {"passed": False, "error": "请填写 qflux_home 与 qflux_python"}
        else:
            code = ("import os,sys,struct;p=" + repr(home) + ";sys.path.insert(0,p);cookie=os.add_dll_directory(p);" +
                    "from qfxPyApi import qxapp,qxcmd;print(sys.version);print(struct.calcsize('P')*8);print('QFLUX_API_IMPORT_OK')")
            process_env = os.environ.copy()
            process_env["PATH"] = home + os.pathsep + process_env.get("PATH", "")
            report["api"] = probe(env["qflux_python"], code, process_env)
        report["passed"] = report["passed"] and report["api"]["passed"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        path = Path(args.output).resolve()
        if path.exists():
            raise FileExistsError(path)
        write_json(path, report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

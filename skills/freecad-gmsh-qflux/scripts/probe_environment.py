# -*- coding: utf-8 -*-
"""只读检查软件路径和 Python ABI；不安装软件、不启动求解或修改应用设置。"""

# 可调默认参数；换机器时复制并修改环境 JSON，或传入 --profile。
from pathlib import Path
DEFAULT_PROFILE = Path(__file__).resolve().parents[1] / "assets" / "environment.example.json"
IMPORT_TIMEOUT_SECONDS = 30
REQUIRED_KEYS = ("freecad_gui", "freecad_cmd", "gmsh_exe", "gmsh_api", "exchange_api",
                 "python_mesh", "python_qflux", "qflux_directory")

import argparse
import json
import os
import subprocess
import sys


def load_profile(path):
    """读取路径配置，允许用户目录和环境变量，避免 shell 字符串拼接。"""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    missing = set(REQUIRED_KEYS) - set(data)
    if missing:
        raise ValueError("环境配置缺少字段：" + ", ".join(sorted(missing)))
    empty = [key for key in REQUIRED_KEYS if not isinstance(data[key], str) or not data[key].strip()]
    if empty:
        raise ValueError("请复制环境模板并填写本机路径，空字段：" + ", ".join(empty))
    return {key: os.path.expandvars(os.path.expanduser(value)) if isinstance(value, str) else value
            for key, value in data.items()}


def check_import(executable, code):
    """用指定解释器检查模块，分别验证网格环境与 QFlux Python ABI。"""
    result = subprocess.run([executable, "-c", code], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=IMPORT_TIMEOUT_SECONDS)
    return {"passed": result.returncode == 0, "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(), "exit_code": result.returncode}


def main():
    """路径检查始终执行，模块导入检查按参数启用。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--check-imports", action="store_true")
    parser.add_argument("--output", type=Path, help="可选的新报告文件；已有文件不覆盖")
    args = parser.parse_args()
    profile = load_profile(args.profile)
    paths = {key: {"path": profile[key], "exists": Path(profile[key]).exists()} for key in REQUIRED_KEYS}
    report = {"profile": str(args.profile.resolve()), "paths": paths,
              "passed": all(item["exists"] for item in paths.values()), "imports": {}}
    if args.check_imports and report["passed"]:
        mesh_code = ("import sys; sys.path[:0]=" + repr([profile["gmsh_api"], profile["exchange_api"]])
                     + "; import gmsh,numpy,h5py; print(sys.version.split()[0],gmsh.__version__,numpy.__version__,h5py.__version__)")
        qflux_code = ("import sys,os; d=" + repr(profile["qflux_directory"])
                      + "; sys.path.insert(0,d); c=os.add_dll_directory(d); os.environ['PATH']=d+os.pathsep+os.environ.get('PATH','');"
                      + " import qfxPyApi; print(sys.version.split()[0],qfxPyApi.__file__)")
        report["imports"]["mesh"] = check_import(profile["python_mesh"], mesh_code)
        if os.name == "nt":
            report["imports"]["qflux"] = check_import(profile["python_qflux"], qflux_code)
        else:
            report["imports"]["qflux"] = {"passed": False, "reason": "附带的 QFlux .pyd 适配器仅在 Windows 验证"}
        report["passed"] = report["passed"] and all(item["passed"] for item in report["imports"].values())
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text + "\n")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print("环境检查失败：" + str(error), file=sys.stderr)
        sys.exit(1)

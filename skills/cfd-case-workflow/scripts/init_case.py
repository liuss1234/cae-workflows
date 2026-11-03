# -*- coding: utf-8 -*-
"""创建自包含 CFD 案例；示例仅作安装自检，支持随后替换几何/物理适配器。"""
from pathlib import Path
import argparse
import shutil
import sys
from cfd_common import write_json

# 技能资源路径由当前脚本位置推导；不包含开发电脑的绝对路径。
SKILL_ROOT = Path(__file__).resolve().parents[1]
CASE_TOOLS = ["cfd_common.py", "probe_environment.py", "mesh_export.py", "qflux_case.py", "run_solver.py", "solution_check.py", "plot_vtu.py", "package_artifacts.py"]


def main():
    """复制必要工具，不复制软件、缓存、环境凭据或历史计算结果。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--example", choices=["duct", "custom"], default="custom")
    args = parser.parse_args()
    root = args.directory.resolve()
    if root.exists():
        raise FileExistsError("案例目录已存在，请选择新目录：" + str(root))
    for name in CASE_TOOLS:
        if not (SKILL_ROOT / "scripts" / name).is_file():
            raise FileNotFoundError(name)
    root.mkdir(parents=True)
    for folder in ["adapters", "tools", "cad", "mesh", "checks", "post", "runs"]:
        (root / folder).mkdir()
    source = "duct.case.json" if args.example == "duct" else "case.template.json"
    shutil.copy2(SKILL_ROOT / "assets" / source, root / "case.json")
    shutil.copy2(SKILL_ROOT / "assets" / "environment.example.json", root / "environment.json")
    shutil.copy2(SKILL_ROOT / "assets" / "requirements-build.txt", root / "requirements-build.txt")
    for name in CASE_TOOLS:
        shutil.copy2(SKILL_ROOT / "scripts" / name, root / "tools" / name)
    if args.example == "duct":
        shutil.copy2(SKILL_ROOT / "assets" / "duct.py", root / "adapters" / "duct.py")
    else:
        write_json(root / "regions.json", {"units": "m", "zones": [], "interfaces": []})
    write_json(root / "delivery.json", {"files": ["case.json", "regions.json", "requirements-build.txt"] + ["tools/" + x for x in CASE_TOOLS]})
    print(str(root))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("创建失败：" + str(exc), file=sys.stderr)
        sys.exit(1)

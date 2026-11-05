# -*- coding: utf-8 -*-
"""从显式清单生成独立技能 ZIP；复用 CFD 打包器的 CRC/SHA256 回读验证。"""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import tempfile

# 可调参数：仓库根目录由脚本位置推导，模块名称须与 skills 中的目录一致。
REPOSITORY = Path(__file__).resolve().parents[1]
WORKFLOWS = ("cfd-case-workflow", "cfd-preprocessing", "freecad-gmsh-qflux", "qflux-liquid-cooling", "ceiling-fan-cfd", "fan-cfd")
RESOURCE_SUFFIXES = {".md", ".py", ".ps1", ".json", ".yaml", ".yml", ".txt", ".FCMacro", ".FCStd"}
PRIVATE_NAMES = {"environment.json", "environment.local.json", "local-windows.json", "workflow.json"}


def collect_resources(root):
    """按资源类型选择文件，排除本机配置与缓存，保持技能内的相对路径。"""
    resources = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.name in PRIVATE_NAMES or (path.suffix not in RESOURCE_SUFFIXES and not path.name.endswith(".java.in")):
            raise ValueError("技能目录含未分类或本机私有文件：" + str(path))
        resources.append(path.relative_to(root).as_posix())
    if "SKILL.md" not in resources:
        raise FileNotFoundError(root / "SKILL.md")
    return resources


def main():
    """每次创建全新输出目录；所有 ZIP 在生成后由公共打包器独立回读。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="尚不存在的新输出目录")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError("输出目录已存在，请选择新目录：" + str(output))
    # 先检查全部输入，再创建输出，减少无效输入留下的半成品。
    resources = {name: collect_resources(REPOSITORY / "skills" / name) for name in WORKFLOWS}
    output.mkdir(parents=True)
    packer = REPOSITORY / "skills" / "cfd-case-workflow" / "scripts" / "package_artifacts.py"
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    with tempfile.TemporaryDirectory(prefix="cae-manifests-") as temporary:
        for name in WORKFLOWS:
            manifest = Path(temporary) / (name + ".json")
            manifest.write_text(json.dumps({"files": resources[name]}, ensure_ascii=False), encoding="utf-8")
            command = [sys.executable, str(packer), "create", "--root", str(REPOSITORY / "skills" / name),
                       "--manifest", str(manifest), "--output", str(output / (name + ".zip")), "--prefix", name]
            subprocess.run(command, check=True, env=environment)
    print("已生成并验证 %d 个工作流包：%s" % (len(WORKFLOWS), output))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("工作流打包失败：" + str(error), file=sys.stderr)
        sys.exit(1)

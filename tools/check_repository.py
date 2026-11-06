# -*- coding: utf-8 -*-
"""在 Windows/Linux 检查工作流资源与可迁移入口，不导入厂商 API、不运行求解器。"""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from urllib.parse import unquote
from xml.etree import ElementTree

from repository_manifest import README_PATH, expected_readme, load_workflows

# 可调检查参数：运行隔离在临时目录，子进程超时不影响实际 CFD 求解。
REPOSITORY = Path(__file__).resolve().parents[1]
WORKFLOW_RECORDS = load_workflows()
WORKFLOWS = tuple(workflow["name"] for workflow in WORKFLOW_RECORDS)
COMMAND_TIMEOUT_SECONDS = 60
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
EXCLUDED_DIRECTORIES = {".git", ".venv", ".venv-cfd", "__pycache__", "cases", "dist", "local"}
CLI_ENTRIES = {workflow["name"]: tuple(workflow.get("cli_entries", [])) for workflow in WORKFLOW_RECORDS}


def run(arguments, expected=0):
    """用当前解释器执行入口并核对状态；失败时保留输出以便定位缺失依赖。"""
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    process = subprocess.run([sys.executable] + [str(item) for item in arguments], cwd=str(REPOSITORY),
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=COMMAND_TIMEOUT_SECONDS, env=environment)
    if process.returncode != expected:
        raise RuntimeError("命令状态异常：%s\n%s\n%s" % (arguments, process.stdout, process.stderr))
    return process


def check_sources():
    """解析源码、参数与元数据，检查文档链接及风扇 CAD 内部资源完整性。"""
    try:
        import yaml
    except ImportError as error:
        raise RuntimeError("请先执行 python -m pip install -r requirements-dev.txt") from error
    counts = {"python_and_macros": 0, "json": 0, "yaml": 0, "local_links": 0, "skills": 0}
    for path in REPOSITORY.rglob("*"):
        relative = path.relative_to(REPOSITORY)
        if not path.is_file() or set(relative.parts) & EXCLUDED_DIRECTORIES:
            continue
        if path.suffix in {".py", ".FCMacro"}:
            # 只解析，不执行依赖 FreeCAD、Gmsh 或 QFlux 的模板。
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(relative), feature_version=8)
            counts["python_and_macros"] += 1
        elif path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8-sig"))
            counts["json"] += 1
        elif path.suffix in {".yaml", ".yml"}:
            yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            counts["yaml"] += 1
        if path.suffix == ".md":
            content = path.read_text(encoding="utf-8-sig")
            for match in LINK_PATTERN.finditer(content):
                target = match.group(1).strip().strip("<>").split("#", 1)[0]
                if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                    continue
                if not (path.parent / unquote(target)).exists():
                    raise FileNotFoundError("文档链接失效：%s → %s" % (relative, target))
                counts["local_links"] += 1
    discovered = {path.parent.name for path in (REPOSITORY / "skills").glob("*/SKILL.md")}
    if discovered != set(WORKFLOWS):
        raise ValueError("workflows.json 与 skills 目录不一致")
    readme = README_PATH.read_text(encoding="utf-8")
    if readme != expected_readme(readme, WORKFLOW_RECORDS):
        raise ValueError("README 工作流表已过期，请执行 python tools/update_readme.py")
    for name in WORKFLOWS:
        content = (REPOSITORY / "skills" / name / "SKILL.md").read_text(encoding="utf-8-sig")
        match = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|$)", content, re.DOTALL)
        if not match:
            raise ValueError("技能缺少标准 YAML 头部：" + name)
        metadata = yaml.safe_load(match.group(1))
        if metadata.get("name") != name or not isinstance(metadata.get("description"), str) or not metadata["description"].strip():
            raise ValueError("技能名称或描述无效：" + name)
        counts["skills"] += 1
    model = REPOSITORY / "skills/freecad-gmsh-qflux/assets/fan-example.FCStd"
    with zipfile.ZipFile(model) as archive:
        if archive.testzip():
            raise ValueError("风扇 FCStd 内部 CRC 校验失败")
        ElementTree.fromstring(archive.read("Document.xml"))
    return counts


def snapshot(root):
    """记录文件内容，验证拒绝覆盖时没有悄悄修改原有案例。"""
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts}


def check_initialization(temporary):
    """创建直管、自定义与液冷案例；独立目录只保留复制出的资源。"""
    source = REPOSITORY / "skills"
    for example in ("duct", "custom"):
        case = temporary / example
        command = [source / "cfd-case-workflow/scripts/init_case.py", "--directory", case, "--example", example]
        run(command)
        json.loads((case / "case.json").read_text(encoding="utf-8"))
        if example == "duct" and not (case / "adapters/duct.py").is_file():
            raise FileNotFoundError("直管适配器未随案例复制")
        if example == "custom" and json.loads((case / "regions.json").read_text(encoding="utf-8"))["zones"]:
            raise ValueError("自定义案例意外包含固定几何区")
        before = snapshot(case)
        run(command, expected=1)
        if snapshot(case) != before:
            raise ValueError("拒绝覆盖时案例内容发生变化")
        run([case / "tools/package_artifacts.py", "--help"])
    cooling = temporary / "cooling"
    command = [source / "qflux-liquid-cooling/scripts/init_case.py", "--output", cooling]
    run(command)
    configuration = json.loads((cooling / "workflow.json").read_text(encoding="utf-8"))
    if configuration["software"]["qflux_home"] or configuration["remote"]["ssh_target"]:
        raise ValueError("液冷模板不应内置机器配置")
    before = snapshot(cooling)
    run(command, expected=1)
    if snapshot(cooling) != before:
        raise ValueError("液冷案例拒绝覆盖时内容发生变化")
    # 空风扇配置必须失败，不能把 Path('') 当成已安装依赖。
    run([source / "freecad-gmsh-qflux/scripts/probe_environment.py"], expected=1)
    # init 阶段只复制 CAD/脚本，用临时配置即可验证搬离技能目录后的结构。
    profile = json.loads((source / "freecad-gmsh-qflux/assets/environment.example.json").read_text(encoding="utf-8"))
    profile.update({key: str(temporary) for key in profile})
    profile_path = temporary / "fan-profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    fan = temporary / "fan"
    command = [source / "freecad-gmsh-qflux/scripts/run_fan_example.py", "init", "--workspace", fan, "--profile", profile_path]
    run(command)
    if (fan / "source_current.FCStd").read_bytes() != (source / "freecad-gmsh-qflux/assets/fan-example.FCStd").read_bytes():
        raise ValueError("风扇快照复制发生内容变化")
    before = snapshot(fan)
    run(command, expected=1)
    if snapshot(fan) != before:
        raise ValueError("风扇初始化拒绝覆盖时内容发生变化")


def check_slurm_helpers(temporary):
    """用合成输入验证 Slurm 准备与登记保护，不调用调度器。"""
    source = REPOSITORY / "skills/qflux-slurm/scripts/slurm_scaling.py"
    root = temporary / "slurm-scaling"
    qfx = temporary / "synthetic.qfx"
    template = temporary / "template.sh"
    qfx.write_bytes(b"synthetic-qfx-input")
    template.write_text("#!/usr/bin/env bash\nset -e\nmodule load qflux\n", encoding="utf-8")
    run([source, "prepare", "--root", root, "--qfx", qfx, "--template", template,
         "--partition", "test", "--cores", "2", "4", "--job-prefix", "smoke"])
    manifest_path = root / "jobs.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if len(manifest["runs"]) != 2 or manifest["source_qfx_sha256"] != hashlib.sha256(qfx.read_bytes()).hexdigest():
        raise ValueError("Slurm 准备清单或工程哈希异常")
    if any(not (root / run_info["directory"] / "submit.sh").is_file() for run_info in manifest["runs"]):
        raise FileNotFoundError("Slurm 独立核数目录缺少提交脚本")
    run([source, "register", "--root", root, "--cores", "2", "--job-id", "123456"])
    before = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    run([source, "register", "--root", root, "--cores", "2", "--job-id", "654321"], expected=1)
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != before:
        raise ValueError("拒绝重复登记时 Slurm 清单发生变化")


def main():
    """完成结构、命令行、初始化及可安装 ZIP 的回读检查，输出可审查的结果。"""
    argparse.ArgumentParser(description=__doc__).parse_args()
    report = check_sources()
    report["workflow_registry"] = "passed"
    for name, entries in CLI_ENTRIES.items():
        for entry in entries:
            run([REPOSITORY / "skills" / name / "scripts" / (entry + ".py"), "--help"])
    report["cli_entries"] = sum(len(entries) for entries in CLI_ENTRIES.values())
    with tempfile.TemporaryDirectory(prefix="cae-workflow-check-") as directory:
        temporary = Path(directory)
        check_initialization(temporary)
        check_slurm_helpers(temporary)
        report["slurm_prepare_register"] = "passed"
        for workflow in WORKFLOW_RECORDS:
            if workflow.get("self_test"):
                run([REPOSITORY / "skills" / workflow["name"] / workflow["self_test"]])
                report[workflow["name"].replace("-", "_") + "_self_test"] = "passed"
        output = temporary / "packages"
        run([REPOSITORY / "tools/package_workflows.py", "--output", output])
        packer = REPOSITORY / "skills/cfd-case-workflow/scripts/package_artifacts.py"
        for workflow in WORKFLOW_RECORDS:
            name = workflow["name"]
            archive_path = output / (name + ".zip")
            run([packer, "verify", archive_path])
            with zipfile.ZipFile(archive_path) as archive:
                if name + "/SKILL.md" not in archive.namelist():
                    raise ValueError("安装包缺少技能入口：" + name)
                for relative in workflow.get("required_package_files", []):
                    if name + "/" + relative not in archive.namelist():
                        raise ValueError("安装包遗漏必要文件：%s/%s" % (name, relative))
        run([REPOSITORY / "tools/package_workflows.py", "--output", output], expected=1)
    report.update(initialization="passed", overwrite_protection="passed", packages_crc_sha256="passed", passed=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("仓库检查失败：" + str(error), file=sys.stderr)
        sys.exit(1)

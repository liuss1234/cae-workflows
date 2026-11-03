# -*- coding: utf-8 -*-
"""在独立目录复用七叶风扇示例；软件路径由 JSON 指定，所有进程采用参数列表启动。"""

# 可调参数；几何/网格参数位于初始化后 workspace/scripts 中各文件头部。
from pathlib import Path
SKILL_DIRECTORY = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = SKILL_DIRECTORY / "assets" / "environment.example.json"
DEFAULT_SOURCE = SKILL_DIRECTORY / "assets" / "fan-example.FCStd"
STAGES = ("init", "draw", "geometry", "view", "mesh", "quality", "export", "qflux", "all")

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from probe_environment import load_profile


def launch(command, environment, log_path, visible=False):
    """保留每阶段日志；后台计算不弹控制台，用户要求的 GUI 阶段正常显示。"""
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" and not visible else 0
    print("RUN " + str(log_path.name), flush=True)
    with log_path.open("x", encoding="utf-8") as log:
        process = subprocess.Popen(command, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=flags, cwd=str(log_path.parent))
        if visible:
            print("GUI_PID " + str(process.pid), flush=True)
            return
        status = process.wait()
    if status:
        raise RuntimeError("阶段失败，退出码 %s；查看日志：%s" % (status, log_path))


def main():
    """all 模式新建项目；分阶段模式允许调整参数后继续，不改写原始 CAD。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=STAGES)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="须与七叶风扇示例对象结构兼容的独立快照")
    args = parser.parse_args()
    profile = load_profile(args.profile)
    workspace = args.workspace.resolve()
    if args.stage in ("init", "all"):
        if not args.source.is_file():
            raise FileNotFoundError(args.source)
        workspace.mkdir(parents=True, exist_ok=False)
        shutil.copy2(args.source, workspace / "source_current.FCStd")
        shutil.copytree(SKILL_DIRECTORY / "scripts" / "fan_example", workspace / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if not workspace.is_dir() or not (workspace / "scripts").is_dir():
        raise RuntimeError("请先用 init 在新目录初始化示例")
    environment = os.environ.copy()
    environment.update(CFD_WORK_DIRECTORY=str(workspace), CFD_GMSH_API=profile["gmsh_api"],
                       CFD_EXCHANGE_API=profile["exchange_api"], CFD_GMSH_EXE=profile["gmsh_exe"],
                       CFD_QFLUX_DIRECTORY=profile["qflux_directory"], PYTHONUTF8="1")
    stages = ("geometry", "mesh", "quality", "export", "qflux") if args.stage == "all" else (args.stage,)
    for stage in stages:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        scripts = workspace / "scripts"

        def execute(command, label, visible=False):
            """给每次运行独立命名日志，避免覆盖此前诊断信息。"""
            launch(command, environment, workspace / (stamp + "_" + label + ".log"), visible)

        def freecad_script(filename):
            """FreeCAD 自带解释器执行脚本，Python 路径用 repr 转义。"""
            path = str(scripts / filename)
            code = "exec(compile(open(%r,'rb').read(),%r,'exec'))" % (path, path)
            execute([profile["freecad_cmd"], "-c", code], filename)

        if stage == "init":
            print("INITIALIZED " + str(workspace), flush=True)
        elif stage == "draw":
            execute([profile["freecad_gui"], str(scripts / "draw_axial_fan.FCMacro")], "drawing", True)
        elif stage == "geometry":
            freecad_script("build_fan_cfd.py")
            freecad_script("export_face_signatures.py")
        elif stage == "view":
            execute([profile["freecad_gui"], str(scripts / "show_fan_cfd.FCMacro")], "view", True)
        elif stage in ("mesh", "quality", "export"):
            filename = {"mesh": "mesh_fan_gmsh.py", "quality": "check_fan_mesh.py", "export": "export_fan_si.py"}[stage]
            execute([profile["python_mesh"], "-u", str(scripts / filename)], stage)
        elif stage == "qflux":
            source = Path(json.loads((workspace / "latest_qflux_si.json").read_text(encoding="utf-8"))["output_directory"])
            handoff = SKILL_DIRECTORY / "scripts" / "qflux_handoff.py"
            imported = workspace / ("qflux_import_" + stamp)
            reopened = workspace / ("qflux_reopen_" + stamp)
            common = ["--qflux-directory", profile["qflux_directory"], "--expected", str(source / "si_export_check.json")]
            execute([profile["python_qflux"], "-u", str(handoff), str(source / "fan_cfd_m.cgns"),
                     "--save-project", "--output-dir", str(imported)] + common, "qflux_import")
            execute([profile["python_qflux"], "-u", str(handoff), str(imported / "project.qfx"),
                     "--open-case", "--output-dir", str(reopened)] + common, "qflux_reopen")
            pointer = {"project": str(imported / "project.qfx"), "check": str(reopened / "check.json")}
            (workspace / "latest_qflux_project.json").write_text(json.dumps(pointer, ensure_ascii=False, indent=2), encoding="utf-8")
            print("QFLUX_VERIFIED " + json.dumps(pointer, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("运行失败：" + str(error), file=sys.stderr)
        sys.exit(1)

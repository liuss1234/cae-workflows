# -*- coding: utf-8 -*-
"""以独立阶段启动 QSolver，保存日志、PID 和结果来源；不覆盖、不自动杀进程。"""
from pathlib import Path
import argparse
import datetime
import os
import re
import shutil
import socket
import subprocess
import sys
import traceback
from cfd_common import context, inside, read_json, write_json, sha256, exclusive_directory

# 仅允许安全的阶段标识；迭代参数、核数、软件位置从 JSON 读取。
STAGE_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}"


def now():
    """记录 UTC 时间，便于跨主机核对日志。"""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main():
    """阻塞等待子求解器完成；外部智能体可用后台工具保持对话响应。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--readback", default="checks/readback/check.json")
    parser.add_argument("--initial", help="续算用已完成 DAT；独立回读必须同时验证该场")
    parser.add_argument("--environment")
    args = parser.parse_args()
    if not re.fullmatch(STAGE_PATTERN, args.stage):
        raise ValueError("阶段名称仅允许字母数字、下划线、短横线")
    root, cfg, env = context(args.case, args.environment)
    qfx = inside(root, cfg["files"]["qfx"])
    report = read_json(inside(root, args.readback))
    qfx_hash = sha256(qfx)
    if not report.get("passed") or not report.get("independent_readback") or report.get("mesh_only") or report.get("source_sha256") != qfx_hash:
        raise ValueError("缺少当前 QFX 的成功独立回读记录")
    initial = Path(args.initial).resolve() if args.initial else None
    if initial and (not initial.is_file() or report.get("source_data_sha256") != sha256(initial)):
        raise ValueError("续算 DAT 必须在当前工程独立回读记录中验证")
    home = Path(env.get("qflux_home", ""))
    if not env.get("qflux_home"):
        raise ValueError("未配置 qflux_home")
    solver = home / ("QSolver.exe" if os.name == "nt" else "QSolver")
    if not solver.is_file():
        raise FileNotFoundError(solver)
    cores = int(cfg["solver"]["cores"])
    if cores < 1 or cores > (os.cpu_count() or 1):
        raise ValueError("核数超出本机可用范围")
    stage = inside(root, "runs/" + args.stage)
    if stage.exists():
        raise FileExistsError("阶段目录已存在，请使用新阶段名称")
    lock = root / "checks/solver.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL 提供同一案例跨进程互斥；远程必须在同一目标文件系统内运行。
    handle = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(handle)
    process = None
    try:
        exclusive_directory(stage)
        # 本机 QSolver 会在结束时回写传入的 QFX；使用阶段副本保护已回读的源工程。
        solver_qfx = stage / "solver_input.qfx"
        shutil.copy2(qfx, solver_qfx)
        if sha256(solver_qfx) != qfx_hash:
            raise ValueError("复制期间源 QFX 发生变化，未启动求解")
        command = [str(solver), "-q", str(solver_qfx), "-o", str(stage), "-n", str(cores)]
        if initial:
            command += ["-i", str(initial)]
        job = {"host": socket.gethostname(), "launcher_pid": os.getpid(), "started_utc": now(), "qfx": str(qfx),
               "qfx_sha256": qfx_hash, "solver_qfx": str(solver_qfx), "case_config_sha256": sha256(root / "case.json"), "stage": args.stage,
               "cores": cores, "initial": str(initial) if initial else None, "command": command}
        with (stage / "solver_stdout.log").open("wb") as stdout, (stage / "solver_stderr.log").open("wb") as stderr:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            process_env = os.environ.copy()
            process_env["PATH"] = str(home) + os.pathsep + process_env.get("PATH", "")
            process = subprocess.Popen(command, cwd=str(home), stdout=stdout, stderr=stderr, env=process_env, creationflags=flags)
            job["pid"] = process.pid
            write_json(stage / "job.json", job)
            write_json(lock, job)
            print("SOLVER_STARTED", process.pid, str(stage), flush=True)
            code = process.wait()
        candidates = []
        for path in stage.glob(cfg["name"] + "-*.dat"):
            match = re.search(r"-(\d+)\.dat$", path.name)
            if match and int(match.group(1)) > 0 and path.stat().st_size > 0:
                candidates.append((int(match.group(1)), path))
        candidates.sort()
        final = candidates[-1] if code == 0 and candidates else None
        finished = {"exit_code": code, "finished_utc": now(), "qfx_sha256": qfx_hash,
                    "source_qfx_preserved": sha256(qfx) == qfx_hash, "solver_qfx_final_sha256": sha256(solver_qfx),
                    "case_config_sha256": job["case_config_sha256"], "final_iteration": final[0] if final else None,
                    "final_data": str(final[1].relative_to(root)).replace("\\", "/") if final else None,
                    "final_data_sha256": sha256(final[1]) if final else None,
                    "note": "正常退出和完整文件记录不等于残差、守恒、稳定性或网格精度合格"}
        write_json(stage / "finished.json", finished)
        if code != 0:
            raise RuntimeError("QSolver 非零退出，请检查本阶段 stdout/stderr：" + str(code))
        if not final:
            raise RuntimeError("QSolver 正常退出但未找到非初始化结果场")
        print("SOLVER_FINISHED", final[0], final[1].name, flush=True)
    finally:
        # 启动器被打断而求解器仍在运行时保留锁；不误删活跃任务状态。
        if process is None or process.poll() is not None:
            lock.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)

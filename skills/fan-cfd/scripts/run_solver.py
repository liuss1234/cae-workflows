# -*- coding: utf-8 -*-
"""从独立回读通过的风机工程启动单个 QSolver 阶段，记录进程证据，不判定收敛。"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from fan_case import case_path, config_hash, digest, load_case, number, read_json, require, write_json

# 运行监测参数；资源预算由命令行传入，不把某个产品规模当默认值。
POLL_SECONDS = 1
DISK_CHECK_SECONDS = 10
HEARTBEAT_SECONDS = 30


def now():
    """日志采用 UTC，便于本机和远程对照。"""
    return datetime.now(timezone.utc).isoformat()


def main():
    """默认仅检查/显示；执行使用新的运行目录，拒绝覆盖和重复提交。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',required=True)
    parser.add_argument('--solver-exe',required=True)
    parser.add_argument('--min-free-gb',type=float,required=True,help='运行前及运行中保留的磁盘空间，按本次规模确定')
    parser.add_argument('--execute',action='store_true')
    args = parser.parse_args()
    root = Path(args.case).resolve(); cfg = load_case(root)
    number(args.min_free_gb,'min-free-gb',0)
    source = case_path(root,cfg['files']['qfx']); output = case_path(root,cfg['files']['run'])
    proof = read_json(source.parent/'qflux_readback.json')
    require(proof['passed'] and proof['independent_readback'], '没有独立回读通过证据')
    require(proof['case_sha256'] == config_hash(cfg), '配置在回读后变化')
    require(proof['mesh_sha256'] == cfg['mesh']['sha256'] == digest(case_path(root,cfg['mesh']['file'])), '源网格变化')
    require(proof['mesh_gate_sha256'] == digest(root/'checks/mesh_gate.json'), '网格准入记录变化')
    require(proof['settings_sha256'] == digest(source.parent/'qflux_readback_settings.json'), '落盘设置证据变化')
    source_hash = digest(source)
    require(source_hash == proof['qfx_sha256'], 'QFX在回读后变化')
    executable = Path(args.solver_exe).resolve()
    require(executable.is_file(), '求解器路径不存在')
    require(not output.exists(), '运行目录已存在；重试请新建阶段并重新回读')
    work = output/'solver_input.qfx'
    command = [str(executable),'-q',str(work),'-o',str(output),'-n',str(cfg['solver']['cores'])]
    budget = args.min_free_gb * 1024**3
    require(shutil.disk_usage(root).free >= budget, '剩余磁盘空间低于本次预算')
    if not args.execute:
        print('检查通过，尚未启动求解：'+str(command)); return 0
    output.mkdir(parents=True,exist_ok=False)
    process = None; job = None; code = None; failure = None
    try:
        shutil.copy2(str(source),str(work))
        with (output/'solver_stdout.log').open('wb') as stdout, (output/'solver_stderr.log').open('wb') as stderr:
            process = subprocess.Popen(command,cwd=str(executable.parent),stdout=stdout,stderr=stderr,
                                       stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            job = {'pid':process.pid,'worker_pid':os.getpid(),'started_utc':now(),'command':command,
                   'case_sha256':config_hash(cfg),'source_qfx_sha256':source_hash,'mesh_sha256':cfg['mesh']['sha256']}
            write_json(output/'job.json',job); print('SOLVER_STARTED',process.pid,flush=True)
            next_disk = time.monotonic(); next_beat = next_disk
            while process.poll() is None:
                current = time.monotonic()
                if current >= next_disk:
                    require(shutil.disk_usage(output).free >= budget, '运行中剩余磁盘空间低于预算，终止本次子进程')
                    next_disk = current + DISK_CHECK_SECONDS
                if current >= next_beat:
                    write_json(output/'heartbeat.json',{'pid':process.pid,'utc':now(),'disk_free_bytes':shutil.disk_usage(output).free})
                    print('SOLVER_RUNNING',process.pid,now(),flush=True); next_beat = current + HEARTBEAT_SECONDS
                time.sleep(POLL_SECONDS)
            code = process.returncode
    except BaseException as error:
        failure = str(error)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=20)
        if process is not None:
            code = process.returncode
    finally:
        unchanged = source.is_file() and digest(source) == source_hash
        candidates = [{'file':p.relative_to(output).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)}
                      for p in sorted(output.rglob('*')) if p.is_file() and p != work and p.suffix.lower() in ('.dat','.qfx')
                      and 'monitor' not in p.relative_to(output).as_posix().lower() and p.stat().st_size > 0]
        write_json(output/'finished.json',{'exit_code':code,'finished_utc':now(),'failure':failure,
                   'source_qfx_unchanged':unchanged,'field_candidates':candidates,'job':job,
                   'scope':'process/file evidence only; final iteration, field readback and convergence not assessed'})
    require(failure is None and unchanged, failure or '源工程在运行中被修改')
    require(code == 0, '求解器异常退出，见原始日志与 finished.json')
    require(bool(candidates), '进程返回0但没有候选结果场，需检查日志')
    print('求解进程结束；请核对最终步、场回读及收敛。',flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print('风机求解阶段失败：'+str(error),file=sys.stderr); sys.exit(1)

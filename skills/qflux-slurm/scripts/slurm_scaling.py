#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QFLUX 单节点测速辅助：准备、登记、只读采集；不调用 sbatch。

可调参数全部由命令行给出，详见 --help；仅依赖 Python 3.6+ 标准库。
"""
import argparse
import csv
import hashlib
import json
import math
import re
import shlex
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def sha256(path):
    """分块计算大文件哈希，避免把整个工程/结果场装入内存。"""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save_json(path, data):
    """原子替换元数据，避免中断留下半个 JSON；调用者负责互斥。"""
    temp = path.with_name(path.name + '.tmp')
    with temp.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    temp.replace(path)


@contextmanager
def manifest_lock(root):
    """登记时拒绝并发写入；遗留锁须确认对应操作结束后人工处理。"""
    lock = root / '.manifest.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(datetime.now(timezone.utc).isoformat())
    try:
        yield
    finally:
        lock.unlink()


def clean_template(source):
    """删除将被重新配置的单条资源指令，其他模板逻辑保持原样。"""
    aliases = {'-J', '--job-name', '-p', '--partition', '-N', '--nodes',
               '-n', '--ntasks', '--ntasks-per-node', '-c', '--cpus-per-task',
               '-o', '--output', '-e', '--error'}
    incompatible = {'--array', '-a', '--chdir', '-D', '--wrap', '--gpus',
                    '--gres', '--ntasks-per-core', '--ntasks-per-socket',
                    '--cpus-per-gpu', '--het-group'}
    lines = source.replace('\r\n', '\n').splitlines()
    if not lines or not re.match(r'^#!.*\b(?:bash|sh)\b', lines[0]):
        raise ValueError('模板必须有 bash/sh shebang；请先人工检查脚本')
    output = [lines[0]]
    for line in lines[1:]:
        if line.lstrip().startswith('#SBATCH'):
            if not line.startswith('#SBATCH '):
                raise ValueError('不支持的 SBATCH 格式，请先规范为行首 #SBATCH + 空格')
            tokens = shlex.split(line[len('#SBATCH '):], comments=True)
            if not tokens:
                raise ValueError('空 SBATCH 指令')
            flag = tokens[0].split('=')[0]
            # 支持 -N1 等紧凑形式，但不静默丢弃同行的其他资源选项。
            short = flag[:2] if flag.startswith('-') and not flag.startswith('--') else flag
            name = short if short in aliases | incompatible else flag
            if name in incompatible:
                raise ValueError('模板包含需独立适配的指令：' + name)
            if name in aliases:
                compact = '=' in tokens[0] or name != flag
                expected = 1 if compact else 2
                if len(tokens) != expected or (expected == 2 and tokens[1].startswith('-')):
                    raise ValueError('每行仅支持一个完整资源指令：' + line)
                continue
        output.append(line)
    return output


def prepare(args):
    """为同一初始工程建立各核数隔离目录；拒绝覆盖已有目录。"""
    root, qfx, template = args.root.resolve(), args.qfx.resolve(), args.template.resolve()
    if root.exists():
        raise ValueError('root 已存在，拒绝覆盖：' + str(root))
    if not qfx.is_file() or qfx.suffix.lower() != '.qfx' or not template.is_file():
        raise ValueError('需要真实 .qfx 文件和已有 Slurm 模板')
    if len(set(args.cores)) != len(args.cores) or any(n < 1 for n in args.cores):
        raise ValueError('核数必须为不重复的正整数')
    for value in (args.partition, args.job_prefix):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', value):
            raise ValueError('分区/作业前缀仅支持字母、数字、下划线、点和连字符')
    base = clean_template(template.read_text(encoding='utf-8-sig'))
    digest = sha256(qfx)
    root.mkdir(parents=True)
    shutil.copy2(template, root / 'template.original.sh')
    manifest = {'created': datetime.now(timezone.utc).isoformat(),
                'source_qfx_sha256': digest, 'qfx_name': qfx.name,
                'source_script_sha256': sha256(template),
                'partition': args.partition, 'runs': []}
    for n in args.cores:
        directory = root / ('np%d' % n)
        directory.mkdir()
        shutil.copy2(qfx, directory / qfx.name)
        if sha256(directory / qfx.name) != digest:
            raise ValueError('复制后工程哈希不符：' + str(directory))
        job_name = '%s_%d' % (args.job_prefix, n)
        directives = ['#SBATCH --job-name=' + job_name,
                      '#SBATCH --partition=' + args.partition, '#SBATCH --nodes=1',
                      '#SBATCH --ntasks=%d' % n, '#SBATCH --ntasks-per-node=%d' % n,
                      '#SBATCH --cpus-per-task=1', '#SBATCH --output=job_%j.out',
                      '#SBATCH --error=job_%j.err']
        # 使用LF保存，避免Windows CRLF导致计算节点脚本解释失败。
        with (directory / 'submit.sh').open('w', encoding='utf-8', newline='\n') as stream:
            stream.write('\n'.join(base[:1] + directives + base[1:]) + '\n')
        manifest['runs'].append({'cores': n, 'job_id': None,
                                 'directory': directory.name, 'job_name': job_name})
    save_json(root / 'jobs.json', manifest)
    print('已准备目录，尚未提交任何计算：' + str(root))


def load_manifest(root):
    """读取受控作业清单；校验唯一核数与作业号。"""
    data = json.loads((root / 'jobs.json').read_text(encoding='utf-8-sig'))
    cores, ids = set(), set()
    for run in data['runs']:
        n, job = run['cores'], run.get('job_id')
        if not isinstance(n, int) or n < 1 or n in cores:
            raise ValueError('manifest 核数重复或不合法')
        cores.add(n)
        if job is not None:
            job = str(job)
            if not re.fullmatch(r'\d+', job) or job in ids:
                raise ValueError('manifest 作业号重复或不合法')
            ids.add(job)
            run['job_id'] = job
    return data


def register(args):
    """仅登记已经由 Slurm 返回的真实作业号，不允许覆盖旧号。"""
    root = args.root.resolve()
    if not re.fullmatch(r'\d+', args.job_id):
        raise ValueError('job-id 必须为 sbatch 真实返回的数字部分')
    with manifest_lock(root):
        data = load_manifest(root)
        candidates = [run for run in data['runs'] if run['cores'] == args.cores]
        if len(candidates) != 1:
            raise ValueError('未找到唯一匹配核数')
        if candidates[0].get('job_id') is not None:
            raise ValueError('该核数已有作业号，拒绝重复登记/覆盖')
        if any(run.get('job_id') == args.job_id for run in data['runs']):
            raise ValueError('同一作业号不能登记两次')
        candidates[0]['job_id'] = args.job_id
        save_json(root / 'jobs.json', data)
    print('已登记作业号：' + args.job_id)


def child_path(directory, relative):
    """监测和最终场路径仅允许位于当前案例目录内。"""
    candidate = (directory / relative).resolve()
    try:
        candidate.relative_to(directory.resolve())
    except ValueError:
        raise ValueError('路径超出案例目录：' + str(relative))
    return candidate


def monitor(path, column):
    """读取最后一条数值记录；末条异常时不回退到旧正常值。"""
    last = None
    if path.is_file():
        with path.open(encoding='utf-8', errors='replace') as stream:
            for line in stream:
                parts = line.split()
                if not parts:
                    continue
                try:
                    float(parts[0])
                except ValueError:
                    continue
                try:
                    value = float(parts[column - 1])
                    last = value if math.isfinite(value) else None
                except (ValueError, IndexError):
                    last = None
    return last


def collect(args):
    """只读真实调度与日志，结果另存，数值验收与运行证据分开。"""
    root = args.root.resolve()
    manifest = load_manifest(root)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', args.output_prefix):
        raise ValueError('output-prefix 只能是简单文件名前缀')
    targets = [root / (args.output_prefix + suffix) for suffix in ('.json', '.csv', '.sacct.txt')]
    if any(path.exists() for path in targets):
        raise ValueError('报告已存在，使用新的 output-prefix')
    ids = [run['job_id'] for run in manifest['runs'] if run.get('job_id')]
    accounting, raw = {}, ''
    if ids:
        result = subprocess.run(['sacct', '-X', '-n', '-P', '-j', ','.join(ids),
                                 '--format=JobIDRaw,State,ElapsedRaw,ExitCode,AllocCPUS,NodeList,NNodes'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, timeout=60)
        if result.returncode:
            raise RuntimeError('sacct 查询失败：' + result.stderr)
        raw = result.stdout
        for line in raw.splitlines():
            parts = line.strip().split('|')
            if len(parts) >= 7:
                accounting[parts[0]] = parts
    rows = []
    for run in manifest['runs']:
        n, job = run['cores'], run.get('job_id')
        directory = Path(run['directory'])
        directory = directory if directory.is_absolute() else root / directory
        directory = directory.resolve()
        info = accounting.get(job, [job, 'UNKNOWN' if job else 'NOT_SUBMITTED', '', '', '', '', ''])
        row = {'cores': n, 'job_id': job, 'state': info[1], 'exit_code': info[3],
               'job_elapsed_s': int(info[2]) if info[2].isdigit() else None,
               'allocated_cpus': int(info[4]) if info[4].isdigit() else None,
               'node': info[5], 'physical_nodes': int(info[6]) if info[6].isdigit() else None}
        qfx = child_path(directory, manifest.get('qfx_name', args.case_name + '.qfx'))
        row['input_hash_matches'] = qfx.is_file() and sha256(qfx) == manifest['source_qfx_sha256']
        log_dir = directory / 'logs' / ('job_' + str(job))
        logs = list(log_dir.glob('*_np%d_job%s.log' % (n, job))) if job else []
        log = logs[0].read_text(encoding='utf-8', errors='replace') if len(logs) == 1 else ''
        timings = re.findall(r'EqnSolveInfo timer for (\d+) iterations[^\n]*\n(.*?)(?=EqnSolveInfo timer|\Z)', log, re.S)
        timing = None
        if timings:
            match = re.search(r'Total wall time\(s\):\s*([\d.eE+-]+)', timings[-1][1])
            if match:
                seconds = float(match.group(1))
                count = int(timings[-1][0])
                if math.isfinite(seconds) and seconds > 0 and count > 0:
                    timing = (count, seconds)
        row['iterations'] = timing[0] if timing else None
        row['solver_wall_s'] = timing[1] if timing else None
        row['seconds_per_iteration'] = timing[1] / timing[0] if timing else None
        row['residual_converged'] = 'Convergent: Residual' in log
        row['nonfinite_in_solver_log'] = bool(re.search(r'(?i)(?<![\w.])(?:nan|[+-]?inf(?:inity)?)(?![\w.])', log))
        row['final_data'], row['final_data_sha256'] = None, None
        if timing:
            # 精确按最后迭代数定位，不能用最近修改的文件代替最终结果。
            relative = 'dat/' + args.final_pattern.format(case=args.case_name, iteration=timing[0])
            final = child_path(directory, relative)
            if final.is_file() and final.stat().st_size > 0:
                row['final_data'], row['final_data_sha256'] = str(final), sha256(final)
        row['mass_imbalance_percent'], row['pressure_drop_Pa'] = None, None
        row['requested_monitor_data_valid'] = True
        for kind, inlet, outlet in [('mass', args.mass_in, args.mass_out),
                                      ('pressure', args.pressure_in, args.pressure_out)]:
            if inlet and outlet:
                mi = monitor(child_path(directory, inlet), args.monitor_column)
                mo = monitor(child_path(directory, outlet), args.monitor_column)
                if mi is None or mo is None or (kind == 'mass' and mi == 0):
                    row['requested_monitor_data_valid'] = False
                if mi is not None and mo is not None:
                    if kind == 'mass' and mi != 0:
                        value = abs(mi + mo) / abs(mi) * 100
                        row['mass_imbalance_percent'] = value if math.isfinite(value) else None
                        row['requested_monitor_data_valid'] &= math.isfinite(value)
                    elif kind == 'pressure':
                        value = mi - mo
                        row['pressure_drop_Pa'] = value if math.isfinite(value) else None
                        row['requested_monitor_data_valid'] &= math.isfinite(value)
        row['performance_eligible'] = bool(info[1] == 'COMPLETED' and info[3] == '0:0'
            and row['allocated_cpus'] == n and row['physical_nodes'] == 1
            and row['input_hash_matches'] and row['final_data'] and timing
            and row['residual_converged'] and not row['nonfinite_in_solver_log']
            and row['requested_monitor_data_valid'])
        # 未配置监测不能视作守恒通过；此处仅报告基础执行证据。
        row['physics_acceptance'] = 'REQUIRES_FIELD_AND_MONITOR_REVIEW'
        rows.append(row)
    valid = [row for row in rows if row['performance_eligible']]
    baseline = min(valid, key=lambda row: row['cores']) if valid else None
    for row in rows:
        speedup = baseline['seconds_per_iteration'] / row['seconds_per_iteration'] if baseline and row['performance_eligible'] else None
        row['iteration_speedup'] = speedup
        row['relative_efficiency_percent'] = speedup * baseline['cores'] / row['cores'] * 100 if speedup is not None else None
    report = {'collected_at': datetime.now(timezone.utc).isoformat(),
              'baseline_cores': baseline['cores'] if baseline else None,
              'monitor_inputs': {'mass_in': args.mass_in, 'mass_out': args.mass_out,
                                 'pressure_in': args.pressure_in, 'pressure_out': args.pressure_out,
                                 'column_one_based': args.monitor_column},
              'scope': '单节点基础执行与计时证据；物理精度需独立验收；未下载场文件', 'runs': rows}
    save_json(targets[0], report)
    with targets[1].open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ['cores'])
        writer.writeheader()
        writer.writerows(rows)
    with targets[2].open('x', encoding='utf-8') as stream:
        stream.write(raw)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


def main():
    """集中定义全部可调参数；业务错误以非零退出码与明确说明返回。"""
    parser = argparse.ArgumentParser(description=__doc__)
    # 集群系统Python可能仍为3.6；不用3.7才加入的required参数。
    commands = parser.add_subparsers(dest='command')
    prep = commands.add_parser('prepare', help='新建隔离目录，不提交计算')
    prep.add_argument('--root', type=Path, required=True)
    prep.add_argument('--qfx', type=Path, required=True)
    prep.add_argument('--template', type=Path, required=True)
    prep.add_argument('--partition', required=True)
    prep.add_argument('--cores', type=int, nargs='+', required=True)
    prep.add_argument('--job-prefix', required=True)
    prep.set_defaults(handler=prepare)
    reg = commands.add_parser('register', help='登记真实作业号，拒绝重复')
    reg.add_argument('--root', type=Path, required=True)
    reg.add_argument('--cores', type=int, required=True)
    reg.add_argument('--job-id', required=True)
    reg.set_defaults(handler=register)
    col = commands.add_parser('collect', help='在集群读取sacct与已有结果，不提交计算')
    col.add_argument('--root', type=Path, required=True)
    col.add_argument('--case-name', required=True)
    col.add_argument('--output-prefix', default='report')
    col.add_argument('--final-pattern', default='{case}-{iteration:05d}.dat')
    col.add_argument('--mass-in', help='相对案例目录的入口有符号流量监测文件')
    col.add_argument('--mass-out', help='相对案例目录的出口有符号流量监测文件')
    col.add_argument('--pressure-in', help='相对案例目录的入口压力监测文件')
    col.add_argument('--pressure-out', help='相对案例目录的出口压力监测文件')
    col.add_argument('--monitor-column', type=int, default=2, help='监测数值列，1基')
    col.set_defaults(handler=collect)
    args = parser.parse_args()
    if args.command is None:
        parser.error('请选择 prepare、register 或 collect')
    if args.command == 'collect':
        if args.monitor_column < 1:
            parser.error('monitor-column 必须大于等于1')
        if bool(args.mass_in) != bool(args.mass_out) or bool(args.pressure_in) != bool(args.pressure_out):
            parser.error('监测文件必须成对提供')
    try:
        args.handler(args)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print('错误：' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

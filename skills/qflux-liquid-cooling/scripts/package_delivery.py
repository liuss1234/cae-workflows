# -*- coding: utf-8 -*-
"""用明确白名单打包案例，生成 SHA256 清单并执行 ZIP CRC 检查。"""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

ROOT_SUFFIXES={'.py','.ps1','.FCMacro','.FCStd','.step','.cgns','.msh','.npz','.md'}
ROOT_JSON={'workflow.json','case_parameters.json','mesh_check.json','cad_check.json','setup_check.json','readback_check.json','readback_settings.json'}
DIRECTORIES={'run','run_stable','run_robust','post','results_summary'}


def sha256(path):
    """分块摘要适用于大网格/场文件。"""
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):value.update(block)
    return value.hexdigest()


def main():
    """未收敛可交付阶段包，但不允许冒称最终收敛案例。"""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--allow-incomplete',action='store_true')
    args=parser.parse_args();root=Path(args.case).resolve();output=Path(args.output).resolve()
    if output.exists():raise FileExistsError('压缩包已存在，禁止覆盖')
    summary_path=root/'results_summary/simulation_summary.json'
    summary=json.loads(summary_path.read_text(encoding='utf-8')) if summary_path.exists() else {}
    if not args.allow_incomplete:
        if not summary.get('convergence_checks_passed'):raise RuntimeError('未通过收敛检查')
        check=json.loads((root/'readback_check.json').read_text(encoding='utf-8'))
        if not check.get('passed') or not check.get('source_data'):raise RuntimeError('未通过最终场回读')
        if Path(check['source_qfx']).resolve()!=Path(summary['source_qfx']).resolve() or (root/check['source_data']).resolve()!=Path(summary['source_data']).resolve():raise RuntimeError('回读与报告来源不一致')
    files=[]
    for path in root.iterdir():
        if path.is_file() and (path.suffix in ROOT_SUFFIXES or path.name in ROOT_JSON or path.name in ['parallel_cooling.qfx','parallel_cooling_stable.qfx','parallel_cooling_robust.qfx','settings.json','settings_stable.json','settings_robust.json']):files.append(path)
    for directory in DIRECTORIES:
        for path in (root/directory).rglob('*'):
            if path.is_file() and not any(part in {'tmp','__pycache__'} for part in path.relative_to(root).parts) and path.suffix in {'.dat','.png','.csv','.json','.log','.vtu','.vtm'}:files.append(path)
    files=sorted(set(files))
    manifest={'converged':bool(summary.get('convergence_checks_passed')),'files':[{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':sha256(p)} for p in files]}
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED,compresslevel=5) as archive:
        for path in files:archive.write(path,root.name+'/'+path.relative_to(root).as_posix())
        archive.writestr(root.name+'/package_manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():raise RuntimeError('ZIP CRC 校验失败')
    print(json.dumps({'zip':str(output),'bytes':output.stat().st_size,'files':len(files),'CRC_verified':True},ensure_ascii=False))


if __name__=='__main__':main()

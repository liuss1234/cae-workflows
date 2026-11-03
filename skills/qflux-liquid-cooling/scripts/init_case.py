# -*- coding: utf-8 -*-
"""初始化独立工作目录：不覆盖已有目录，不运行求解或连接远程。"""
from pathlib import Path
import argparse
import json
import shutil
import sys

SKILL = Path(__file__).resolve().parent.parent


def main():
    """从技能资源复制纯文本模板及统一参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='尚不存在的新案例目录')
    parser.add_argument('--config', help='可选的 workflow JSON；不自动连接其中主机')
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        raise FileExistsError('保护已有文件，目标目录必须不存在：' + str(output))
    config = Path(args.config).resolve() if args.config else SKILL/'assets/workflow.example.json'
    json.loads(config.read_text(encoding='utf-8-sig'))
    shutil.copytree(SKILL/'assets/case-template', output, ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copy2(config, output/'workflow.json')
    for name in ['run_solver.ps1','verify_case.py','write_report.py']:
        shutil.copy2(SKILL/'scripts'/name, output/name)
    print(json.dumps({'case_directory':str(output),'next':'编辑 workflow.json，再执行环境检查和 build_case.py'},ensure_ascii=False))


if __name__ == '__main__':
    try:main()
    except Exception as exc:
        print(str(exc),file=sys.stderr);sys.exit(1)

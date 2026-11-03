# -*- coding: utf-8 -*-
"""每台电脑在 workflow.json 或环境变量中设置软件位置。"""
from pathlib import Path
import json
import os
import sys
ROOT = Path(__file__).resolve().parent


def read_config():
    """读取工作副本配置，拒绝在模板目录直接执行。"""
    path = ROOT / 'workflow.json'
    if not path.is_file():
        raise RuntimeError('先用 init_case.py 创建工作副本，再编辑 workflow.json')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def qflux_home():
    """环境变量优先，不猜测安装目录。"""
    value = os.environ.get('QFLUX_HOME') or read_config()['software']['qflux_home']
    if not value:
        raise RuntimeError('请配置 QFLUX_HOME 或 software.qflux_home')
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise FileNotFoundError('QFlux 目录不存在：' + str(path))
    return path


def bootstrap_qflux():
    """加载匹配的 API；调用方保留 DLL 目录句柄。"""
    path = qflux_home()
    if os.name != 'nt':
        raise RuntimeError('QFlux 原生阶段仅验证过 Windows；Linux 需适配厂商库和 API')
    sys.path.insert(0, str(path))
    os.environ['PATH'] = str(path) + os.pathsep + os.environ.get('PATH', '')
    return os.add_dll_directory(str(path))


def extra_python_paths():
    """复用已安装依赖目录，不携带二进制。"""
    return [str(Path(p).expanduser().resolve()) for p in read_config()['software']['extra_python_paths']]

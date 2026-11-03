# -*- coding: utf-8 -*-
"""跨平台通用配置、路径和散列工具；不导入任何厂商原生模块。"""
from pathlib import Path
import hashlib
import json
import os
import sys

# 所有工程参数在 case.json，软件参数在 environment.json；以下为文件约定。
CASE_FILE = "case.json"
ENVIRONMENT_FILE = "environment.json"


def read_json(path):
    """兼容 UTF-8 和带 BOM 的 PowerShell JSON。"""
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_json(path, value):
    """写结构化记录；调用者须先确认目标可以写入。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def inside(root, name):
    """只允许案例内的相对路径，防止误写上级目录或通过符号链接越界。"""
    root = Path(root).resolve()
    path = (root / name).resolve()
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise ValueError("路径超出案例目录：" + str(name))
    if not relative.parts:
        raise ValueError("需要文件或子目录，不能使用案例根目录")
    return path


def context(case, environment=None):
    """加载案例与可选机器配置；环境文件相对路径以案例目录为基准。"""
    root = Path(case).resolve()
    cfg = read_json(root / CASE_FILE)
    env_path = Path(environment) if environment else root / ENVIRONMENT_FILE
    env_path = (env_path if env_path.is_absolute() else root / env_path).resolve()
    env = read_json(env_path) if env_path.is_file() else {}
    home = os.environ.get("QFLUX_HOME") or env.get("qflux_home", "")
    if home:
        env["qflux_home"] = str(Path(home).expanduser().resolve())
    return root, cfg, env


def add_build_paths(env):
    """为普通 Python 添加可选模块路径，不修改用户系统环境。"""
    for path in reversed(env.get("extra_python_paths", [])):
        sys.path.insert(0, str(Path(path).expanduser().resolve()))


def sha256(path):
    """流式计算大文件 SHA256，避免把 DAT 全部读入内存。"""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def exclusive_directory(path):
    """创建新阶段目录，已有结果一律不覆盖。"""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=False)
    return path

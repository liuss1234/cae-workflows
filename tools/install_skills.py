# -*- coding: utf-8 -*-
"""把技能目录安装到本机 Codex 或 DeepSeek Harness 的技能目录，保留技能内部相对结构。"""
from pathlib import Path
import argparse
import os
import re
import shutil
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
SKILLS_PATH = REPOSITORY / "skills"
# 目标宿主：优先读取环境变量，未设置时使用用户目录下的默认位置。
TARGET_HOMES = {
    "codex": ("CODEX_HOME", ".codex"),
    "dsh": ("DSH_HOME", ".dsh"),
}
FRONTMATTER_PATTERN = re.compile(r"\A---\s*\n(.*?)\n---(?:\s*\n|$)", re.DOTALL)
NAME_PATTERN = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)


def read_skill_name(directory):
    """读取 SKILL.md 头部的 name，供安装前核对目录名。"""
    path = Path(directory) / "SKILL.md"
    if not path.is_file():
        raise ValueError("技能缺少 SKILL.md：%s" % Path(directory).name)
    match = FRONTMATTER_PATTERN.match(path.read_text(encoding="utf-8-sig"))
    if not match:
        raise ValueError("技能缺少标准 YAML 头部：%s" % Path(directory).name)
    name = NAME_PATTERN.search(match.group(1))
    if not name:
        raise ValueError("技能缺少 name 字段：%s" % Path(directory).name)
    return name.group(1).strip().strip('"').strip("'")


def available_skills():
    """列出仓库中带 SKILL.md 的技能目录。"""
    return sorted(path.name for path in SKILLS_PATH.iterdir() if (path / "SKILL.md").is_file())


def resolve_root(target, override=None):
    """返回目标技能目录：--root 优先，其次宿主环境变量，最后用户目录默认值。"""
    if override:
        return Path(override).expanduser()
    variable, default_name = TARGET_HOMES[target]
    home = os.environ.get(variable)
    base = Path(home).expanduser() if home else Path.home() / default_name
    return base / "skills"


def install(names, root, force=False, dry_run=False):
    """复制指定技能到 root；默认跳过同名目录，force 时先删除再复制。"""
    root = Path(root)
    installed = []
    for name in names:
        source = SKILLS_PATH / name
        if not source.is_dir():
            raise ValueError("未知技能：%s（可用：%s）" % (name, ", ".join(available_skills())))
        if read_skill_name(source) != name:
            raise ValueError("技能目录名与 SKILL.md 的 name 不一致：%s" % name)
        destination = root / name
        if destination.exists() and not force:
            print("已存在，跳过（使用 --force 覆盖）：%s" % destination)
            continue
        if dry_run:
            print("将安装：%s -> %s" % (name, destination))
            installed.append(name)
            continue
        root.mkdir(parents=True, exist_ok=True)
        if destination.is_dir():
            shutil.rmtree(destination)
        elif destination.exists():
            destination.unlink()
        shutil.copytree(source, destination)
        print("已安装：%s -> %s" % (name, destination))
        installed.append(name)
    return installed


def main(argv=None):
    parser = argparse.ArgumentParser(description="安装技能到本机 Codex 或 DeepSeek Harness 的技能目录。")
    parser.add_argument("--target", choices=sorted(TARGET_HOMES), required=True, help="目标宿主")
    parser.add_argument("--skill", action="append", dest="skills", metavar="NAME", help="只安装指定技能，可重复")
    parser.add_argument("--root", help="直接指定技能目录，覆盖 --target 的默认路径")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的同名技能")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的操作")
    arguments = parser.parse_args(argv)
    root = resolve_root(arguments.target, arguments.root)
    names = arguments.skills or available_skills()
    try:
        installed = install(names, root, force=arguments.force, dry_run=arguments.dry_run)
    except ValueError as error:
        print("安装失败：%s" % error, file=sys.stderr)
        return 1
    print("目标目录：%s；完成 %d 个技能" % (root, len(installed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

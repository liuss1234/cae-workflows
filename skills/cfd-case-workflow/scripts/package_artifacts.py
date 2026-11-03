# -*- coding: utf-8 -*-
"""按显式文件清单打包或校验交付物，包含 ZIP CRC 与逐文件 SHA256。"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import sys
import zipfile
from cfd_common import inside, read_json, sha256

# 不打包本机路径配置和软件/凭据；技能环境示例 environment.example.json 可以交付。
MANIFEST_NAME = "_package_manifest.json"
BLOCKED_SUFFIXES = {".exe", ".dll", ".pyd", ".pem", ".key"}


def safe_name(name):
    """检查 ZIP 名称，拒绝绝对路径、驱动器、反斜线和目录穿越。"""
    path = PurePosixPath(name)
    if not name or "\\" in name or ":" in name or path.is_absolute() or ".." in path.parts or str(path) != name:
        raise ValueError("不安全或非规范 ZIP 路径：" + name)
    return name


def verify(path):
    """不解压即可校验全部内容，防止把仅能打开的 ZIP 当作完整交付。"""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names) or any(item.is_dir() for item in archive.infolist()):
            raise ValueError("ZIP 条目重复或含未预期目录条目")
        for name in names:
            safe_name(name)
        manifests = [name for name in names if PurePosixPath(name).name == MANIFEST_NAME]
        if len(manifests) != 1:
            raise ValueError("ZIP 需要唯一内容清单")
        manifest = json.loads(archive.read(manifests[0]).decode("utf-8"))
        if set(names) != set(manifest["files"]) | {manifests[0]}:
            raise ValueError("ZIP 实际条目与内容清单不符")
        bad = archive.testzip()
        if bad:
            raise ValueError("ZIP CRC 失败：" + bad)
        for name, record in manifest["files"].items():
            digest = hashlib.sha256()
            size = 0
            with archive.open(name) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
                    size += len(block)
            if digest.hexdigest() != record["sha256"] or size != record["bytes"]:
                raise ValueError("文件内容校验失败：" + name)
        return {"passed": True, "files": len(manifest["files"]), "crc": "passed", "sha256": sha256(path)}


def main():
    """创建新包后立即回读；不压缩整个桌面、运行时目录或不明通配文件。"""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("create")
    create.add_argument("--root", required=True, type=Path)
    create.add_argument("--manifest", required=True, type=Path)
    create.add_argument("--output", required=True, type=Path)
    create.add_argument("--prefix", default="", help="例如技能名，形成可直接解压安装的目录")
    check = sub.add_parser("verify")
    check.add_argument("archive", type=Path)
    args = parser.parse_args()
    if args.action == "verify":
        result = verify(args.archive)
    else:
        root = args.root.resolve()
        manifest_path = args.manifest if args.manifest.is_absolute() else root / args.manifest
        spec = read_json(manifest_path)
        prefix = safe_name(args.prefix) + "/" if args.prefix else ""
        files, sources = {}, {}
        if not spec.get("files"):
            raise ValueError("文件清单为空")
        for relative in spec["files"]:
            safe_name(relative)
            source = inside(root, relative)
            if not source.is_file() or source.suffix.lower() in BLOCKED_SUFFIXES or source.name.lower() == "environment.json":
                raise ValueError("文件不存在、属于软件二进制或机器私有配置：" + relative)
            name = prefix + relative
            if name in files or PurePosixPath(name).name == MANIFEST_NAME:
                raise ValueError("重复文件或保留清单名称：" + name)
            files[name] = {"bytes": source.stat().st_size, "sha256": sha256(source)}
            sources[name] = source
        output = args.output.resolve()
        if output.exists() or output.with_suffix(output.suffix + ".sha256").exists():
            raise FileExistsError("输出 ZIP 或哈希文件已存在")
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(files):
                archive.write(sources[name], name)
            archive.writestr(prefix + MANIFEST_NAME, json.dumps({"schema_version": 1, "files": files}, ensure_ascii=False, indent=2))
        result = verify(output)
        # 这是打包程序的正常生成产物，不涉及用户已有文件。
        with output.with_suffix(output.suffix + ".sha256").open("x", encoding="utf-8") as stream:
            stream.write(result["sha256"] + "  " + output.name + "\n")
        result["archive"] = str(output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("打包/校验失败：" + str(exc), file=sys.stderr)
        sys.exit(1)

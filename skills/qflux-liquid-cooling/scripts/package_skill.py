# -*- coding: utf-8 -*-
"""打包纯文本技能资源；排除缓存，记录 SHA256，并检查 CRC。"""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

SKILL=Path(__file__).resolve().parent.parent
ALLOWED={'.md','.py','.ps1','.json','.yaml','.FCMacro'}


def main():
    """ZIP 顶层为技能同名文件夹，可直接放入 Codex skills。"""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args();output=Path(args.output).resolve()
    if output.exists():raise FileExistsError('已有 ZIP 不覆盖，请更换文件名')
    files=sorted(p for p in SKILL.rglob('*') if p.is_file() and p.suffix in ALLOWED and '__pycache__' not in p.parts)
    entries=[{'path':p.relative_to(SKILL).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in files:archive.write(path,SKILL.name+'/'+path.relative_to(SKILL).as_posix())
        archive.writestr(SKILL.name+'/manifest.json',json.dumps({'skill':SKILL.name,'files':entries},ensure_ascii=False,indent=2))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():raise RuntimeError('CRC 检查失败')
        for item in entries:
            if hashlib.sha256(archive.read(SKILL.name+'/'+item['path'])).hexdigest()!=item['sha256']:raise RuntimeError('摘要检查失败')
    print(json.dumps({'zip':str(output),'bytes':output.stat().st_size,'files':len(files)+1,'CRC_verified':True,'SHA256_verified':True},ensure_ascii=False))


if __name__=='__main__':main()

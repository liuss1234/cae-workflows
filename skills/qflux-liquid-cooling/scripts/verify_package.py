# -*- coding: utf-8 -*-
"""只读核验技能包/案例包的 ZIP CRC 及逐文件 SHA256，不解压执行。"""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile


def main():
    """同时识别技能 manifest.json 与案例 package_manifest.json。"""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip_path')
    args=parser.parse_args()
    with zipfile.ZipFile(Path(args.zip_path)) as archive:
        if archive.testzip():raise RuntimeError('ZIP CRC 校验失败')
        candidates=[n for n in archive.namelist() if n.endswith('/manifest.json') or n.endswith('/package_manifest.json')]
        if len(candidates)!=1:raise ValueError('应只有一个包内清单')
        name=candidates[0];prefix=name.rsplit('/',1)[0]+'/'
        manifest=json.loads(archive.read(name).decode('utf-8'))
        for item in manifest['files']:
            path=item['path']
            if path.startswith('/') or '..' in Path(path).parts:raise ValueError('清单路径不合法')
            digest=hashlib.sha256()
            with archive.open(prefix+path) as stream:
                for block in iter(lambda:stream.read(4*1024*1024),b''):digest.update(block)
            if digest.hexdigest()!=item['sha256'].lower():raise RuntimeError('摘要不一致：'+path)
        print(json.dumps({'verified':True,'files':len(manifest['files']),'CRC':True,'SHA256':True}))


if __name__=='__main__':main()

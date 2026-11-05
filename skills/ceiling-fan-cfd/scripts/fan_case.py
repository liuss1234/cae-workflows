# -*- coding: utf-8 -*-
"""吊扇案例初始化、参数核验、显式命令运行及带哈希的交付工具。"""
import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

# 所有默认路径相对技能目录；业务参数来自case.json，不内置用户机器路径。
SKILL = Path(__file__).resolve().parents[1]
CONFIG_REL = Path('03日志脚本/03工况配置/case.json')
TOP_DIRS = ('01模型文件', '02工程及计算结果文件', '03日志脚本')
BLOCKED_SUFFIXES = {'.exe', '.dll', '.key', '.pem', '.pfx', '.lic', '.pyc'}
BLOCKED_NAMES = {'environment.json', '.env', 'id_rsa', 'id_ed25519', 'credentials', '.git-credentials'}


def read_json(path):
    """兼容UTF-8 BOM配置。"""
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, data):
    """保存结构化证据。"""
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf8')


def digest(path):
    """大文件分块计算SHA256，不全量加载。"""
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def positive(value, name):
    """排除空、布尔、非有限及非正输入。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(name+'必须为有限正数')
    return float(value)


def validate_config(cfg):
    """核对工况并推导角速度、检测面及首层理论厚度。"""
    if cfg.get('schema_version') != 1:raise ValueError('不支持的配置版本')
    if cfg['units']['cad'] not in ('mm', 'm') or cfg['units']['mesh'] != 'm':raise ValueError('需显式CAD单位及m制网格')
    rpm = positive(cfg['operating']['rpm'], 'rpm')
    direction = cfg['operating']['direction_viewed_from_plus_z']
    if direction not in ('clockwise', 'counterclockwise'):raise ValueError('需明确从+Z看的转向')
    diameter = positive(cfg['geometry']['swept_diameter_m'], 'swept_diameter_m')
    room = cfg['room'];outer = positive(room['outer_width_m'], 'outer_width_m')
    inner = positive(room['inner_width_m'], 'inner_width_m');height = positive(room['height_m'], 'height_m')
    if not diameter < inner < outer:raise ValueError('需满足扫掠直径<内屏宽<外室宽')
    if not 0 <= room['screen_bottom_m'] < room['screen_top_m'] <= height:raise ValueError('内屏高度范围不正确')
    if not 0 < cfg['geometry']['blade_reference_z_m'] < height:raise ValueError('安装基准应在室内')
    measurement = cfg['measurement'];offset = measurement['diameter_offset_m']
    if not isinstance(offset, (int, float)) or not math.isfinite(offset) or offset < 0:raise ValueError('检测面偏置不合法')
    if not 0 < measurement['height_above_floor_m'] < height or diameter+offset >= outer:raise ValueError('检测面超出房间')
    if measurement['normal'] != [0., 0., -1.]:raise ValueError('当前向下风量适配要求法向-Z')
    origin = cfg['operating']['axis_origin_m']
    if len(origin) != 3 or not all(isinstance(x,(float,int)) and math.isfinite(x) for x in origin):raise ValueError('轴原点不合法')
    mesh = cfg['mesh'];layers = mesh['blade_layers'];growth = positive(mesh['growth'], 'growth')
    if isinstance(layers,bool) or not isinstance(layers,int) or layers < 1:raise ValueError('层数应为正整数')
    for key in ('base_size_m','blade_size_m','blade_min_size_m','blade_total_thickness_m','fixed_size_m','hub_size_m','hub_thickness_m','interface_size_m','interface_min_size_m'):
        positive(mesh[key],key)
    if mesh['blade_min_size_m']>mesh['blade_size_m'] or mesh['interface_min_size_m']>mesh['interface_size_m']:raise ValueError('最小网格尺寸大于目标')
    accepted = cfg['acceptance']['blade_full_layer_min_fraction']
    if isinstance(accepted,bool) or not isinstance(accepted,(float,int)) or not 0 < accepted <= 1:raise ValueError('需填写本次实际接受的层覆盖率')
    for key in ('cores','iterations','save_interval'):
        value=cfg['solver'][key]
        if isinstance(value,bool) or not isinstance(value,int) or value<1:raise ValueError(key+'应为正整数')
    if cfg['solver']['save_interval'] > cfg['solver']['iterations']:raise ValueError('保存间隔超过总步数')
    if not isinstance(cfg['solver'].get('run_full_iterations',False),bool):raise ValueError('run_full_iterations应为布尔值')
    for key,value in cfg['fluid'].items():positive(value,key)
    first = mesh['blade_total_thickness_m']/(layers if abs(growth-1)<1e-12 else (growth**layers-1)/(growth-1))
    return dict(passed=True, omega_vector_rad_s=[0.,0.,rpm*math.pi/30*(-1 if direction=='clockwise' else 1)],
                measurement_diameter_m=diameter+offset, measurement_area_m2=math.pi*((diameter+offset)/2)**2,
                first_layer_theoretical_m=first, note='参数一致性检查，不证明网格或物理有效')


def initialize(case, source):
    """创建全新案例，保留源件；不猜未知工况。"""
    case=Path(case).resolve();source=Path(source).resolve()
    if not source.is_file():raise FileNotFoundError(source)
    if case.exists():raise FileExistsError('案例目录已存在，拒绝覆盖')
    for name in TOP_DIRS:(case/name).mkdir(parents=True)
    original=case/'01模型文件/01原始模型'/source.name;original.parent.mkdir();shutil.copy2(source,original)
    cfg=read_json(SKILL/'assets/case.example.json');cfg['case_id']=case.name
    cfg['source']=dict(file=original.relative_to(case).as_posix(),sha256=digest(original),original_name=source.name)
    write_json(case/CONFIG_REL,cfg)
    return dict(case=str(case),config=str(case/CONFIG_REL),source_sha256=cfg['source']['sha256'])


def safe_file(root, relative):
    """只接受案例内规范相对路径，拒绝软链接和私有运行时。"""
    text=str(relative)
    p=PurePosixPath(text)
    if '\\' in text or ':' in text or p.is_absolute() or not p.parts or '..' in p.parts or text != p.as_posix():raise ValueError('非法相对路径：'+text)
    current=root
    for part in p.parts:
        current=current/part
        if current.is_symlink():raise ValueError('不打包软链接')
    target=current.resolve()
    if root not in target.parents or not target.is_file():raise ValueError('文件越界或不存在：'+text)
    if target.suffix.lower() in BLOCKED_SUFFIXES or any(x.lower() in BLOCKED_NAMES or x.lower()=='.git' for x in p.parts):raise ValueError('不交付凭据、许可证或软件运行时')
    return target


def pack(case, manifest, output):
    """显式文件清单打包；ZIP内含逐文件大小及哈希。"""
    root=Path(case).resolve();out=Path(output).resolve();rows=[]
    if out.exists():raise FileExistsError(out)
    names=read_json(manifest)['files']
    if not names or len(set(names))!=len(names) or 'SHA256.json' in names:raise ValueError('清单空、重复或使用保留名')
    sources=[]
    for name in names:
        path=safe_file(root,name)
        if path==out:raise ValueError('不能打包输出文件自身')
        sources.append((name,path));rows.append(dict(path=name,bytes=path.stat().st_size,sha256=digest(path)))
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('xb') as raw:
        with zipfile.ZipFile(raw,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,path in sources:archive.write(path,name)
            archive.writestr('SHA256.json',json.dumps(rows,ensure_ascii=False,indent=2))
    verify(out)
    return dict(passed=True,files=len(rows),archive=out.name,sha256=digest(out))


def verify(archive):
    """不解压地校验所有ZIP条目和CRC；拒绝多余项、重复与路径穿越。"""
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(set(names))!=len(names) or z.testzip() is not None:raise ValueError('重复条目或CRC损坏')
        for name in names:
            p=PurePosixPath(name)
            if '\\' in name or ':' in name or p.is_absolute() or '..' in p.parts or p.as_posix()!=name:raise ValueError('ZIP路径不合法')
        rows=json.loads(z.read('SHA256.json'))
        if len(rows)!=len({r['path'] for r in rows}) or set(names)!={r['path'] for r in rows}|{'SHA256.json'}:raise ValueError('ZIP清单与内容不一致')
        for r in rows:
            h=hashlib.sha256();size=0
            with z.open(r['path']) as f:
                for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block);size+=len(block)
            if size!=r['bytes'] or h.hexdigest()!=r['sha256']:raise ValueError('文件哈希不一致：'+r['path'])
    return dict(passed=True,files=len(rows))


def run_manifest(path, execute):
    """只执行用户显式命令数组，不将参数拼接为shell。"""
    cfg=read_json(path);commands=cfg['commands']
    if not commands or any(not isinstance(c,list) or not c or not all(isinstance(x,str) for x in c) for c in commands):raise ValueError('commands需为非空字符串数组列表')
    if not execute:return dict(executed=False,commands=commands)
    log=Path(cfg['log']);log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('xb') as stream:
        for command in commands:subprocess.run(command,cwd=cfg['cwd'],stdout=stream,stderr=subprocess.STDOUT,check=True)
    return dict(executed=True,completed_commands=len(commands))


def main():
    """子命令入口；异常明确返回非零，避免把尝试当完成。"""
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    s=sub.add_parser('init');s.add_argument('--case',required=True);s.add_argument('--source',required=True)
    s=sub.add_parser('validate');s.add_argument('--case',required=True)
    s=sub.add_parser('pack');s.add_argument('--case',required=True);s.add_argument('--manifest',required=True);s.add_argument('--output',required=True)
    s=sub.add_parser('verify');s.add_argument('--archive',required=True)
    s=sub.add_parser('run');s.add_argument('--manifest',required=True);s.add_argument('--execute',action='store_true')
    a=p.parse_args()
    if a.action=='init':result=initialize(a.case,a.source)
    elif a.action=='validate':result=validate_config(read_json(Path(a.case)/CONFIG_REL))
    elif a.action=='pack':result=pack(a.case,a.manifest,a.output)
    elif a.action=='verify':result=verify(a.archive)
    else:result=run_manifest(a.manifest,a.execute)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    except Exception as exc:print(type(exc).__name__+': '+str(exc),file=sys.stderr);sys.exit(1)

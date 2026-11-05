# -*- coding: utf-8 -*-
"""由本案例参数与已验收多面体报告构建QFlux配置，不读取旧型号参数。"""
import argparse
import copy
import json
import sys
from pathlib import Path
from fan_case import CONFIG_REL,SKILL,read_json,write_json,validate_config,digest


def make(case, quality, mesh, target, result_dir, output):
    """路径显式指定；源网格哈希匹配验收记录后才生成设置。"""
    cfg=read_json(Path(case)/CONFIG_REL);derived=validate_config(cfg);q=read_json(quality)
    if not q.get('passed') or digest(mesh)!=q.get('mesh_sha256'):raise ValueError('网格验收记录或哈希不符')
    if len(q['zones'])!=2 or sum(r['cells'] for r in q['zones'].values())!=q['cells_total']:raise ValueError('双区网格单元统计不一致')
    semantic={}
    for name,row in q['zones'].items():
        kind='fluid_rotating' if 'rotating' in name else 'fluid_stationary' if 'stationary' in name else None
        if kind is None or kind in semantic:raise ValueError('网格区语义不唯一')
        semantic[kind]=row['cells']
    out=copy.deepcopy(read_json(SKILL/'assets/qflux.setup.example.json'))
    out.update(model=cfg['case_id'],rpm=cfg['operating']['rpm'],qflux_run=str(Path(result_dir).resolve()))
    out['mesh']=dict(source_cgns=str(Path(mesh).resolve()),sha256=digest(mesh),cells=q['cells_total'],
        zone_cells=semantic,zone_names_cells={n:r['cells'] for n,r in q['zones'].items()})
    out['files']['QFlux']=str(Path(target).resolve())
    out['names']=dict(QFlux=Path(target).stem,rotor='rotor_%grpm'%cfg['operating']['rpm'])
    out['physics'].update(omega_rad_s=derived['omega_vector_rad_s'][2],axis_origin_m=cfg['operating']['axis_origin_m'],
        temperature_K=cfg['fluid']['temperature_K'],density_kg_m3=cfg['fluid']['density_kg_m3'],viscosity_Pa_s=cfg['fluid']['viscosity_Pa_s'])
    out['boundaries']=sorted({n for r in q['zones'].values() for n in r['boundaries']})
    out['solver'].update(cores=cfg['solver']['cores'],max_iterations=cfg['solver']['iterations'],save_interval=cfg['solver']['save_interval'],run_full_iterations=cfg['solver'].get('run_full_iterations',False))
    out['measurement'].update(name='measurement_signed_volume_flux',
        height_above_floor_m=cfg['measurement']['height_above_floor_m'],diameter_offset_m=cfg['measurement']['diameter_offset_m'],
        center_m=[0.,0.,cfg['measurement']['height_above_floor_m']],normal=cfg['measurement']['normal'],
        radius_m=derived['measurement_diameter_m']/2,diameter_m=derived['measurement_diameter_m'])
    path=Path(output)
    if path.exists():raise FileExistsError(path)
    write_json(path,out);return out


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['case','quality','mesh','target','result-dir','output']:p.add_argument('--'+key,required=True)
    a=p.parse_args()
    try:
        make(a.case,a.quality,a.mesh,a.target,a.result_dir,a.output);print('QFLUX_CONFIG_CREATED')
    except Exception as exc:print(str(exc),file=sys.stderr);sys.exit(1)

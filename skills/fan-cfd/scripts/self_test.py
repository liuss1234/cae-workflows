# -*- coding: utf-8 -*-
"""普通 Python 合成数据自检：验证失败路径和工程不变量，不模拟风扇物理性能。"""
import argparse
import copy
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from fan_case import TEMPLATE, check_mesh, config_hash, digest, load_case, read_json, validate_config, write_json
from analyze_history import analyze
from qflux_verify import verify_settings

# 自检专用参数：小型人工数据，不是行业推荐工况或生产质量证据。
SCRIPTS = Path(__file__).resolve().parent


def fixture(root):
    """创建可校验配置与人工证据，客户 CAD 和商业库均不参与此单元自检。"""
    root.mkdir(parents=True)
    (root/'01_geometry').mkdir(); (root/'02_mesh').mkdir()
    source = root/'01_geometry/synthetic.txt'; source.write_text('synthetic metadata only',encoding='utf8')
    mesh = root/'02_mesh/mesh.cgns'; mesh.write_bytes(b'synthetic gate fixture; not CGNS')
    cfg = read_json(TEMPLATE)
    cfg['source'] = {'file':'01_geometry/synthetic.txt','sha256':digest(source)}
    cfg['geometry']['diameter_m'] = .1
    cfg['mesh']['sha256'] = digest(mesh); cfg['mesh']['bbox_tolerance_m'] = 1e-9
    cfg['mesh']['limits'].update(max_nonorth_deg=80.,max_volume_error_fraction=.01)
    for i,(name,z) in enumerate(cfg['mesh']['zones'].items()):
        z.update(cells=2,bbox_m=[0.,0.,float(i),1.,1.,float(i+1)])
    for group in cfg['mesh']['layer_groups']:
        group.update(requested_layers=2,first_height_m=None,total_thickness_m=.002,growth=1.2,minimum_full_layer_area_fraction=.9)
    cfg['rotation'].update(rpm=60.,omega_rad_s=2*math.pi,view_direction_unit=[0.,0.,1.],sense_from_view='clockwise')
    cfg['physics'].update(density_kg_m3=1.2,viscosity_Pa_s=1.8e-5,temperature_K=300.,reference_pressure_Pa=101325.)
    cfg['solver'].update(cores=1,max_iterations=10,save_interval=5,momentum_scheme='FirstUpwind',nonorth_corrections=2,initial_k_m2_s2=.01,initial_epsilon_m2_s3=.01)
    cfg['solver']['relaxation'].update(pressure=.2,momentum=.4,turbulence=.4)
    evidence = {'producer':'synthetic self-test only','quality_method':'artificial fixture; no CFD quality assertion',
        'mesh_sha256':digest(mesh),'zones':{},'boundaries':{}}
    for name,z in cfg['mesh']['zones'].items():
        evidence['zones'][name] = {'cells':z['cells'],'bbox_m':z['bbox_m'],'cell_types':{'tetra':1,'prism':1},
            'quality':{'nonpositive_cells':0,'invalid_topology_cells':0,'min_volume_m3':1e-9,'max_nonorth_deg':50.,'volume_error_fraction':.001}}
    for name,b in cfg['boundaries'].items():
        evidence['boundaries'][name] = {'zone':b['zone'],'faces':2}
        if b['kind'] == 'wall':
            evidence['boundaries'][name].update(area_m2=1.,layer_count_area_m2={'2':.95,'1':.05},unmatched_area_m2=0.,actual_total_thickness_m={'min':.001,'median':.002,'max':.002})
    write_json(root/'case.json',cfg)
    return cfg,evidence


def settings_fixture(cfg,evidence):
    """构造落盘结构样本，仅用于检验核验逻辑，不能宣称 API 已运行。"""
    zones = [{'id':i,'name':n,'cells':z['cells'],'bbox_m':z['bbox_m']} for i,(n,z) in enumerate(cfg['mesh']['zones'].items())]
    zone_ids = {z['name']:z['id'] for z in zones}
    classes = {'wall':'CBCWall','interface':'CBCInterfaceBoundary','pressure_inlet':'CBCPressInlet','pressure_outlet':'CBCPressOutlet'}
    boundaries = [{'id':i,'name':n,'zone_id':zone_ids[b['zone']],'faces':evidence['boundaries'][n]['faces'],
        'condition_class':classes[b['kind']],'paired':b['kind'] == 'interface','pressure_Pa':b.get('pressure_Pa')} for i,(n,b) in enumerate(cfg['boundaries'].items())]
    ids = {b['name']:b['id'] for b in boundaries}; solver = cfg['solver']
    region = {'material':1,'solver':{'time':1,'energy':False,'turbModel':{'RANS':{'type':2,'subType':2,'wallFunction':3}}},
        'operationCondition':{'gravity':{'on':False},'pressure':{'value':cfg['physics']['reference_pressure_Pa']}},
        'motion':[{'meshMotion':{'zone':[zone_ids[cfg['rotation']['zone']]],'motionType':0},
            'rigidBodySystem':{'rigidBody':[{'custom':{'rotate':{'axisAngleVelocity':{'axis':cfg['rotation']['axis_unit'],'velocity':{'const':[cfg['rotation']['omega_rad_s']]}}},
                'coordSystem':{'origin':{'value':cfg['geometry']['axis_origin_m']}}}}]}}],
        'bc':[{'name':n,'publicData':{'momentum':{'referenceSystem':int(b.get('frame') == 'rotating')}}} for n,b in cfg['boundaries'].items()],
        'numericMethod':{'linearEquation':{'pressure':{'nonOrthCorrs':solver['nonorth_corrections']}},'relaxFactor':{k:{'value':v} for k,v in solver['relaxation'].items()}},
        'initialize':{'global':{'method':1,'publicData':{k:{'value':v} for k,v in [('velocity',solver['initial_velocity_m_s']),('pressure',0.),('temperature',cfg['physics']['temperature_K']),('density',cfg['physics']['density_kg_m3']),('k',solver['initial_k_m2_s2']),('epsilon',solver['initial_epsilon_m2_s3'])]}}}}
    settings = {'region':[region],'material':[{'id':1,'density':{'const':[cfg['physics']['density_kg_m3']]},'viscosity':{'const':[cfg['physics']['viscosity_Pa_s']]}}],
        'interfaceGroup':[{'sideA':[ids[a]],'sideB':[ids[b]]} for a,b in cfg['interface_pairs']],
        'couplingSolver':{'mpi':{'core':solver['cores']},'steady':{'iters':solver['max_iterations'],'savedIters':solver['save_interval']}},
        'monitor':[{'name':prefix+n} for n,b in cfg['boundaries'].items() if b['kind'] != 'wall' for prefix in ('mass_','volume_')]}
    inventory = {'zones':zones,'boundaries':boundaries,'regions':[{'zone_ids':[z['id'] for z in zones]}],'momentum_convection':0}
    return settings,inventory


def main():
    """通过真实函数调用和独立进程验证正常/异常路径，而不只检查文字或源码。"""
    argparse.ArgumentParser(description=__doc__).parse_args()
    checks = []
    def good(name,function):
        function(); checks.append(name)
    def reject(name,function):
        try:
            function()
        except (ValueError,KeyError,RuntimeError,FileNotFoundError):
            checks.append(name); return
        raise RuntimeError('应该拒绝却通过：'+name)
    def command(arguments,expected):
        process = subprocess.run([sys.executable]+[str(a) for a in arguments],capture_output=True)
        if process.returncode != expected:
            raise RuntimeError(process.stdout.decode(errors='replace')+process.stderr.decode(errors='replace'))
    with tempfile.TemporaryDirectory(prefix='fan-cfd-中文 ') as temporary:
        root = Path(temporary)/'fixture'; cfg,evidence = fixture(root)
        good('explicit_config',lambda:load_case(root))
        good('mesh_evidence',lambda:check_mesh(root,cfg,evidence))
        def change_config(key,value):
            altered = copy.deepcopy(cfg); node = altered
            for part in key[:-1]:
                node = node[part]
            node[key[-1]] = value; validate_config(altered)
        reject('unknown_rpm',lambda:change_config(['rotation','rpm'],None))
        reject('wrong_view_sense',lambda:change_config(['rotation','sense_from_view'],'counterclockwise'))
        reject('wrong_rotating_wall',lambda:change_config(['boundaries','stator_wall','frame'],'rotating'))
        reject('missing_interface_pair',lambda:change_config(['interface_pairs'],cfg['interface_pairs'][1:]))
        reject('duplicate_interface_pair',lambda:change_config(['interface_pairs'],cfg['interface_pairs']+[cfg['interface_pairs'][0]]))
        reject('unknown_layers',lambda:change_config(['mesh','layer_groups',0,'requested_layers'],None))
        def bad_evidence(path,value):
            altered = copy.deepcopy(evidence); node = altered
            for part in path[:-1]:
                node = node[part]
            node[path[-1]] = value; check_mesh(root,cfg,altered)
        reject('no_generated_layers',lambda:bad_evidence(['boundaries','blade_wall','layer_count_area_m2'],{'0':1.}))
        reject('unmatched_layer_area',lambda:bad_evidence(['boundaries','blade_wall','unmatched_area_m2'],.1))
        reject('lost_prisms',lambda:bad_evidence(['zones','rotor','cell_types'],{'tetra':1}))
        reject('millimeter_as_meter',lambda:bad_evidence(['zones','rotor','bbox_m'],[0.,0.,3000.,1000.,1000.,4000.]))
        reject('nonorth_exceeds_limit',lambda:bad_evidence(['zones','rotor','quality','max_nonorth_deg'],89.9))
        reject('nan_quality',lambda:bad_evidence(['zones','rotor','quality','min_volume_m3'],float('nan')))
        settings,inventory = settings_fixture(cfg,evidence)
        good('readback_fixture',lambda:verify_settings(cfg,settings,inventory,evidence,0))
        altered = copy.deepcopy(settings); altered['region'][0]['bc'][4]['publicData']['momentum']['referenceSystem'] = 1
        reject('fixed_wall_in_mrf',lambda:verify_settings(cfg,altered,inventory,evidence,0))
        altered = copy.deepcopy(settings); altered['interfaceGroup'].pop()
        reject('unpaired_native_interface',lambda:verify_settings(cfg,altered,inventory,evidence,0))
        source = Path(temporary)/'source.step'; source.write_text('synthetic initialization only',encoding='utf8')
        newcase = Path(temporary)/'新风机 case'
        command([SCRIPTS/'fan_case.py','init','--case',newcase,'--source',source],0)
        snapshot = {str(p.relative_to(newcase)):digest(p) for p in newcase.rglob('*') if p.is_file()}
        command([SCRIPTS/'fan_case.py','init','--case',newcase,'--source',source],1)
        if snapshot != {str(p.relative_to(newcase)):digest(p) for p in newcase.rglob('*') if p.is_file()}:
            raise RuntimeError('重复初始化修改原件')
        checks.append('initialization_overwrite_protection')
        history = Path(temporary)/'flow.txt'
        history.write_text('\n'.join('%d %.8f'%(i,1+i*1e-5) for i in range(1,11)),encoding='utf8')
        result = analyze(history,1,5,1.,1e-9,10)
        if not result['plateau_passed']:
            raise RuntimeError('稳定历史未通过')
        checks.append('stable_history')
        for name,text in [('missing_steps','1 1\n3 1\n'),('duplicate_steps','1 1\n1 1\n'),('nan_history','1 1\n2 nan\n')]:
            history.write_text(text,encoding='utf8'); reject(name,lambda:analyze(history,1,2,1.,1e-9))
        history.write_text('1 0\n2 0\n',encoding='utf8')
        if analyze(history,1,2,1.,1e-9)['plateau_passed']:
            raise RuntimeError('零均值误判稳定')
        checks.append('near_zero_history')
        # 使用 Python 充当会退出7的子进程，验证异常进程证据、原件保护和重复提交拒绝。
        qfx = root/cfg['files']['qfx']; qfx.parent.mkdir(parents=True)
        qfx.write_text('raise SystemExit(7)\n',encoding='utf8')
        settings_path = qfx.parent/'qflux_readback_settings.json'; write_json(settings_path,settings)
        gate = root/'checks/mesh_gate.json'; write_json(gate,{'synthetic':True})
        proof = {'passed':True,'independent_readback':True,'case_sha256':config_hash(cfg),'qfx_sha256':digest(qfx),
            'mesh_sha256':cfg['mesh']['sha256'],'mesh_gate_sha256':digest(gate),'settings_sha256':digest(settings_path)}
        write_json(qfx.parent/'qflux_readback.json',proof)
        cmd = [SCRIPTS/'run_solver.py','--case',root,'--solver-exe',sys.executable,'--min-free-gb','0']
        command(cmd,0); command(cmd+['--execute'],1)
        result = read_json(root/cfg['files']['run']/'finished.json')
        if result['exit_code'] != 7 or not result['source_qfx_unchanged']:
            raise RuntimeError('未正确记录子进程失败/源工程保护')
        command(cmd+['--execute'],1); checks.append('failed_process_record_and_duplicate_rejection')
    print(json.dumps({'passed':True,'checks':checks,'count':len(checks),'scope':'synthetic logic tests; no vendor API or fan solve'},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('风机技能自检失败：'+str(error),file=sys.stderr); sys.exit(1)

# -*- coding: utf-8 -*-
"""不加载商业 API 的 QFlux 落盘设置核验，供独立回读及合成数据测试共用。"""
import math
from fan_case import number, require

# QFlux 原生枚举：仅在目标 API 版本已核对时使用，不猜测其他版本含义。
CONDITION_CLASSES = {'wall':'CBCWall', 'interface':'CBCInterfaceBoundary',
                     'pressure_inlet':'CBCPressInlet', 'pressure_outlet':'CBCPressOutlet'}


def equal(actual, expected, name):
    """递归比较有限数值，避免字符串化或 NaN 比较误通过。"""
    if isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), name+' 长度不符')
        for a,b in zip(actual,expected):
            equal(a,b,name)
    elif isinstance(expected,(int,float)) and not isinstance(expected,bool):
        number(actual,name)
        require(math.isclose(actual,expected,rel_tol=1e-8,abs_tol=1e-12), name+' 不符')
    else:
        require(actual == expected, name+' 不符')


def verify_inventory(cfg, inventory, evidence):
    """全部边界名称、面数、归属与米制尺寸以实际管理器对象为准。"""
    zones = {z['name']:z for z in inventory['zones']}
    boundaries = {b['name']:b for b in inventory['boundaries']}
    require(len(zones) == len(inventory['zones']) and set(zones) == set(cfg['mesh']['zones']), '网格区缺失/重复/多余')
    require(len(boundaries) == len(inventory['boundaries']) and set(boundaries) == set(cfg['boundaries']), '边界名称缺失/重复/多余')
    for name, expected in cfg['mesh']['zones'].items():
        actual = zones[name]
        equal(actual['cells'], expected['cells'], name+'.cells')
        require(len(actual['bbox_m']) == 6, '实际包围盒不完整')
        require(all(abs(number(a,'bbox_m')-b) <= cfg['mesh']['bbox_tolerance_m'] for a,b in zip(actual['bbox_m'],expected['bbox_m'])), '米制包围盒不符：'+name)
    zone_ids = {z['id']:n for n,z in zones.items()}
    for name, expected in cfg['boundaries'].items():
        actual = boundaries[name]
        require(zone_ids[actual['zone_id']] == expected['zone'], '边界归属不符：'+name)
        equal(actual['faces'], evidence['boundaries'][name]['faces'], name+'.faces')


def verify_settings(cfg, settings, inventory, evidence, scheme_enum):
    """证明已保存的工况与配置相符；此函数不证明已求解或收敛。"""
    verify_inventory(cfg,inventory,evidence)
    require(len(settings['region']) == 1, '应为单一流体求解域')
    region = settings['region'][0]
    regions = inventory['regions']
    require(len(regions) == 1 and set(regions[0]['zone_ids']) == {z['id'] for z in inventory['zones']}, '单流体域网格区绑定不完整')
    equal(region['solver']['time'],1,'稳态')
    equal(region['solver']['energy'],False,'能量')
    turb = region['solver']['turbModel']['RANS']
    for key,value in [('type',2),('subType',2),('wallFunction',3)]:
        equal(turb[key],value,'turbulence.'+key)
    equal(region['operationCondition']['gravity']['on'],False,'重力')
    equal(region['operationCondition']['pressure']['value'],cfg['physics']['reference_pressure_Pa'],'参考压力')
    mat = next(m for m in settings['material'] if m['id'] == region['material'])
    equal(mat['density']['const'],[cfg['physics']['density_kg_m3']],'密度')
    equal(mat['viscosity']['const'],[cfg['physics']['viscosity_Pa_s']],'粘度')
    require(len(region['motion']) == 1, '应为一个MRF运动对象')
    motion = region['motion'][0]
    rotor = next(z for z in inventory['zones'] if z['name'] == cfg['rotation']['zone'])
    equal(motion['meshMotion']['zone'],[rotor['id']],'旋转区')
    equal(motion['meshMotion']['motionType'],0,'MRF')
    bodies = motion['rigidBodySystem']['rigidBody']
    require(len(bodies) == 1, '应为一个旋转刚体')
    body = bodies[0]['custom']
    angle = body['rotate']['axisAngleVelocity']
    equal(angle['axis'],cfg['rotation']['axis_unit'],'旋转轴')
    equal(angle['velocity']['const'],[cfg['rotation']['omega_rad_s']],'角速度')
    equal(body['coordSystem']['origin']['value'],cfg['geometry']['axis_origin_m'],'MRF原点')
    bmap = {b['name']:b for b in inventory['boundaries']}
    stored = {b['name']:b for b in region['bc']}
    require(set(stored) == set(cfg['boundaries']), '设置中的边界不完整')
    for name,expected in cfg['boundaries'].items():
        actual = bmap[name]
        require(actual['condition_class'] == CONDITION_CLASSES[expected['kind']], '实际边界类型不符：'+name)
        if expected['kind'] == 'wall':
            equal(stored[name]['publicData']['momentum']['referenceSystem'],int(expected['frame'] == 'rotating'),name+'.frame')
        elif expected['kind'] == 'interface':
            require(actual['paired'], '接口未真正配对：'+name)
        else:
            equal(actual['pressure_Pa'],expected['pressure_Pa'],name+'.pressure')
    actual_pairs = [frozenset(p['sideA']+p['sideB']) for p in settings['interfaceGroup']]
    expected_pairs = [frozenset((bmap[a]['id'],bmap[b]['id'])) for a,b in cfg['interface_pairs']]
    require(len(actual_pairs) == len(expected_pairs) and set(actual_pairs) == set(expected_pairs), '实际接口配对不符')
    solver = cfg['solver']; native = region['numericMethod']
    equal(native['linearEquation']['pressure']['nonOrthCorrs'],solver['nonorth_corrections'],'非正交修正次数')
    # 格式的持久化字段在 adapter 中从原生对象读回，避免假定 JSON 枚举层级。
    equal(inventory['momentum_convection'],scheme_enum,'动量格式')
    for key,value in solver['relaxation'].items():
        equal(native['relaxFactor'][key]['value'],value,'松弛.'+key)
    init = region['initialize']['global']
    equal(init['method'],1,'显式初始化')
    for key,value in [('velocity',solver['initial_velocity_m_s']),('pressure',0.),('temperature',cfg['physics']['temperature_K']),
                      ('density',cfg['physics']['density_kg_m3']),('k',solver['initial_k_m2_s2']),('epsilon',solver['initial_epsilon_m2_s3'])]:
        equal(init['publicData'][key]['value'],value,'初值.'+key)
    control = settings['couplingSolver']
    equal(control['mpi']['core'],solver['cores'],'核数')
    equal(control['steady']['iters'],solver['max_iterations'],'迭代上限')
    equal(control['steady']['savedIters'],solver['save_interval'],'保存间隔')
    monitor_names = {m['name'] for m in settings['monitor']}
    for name,bc in cfg['boundaries'].items():
        if bc['kind'] != 'wall':
            require({'mass_'+name,'volume_'+name} <= monitor_names, '缺少通量监控：'+name)

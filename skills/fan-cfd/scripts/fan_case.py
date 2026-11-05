# -*- coding: utf-8 -*-
"""初始化风机案例、校验显式物理映射，并审核与网格哈希绑定的实测质量/层覆盖。"""
import argparse
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path

# 模板路径与数值比较容差；工程参数均来自 case.json，不内置型号工况。
TEMPLATE = Path(__file__).resolve().parents[1] / 'assets/case.example.json'
REL_TOLERANCE = 1e-8
KINDS = {'wall', 'interface', 'pressure_inlet', 'pressure_outlet'}


def digest(path):
    """流式计算大 CAD、网格或工程的 SHA256。"""
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def read_json(path):
    """兼容 Windows BOM，拒绝 JSON 中非标准 NaN/Infinity。"""
    def invalid(value):
        raise ValueError('JSON 含非有限常量：' + value)
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), parse_constant=invalid)


def write_json(path, data):
    """同目录临时文件原子替换，观察端不会读到半份 JSON。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(str(temporary), str(target))


def config_hash(cfg):
    """绑定实际配置内容，键顺序或缩进变化不使同一配置失效。"""
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, allow_nan=False).encode('utf-8')).hexdigest()


def require(condition, message):
    """不用 assert，避免 Python -O 关闭工程检查。"""
    if not condition:
        raise ValueError(message)


def number(value, name, minimum=None, integer=False):
    """拒绝 null、布尔值、非有限数和非整数的计数参数。"""
    require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value), name + ' 必须为有限数')
    require(minimum is None or value >= minimum, name + ' 低于允许范围')
    require(not integer or isinstance(value, int), name + ' 必须为整数')
    return value


def vector(value, name, unit=False):
    """检查三维坐标和方向；单位向量不做隐式归一化。"""
    require(isinstance(value, list) and len(value) == 3, name + ' 需要三个分量')
    for component in value:
        number(component, name)
    if unit:
        require(abs(sum(x*x for x in value)-1) <= REL_TOLERANCE, name + ' 需要单位向量')


def case_path(root, relative):
    """配置产物限定在案例目录内；远程迁移无需写死绝对路径。"""
    require(isinstance(relative, str) and bool(relative.strip()), '缺少案例相对路径')
    path = (Path(root).resolve() / relative).resolve()
    require(Path(root).resolve() in path.parents, '案例文件路径越界：' + relative)
    return path


def validate_config(cfg):
    """校验单转子稳态 MRF 模板；任意区名和接口数量由显式映射决定。"""
    require(cfg['schema_version'] == 1, '不支持的 schema_version')
    require(cfg['profile'] in ('open_fan', 'room_fan', 'custom'), '未知流体域 profile')
    require(isinstance(cfg['name'], str) and cfg['name'].strip(), '缺少案例名称')
    number(cfg['geometry']['diameter_m'], 'diameter_m', 1e-12)
    vector(cfg['geometry']['axis_origin_m'], 'axis_origin_m')
    mesh = cfg['mesh']
    require(isinstance(mesh['sha256'], str) and len(mesh['sha256']) == 64 and all(c in '0123456789abcdef' for c in mesh['sha256']), '请填写实测 mesh.sha256')
    require(bool(mesh['zones']), '缺少网格区')
    for name, zone in mesh['zones'].items():
        number(zone['cells'], name + '.cells', 1, True)
        box = zone['bbox_m']
        require(isinstance(box, list) and len(box) == 6, name + ' 缺少米制包围盒')
        for value in box:
            number(value, name + '.bbox_m')
        require(all(box[i+3] > box[i] for i in range(3)), '三维区域包围盒无厚度：' + name)
    number(mesh['bbox_tolerance_m'], 'bbox_tolerance_m', 0)
    lim = mesh['limits']
    number(lim['min_volume_m3'], 'min_volume_m3', 0)
    require(0 < number(lim['max_nonorth_deg'], 'max_nonorth_deg') < 90, '非正交门槛需在 0~90 度内')
    require(0 < number(lim['max_volume_error_fraction'], 'max_volume_error_fraction') < 1, '体积误差门槛不合法')
    boundaries = cfg['boundaries']
    require(bool(boundaries), '边界表为空')
    rot = cfg['rotation']
    require(rot['zone'] in mesh['zones'], '旋转区不存在')
    vector(rot['axis_unit'], 'axis_unit', True)
    vector(rot['view_direction_unit'], 'view_direction_unit', True)
    number(rot['rpm'], 'rpm', 1e-12)
    omega = number(rot['omega_rad_s'], 'omega_rad_s')
    require(abs(abs(omega)-rot['rpm']*2*math.pi/60) <= REL_TOLERANCE*max(1, abs(omega)), 'rpm 与角速度不一致')
    require(rot['sense_from_view'] in ('clockwise', 'counterclockwise'), '缺少观察方向下的旋向')
    dot = sum(a*b for a,b in zip(rot['axis_unit'], rot['view_direction_unit']))
    require(abs(dot) > .99, '观察方向需沿旋转轴，不能侧向判断顺逆时针')
    require((omega*dot > 0) == (rot['sense_from_view'] == 'clockwise'), '角速度与沿视线观察的顺逆时针不一致')
    for name, boundary in boundaries.items():
        require(boundary['zone'] in mesh['zones'], '边界归属区不存在：' + name)
        require(boundary['kind'] in KINDS, '适配器不支持边界类型：' + name)
        if boundary['kind'] == 'wall':
            require(boundary['frame'] in ('global', 'rotating'), '壁面需显式选择参考系：' + name)
            if boundary['frame'] == 'rotating':
                require(boundary['zone'] == rot['zone'], '旋转壁面未落在旋转区：' + name)
        if boundary['kind'].startswith('pressure_'):
            number(boundary['pressure_Pa'], name + '.pressure_Pa')
    paired = []
    for pair in cfg['interface_pairs']:
        require(isinstance(pair, list) and len(pair) == 2 and pair[0] != pair[1], '接口必须是两个不同边界')
        require(all(n in boundaries and boundaries[n]['kind'] == 'interface' for n in pair), '接口配对引用非接口边界')
        require(boundaries[pair[0]]['zone'] != boundaries[pair[1]]['zone'], '接口两侧不能是同一网格区')
        paired.extend(pair)
    require(len(paired) == len(set(paired)), '接口被重复配对')
    require(set(paired) == {n for n,b in boundaries.items() if b['kind'] == 'interface'}, '存在未配对接口')
    # 任意多个区域都应通过配对连通到同一求解域；不靠名字猜语义。
    reached = {rot['zone']}
    for unused in mesh['zones']:
        for a,b in cfg['interface_pairs']:
            za,zb = boundaries[a]['zone'], boundaries[b]['zone']
            if za in reached or zb in reached:
                reached.update((za,zb))
    require(reached == set(mesh['zones']), '区域未通过接口连通')
    grouped = []
    for group in mesh['layer_groups']:
        require(bool(group['boundaries']), '层组不能为空')
        require(all(n in boundaries and boundaries[n]['kind'] == 'wall' for n in group['boundaries']), '层组含非壁面')
        number(group['requested_layers'], 'requested_layers', 1, True)
        require(0 < number(group['minimum_full_layer_area_fraction'], 'minimum_full_layer_area_fraction') <= 1, '需要案例层覆盖门槛')
        number(group['growth'], 'growth', 1)
        first,total = group['first_height_m'], group['total_thickness_m']
        require(first is not None or total is not None, '首层高度或总厚度至少明确一项')
        if first is not None:
            number(first, 'first_height_m', 1e-15)
        if total is not None:
            number(total, 'total_thickness_m', 1e-15)
        if first is not None and total is not None:
            expected = first*sum(group['growth']**i for i in range(group['requested_layers']))
            require(math.isclose(total, expected, rel_tol=1e-6), '首层、增长率和总厚度不一致')
        grouped.extend(group['boundaries'])
    require(len(grouped) == len(set(grouped)), '壁面重复分配边界层组')
    require(set(grouped) == {n for n,b in boundaries.items() if b['kind'] == 'wall'}, '每个壁面必须明确边界层要求')
    physics = cfg['physics']
    require(physics['energy'] is False and physics['gravity'] is False, '内置适配限等温无重力；其他物理请扩展')
    require(physics['turbulence_adapter'] == 'KE-native2-wall3', '其他湍流模型需要目标版本适配')
    for key in ('density_kg_m3', 'viscosity_Pa_s', 'temperature_K', 'reference_pressure_Pa'):
        number(physics[key], key, 1e-15)
    solver = cfg['solver']
    for key in ('cores', 'max_iterations', 'save_interval'):
        number(solver[key], key, 1, True)
    require(solver['save_interval'] <= solver['max_iterations'], '保存间隔大于迭代数')
    number(solver['nonorth_corrections'], 'nonorth_corrections', 0, True)
    require(solver['momentum_scheme'] in ('FirstUpwind', 'SecondUpwind'), '未知离散格式')
    for key in ('pressure','momentum','turbulence'):
        require(0 < number(solver['relaxation'][key], 'relaxation.'+key) <= 1, '松弛因子范围错误')
    for key in ('initial_k_m2_s2','initial_epsilon_m2_s3'):
        number(solver[key], key, 1e-15)
    vector(solver['initial_velocity_m_s'], 'initial_velocity_m_s')
    vector(solver['reference_position_m'], 'reference_position_m')
    return cfg


def load_case(root):
    """读取配置并校验全部产物路径；原始 CAD 始终通过初始化复制留存。"""
    root = Path(root).resolve()
    cfg = validate_config(read_json(root/'case.json'))
    paths = [case_path(root, cfg['mesh']['file']), case_path(root, cfg['source']['file'])]
    paths.extend(case_path(root, value) for value in cfg['files'].values())
    require(len(paths) == len(set(paths)), '源文件、网格、设置工程和运行目录不能重合')
    return cfg


def check_mesh(root, cfg, evidence):
    """审核实测报告并重算层覆盖；报告必须由原生/独立检查生成，不能手填 passed。"""
    mesh = case_path(root, cfg['mesh']['file'])
    actual_hash = digest(mesh)
    require(actual_hash == cfg['mesh']['sha256'] == evidence['mesh_sha256'], '网格来源哈希不一致')
    require(bool(evidence.get('producer')) and bool(evidence.get('quality_method')), '缺少网格检查工具/方法说明')
    require(set(evidence['zones']) == set(cfg['mesh']['zones']), '质量报告区域集合不符')
    for name, expect in cfg['mesh']['zones'].items():
        actual = evidence['zones'][name]
        require(actual['cells'] == expect['cells'], '网格单元数不符：' + name)
        require(len(actual['bbox_m']) == 6, '网格包围盒长度不符')
        require(all(abs(number(a,'bbox')-b) <= cfg['mesh']['bbox_tolerance_m'] for a,b in zip(actual['bbox_m'], expect['bbox_m'])), '米制包围盒不符：' + name)
        types = actual['cell_types']
        require(bool(types), '缺少混合单元类型统计')
        for count in types.values():
            number(count, 'cell_types', 0, True)
        require(sum(types.values()) == actual['cells'], '混合单元导出遗漏：' + name)
        q = actual['quality']
        for key in ('nonpositive_cells','invalid_topology_cells'):
            require(number(q[key], key, 0, True) == 0, '非正体积或拓扑错误：' + name)
        require(number(q['min_volume_m3'], 'min_volume_m3') > cfg['mesh']['limits']['min_volume_m3'], '体积质量未通过：' + name)
        require(number(q['max_nonorth_deg'], 'max_nonorth_deg', 0) <= cfg['mesh']['limits']['max_nonorth_deg'], '非正交超出案例门槛：' + name)
        require(number(q['volume_error_fraction'], 'volume_error_fraction', 0) <= cfg['mesh']['limits']['max_volume_error_fraction'], '网格/CAD体积误差超限：' + name)
    require(set(evidence['boundaries']) == set(cfg['boundaries']), '边界集合不符')
    for name, expect in cfg['boundaries'].items():
        actual = evidence['boundaries'][name]
        require(actual['zone'] == expect['zone'], '边界归属不符：' + name)
        number(actual['faces'], name+'.faces', 1, True)
    records = {}
    for group in cfg['mesh']['layer_groups']:
        for name in group['boundaries']:
            actual = evidence['boundaries'][name]
            histogram = actual['layer_count_area_m2']
            require(bool(histogram), '缺少实际层数面积分布：' + name)
            for layers,area in histogram.items():
                require(str(int(layers)) == layers and int(layers) >= 0, '层数分组不合法')
                number(area, 'layer area', 0)
            total = sum(histogram.values())
            require(total > 0 and number(actual['unmatched_area_m2'],'unmatched_area_m2',0) == 0, '层证据未覆盖完整壁面：' + name)
            require(math.isclose(total, number(actual['area_m2'],'area_m2',1e-30), rel_tol=1e-6), '层直方图与完整壁面面积不符')
            covered = sum(area for layers,area in histogram.items() if int(layers) >= group['requested_layers'])/total
            require(covered >= group['minimum_full_layer_area_fraction'], '实际边界层覆盖不足：' + name)
            thickness = actual['actual_total_thickness_m']
            for key in ('min','median','max'):
                number(thickness[key], name+'.actual_total_thickness_m.'+key, 0)
            require(0 < thickness['median'] <= thickness['max'] and thickness['min'] <= thickness['median'], '实际层厚统计不合法')
            records[name] = {'full_layer_area_fraction':covered, 'actual_total_thickness_m':thickness}
    return {'passed':True, 'scope':'mesh evidence gate; independent QFlux readback still required', 'mesh_sha256':actual_hash,
            'case_sha256':config_hash(cfg), 'layers':records, 'solved':False}


def main():
    """初始化不覆盖已有目录，验收只读取原网格并生成新记录。"""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    init = sub.add_parser('init'); init.add_argument('--case', required=True); init.add_argument('--source', required=True)
    val = sub.add_parser('validate'); val.add_argument('--case', required=True)
    check = sub.add_parser('check-mesh'); check.add_argument('--case', required=True); check.add_argument('--evidence', required=True)
    args = parser.parse_args(); root = Path(args.case).resolve()
    if args.action == 'init':
        source = Path(args.source).resolve()
        require(source.is_file(), '原始 CAD 不存在')
        require(not root.exists(), '拒绝覆盖已有案例')
        cfg = read_json(TEMPLATE); cfg['name'] = root.name
        cfg['source'] = {'file':'01_geometry/source'+source.suffix.lower(), 'sha256':digest(source)}
        for folder in ('01_geometry','02_mesh','03_solve','checks'):
            (root/folder).mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(root/cfg['source']['file']))
        write_json(root/'case.json', cfg)
        print('已初始化；请填写 case.json 中未知参数：' + str(root))
    else:
        cfg = load_case(root)
        require(digest(case_path(root,cfg['source']['file'])) == cfg['source']['sha256'], '原始 CAD 已变化')
        result = {'passed':True,'case_sha256':config_hash(cfg)}
        if args.action == 'check-mesh':
            result = check_mesh(root,cfg,read_json(args.evidence))
            result['evidence_sha256'] = digest(args.evidence)
            write_json(root/'checks/mesh_gate.json', result)
        print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('风机案例检查失败：' + str(error), file=sys.stderr)
        sys.exit(1)

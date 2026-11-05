# -*- coding: utf-8 -*-
"""只配置本次新网格QFlux工程；独立回读落盘设置，不启动求解。"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
import traceback

# 可调参数全部来自显式配置；安装目录可由命令行或环境变量提供。
CLI=argparse.ArgumentParser(description=__doc__)
CLI.add_argument('action', choices=['setup','readback'])
CLI.add_argument('--config',required=True)
CLI.add_argument('--output-dir',required=True)
CLI.add_argument('--qflux-home',default=os.environ.get('QFLUX_HOME'))
ARGS=CLI.parse_args()
if not ARGS.qflux_home:raise RuntimeError('请指定--qflux-home或QFLUX_HOME')
ROOT=Path(ARGS.output_dir).resolve();ROOT.mkdir(parents=True,exist_ok=True)
CFG=json.loads(Path(ARGS.config).read_text(encoding='utf-8-sig'))
if CFG['physics'].get('energy',False) or CFG['physics'].get('gravity',False):
    raise ValueError('当前适配器仅支持无重力、等温空气MRF；其他物理需单独适配')
QHOME=Path(ARGS.qflux_home).resolve()
if not (QHOME/'qfxPyApi').is_dir():raise FileNotFoundError('安装目录缺少qfxPyApi')
sys.path.insert(0,str(QHOME))
COOKIE=os.add_dll_directory(str(QHOME)) if hasattr(os,'add_dll_directory') else None
os.environ['PATH']=str(QHOME)+os.pathsep+os.environ.get('PATH','')
from qfxPyApi import qxapp, qxcmd
from qfxPyApi.qxmod import boundary as bc, dynamicMesh as dm, material, monitor
from qfxPyApi.qxmod import physics, region, solverset, types, post, numerics
from qfxPyApi.qxmod.runtime import getActiveModel
KEEP = []


def digest(path):
    """计算文件来源哈希，避免把旧工程误当成新网格。"""
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8*1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def scalar(value):
    """保留原生常量的生命周期，直到工程保存完成。"""
    v = types.variant()
    v.value = value
    KEEP.append(v)
    return v


def monitor_face(model, name, face, method):
    """建立检测圆面和接口通量监测。"""
    mon = monitor.txMonitorBase.Create(monitor.txMonitorType.Face)
    mon.name = name
    mon.regions = [model.regionMng[0].id]
    mon.faceDefinition = face
    mon.method = int(method)
    for v in mon.variable:
        v.state = int(v.innerName in ('p', 'U.z'))
    qxcmd.ICmdAddMonitor(mon)
    KEEP.extend([face, mon])


def configure():
    """由同一网格的已回读QFX建立设置完整的新工程，不改变任何网格。"""
    target = Path(CFG['files']['QFlux'])
    if target.exists():
        raise FileExistsError('拒绝覆盖无本任务回读记录的工程：'+str(target))
    if CFG['mesh'].get('source_qfx'):
        if digest(CFG['mesh']['source_qfx']) != CFG['mesh']['source_qfx_sha256']:
            raise RuntimeError('输入QFX哈希与已验收记录不同')
        opencase = qxcmd.ICmdOpenCaseParameter()
        opencase.caseFile = CFG['mesh']['source_qfx']
        qxcmd.ICmdOpenCase(opencase)
    else:
        if digest(CFG['mesh']['source_cgns']) != CFG['mesh']['sha256']:
            raise RuntimeError('输入CGNS哈希与已验收网格记录不一致')
        qxcmd.ICmdImportMesh([CFG['mesh']['source_cgns']])
    m = getActiveModel()
    if any(len(r.motions) for r in m.regionMng):
        raise ValueError('setup只接受纯网格源工程；已含运动设置的工程请新建阶段并提取网格')
    if sum(z.cellCount for z in m.qxZoneMng) != CFG['mesh']['cells']:
        raise RuntimeError('源网格单元总数不符')
    qxcmd.ICmdSetRegionName(m.regionMng[0].id, 'air')
    zones = {('rotating' if 'rotating' in z.name else 'stationary'): z for z in m.qxZoneMng}
    qxcmd.ICmdSetRegionZone('air', [zones['stationary'].id, zones['rotating'].id])
    for semantic, z in zones.items():
        key = 'fluid_' + semantic
        if z.cellCount != CFG['mesh']['zone_cells'][key]:
            raise RuntimeError('网格区单元数与验收回读不一致：' + z.name)
    qxcmd.ICmdSetTimeMode(region.txSolverPatternESTType.Steady)
    turb = physics.CTurbulenceModel.Create(physics.CTurbulenceModelTurbulenceMethod.KE)
    turb.options = 2
    turb.wallFunction = 3
    turb.buoyancy = False
    qxcmd.ICmdSetTurbulence('air', turb)
    qxcmd.ICmdSetEnergy('air', False)
    KEEP.append(turb)
    air = material.material.Create(material.materialTypeEnum.Gas)
    air.name = 'Air_configured'
    for name, val in [('Density', CFG['physics']['density_kg_m3']), ('Viscosity', CFG['physics']['viscosity_Pa_s']), ('SpecialHeat', 1006.), ('ThermalConduct', .0263)]:
        prop = air.getProperty(getattr(material.matPropertyBase, name))
        variant = material.materialVariant()
        variant.value = val
        prop.method = 1
        prop.value = variant
        KEEP.extend([prop, variant])
    qxcmd.ICmdAddProjectMaterial(air)
    qxcmd.ICmdSetRegionMaterial('air', air.name)
    KEEP.append(air)
    boundaries = {b.name: b for b in m.boundaryMng}
    expected = set(CFG['boundaries'])
    if set(boundaries) != expected:
        raise RuntimeError('边界列表不同：'+repr(set(boundaries)^expected))
    for name in boundaries:
        condition = bc.CBCInterfaceBoundary() if name.startswith('if_rotor_') else bc.CBCWall()
        if name.startswith('if_rotor_'):
            pri = condition.pri
            pri.mergeable = True
            condition.pri = pri
            KEEP.append(pri)
        qxcmd.ICmdSetBoundaryCondition(name, condition)
        KEEP.append(condition)
    interface = bc.CBCInterfaceBoundary()
    pri = interface.pri
    pri.mergeable = True
    interface.pri = pri
    interface.surfaceId = boundaries['if_rotor_rot'].id
    qxcmd.ICmdSetBoundaryPaired('if_rotor_stat', 'if_rotor_rot', interface)
    KEEP.extend([interface, pri])
    motion = dm.txDynMeshRegion.Create(0)
    motion.name = 'rotor_MRF'
    motion.motionType = 0
    qxcmd.ICmdAddDynamicMesh('air', motion)
    actual = m.regionMng[0].motions[0]
    qxcmd.ICmdDynamicMeshAddZone('air', actual.id, [zones['rotating'].id])
    body = dm.txCustomRigidBody()
    body.name = CFG['names']['rotor']
    body.boundaryType = 0
    body.walls = []
    rotate = dm.txDefineAxisAngleVelocity()
    rotate.axis = [0., 0., 1.]
    rotate.velocity = scalar(CFG['physics']['omega_rad_s'])
    body.rotate = rotate
    coord = body.rigidCoordSystem
    origin = coord.unitOrigin
    origin.value = CFG['physics']['axis_origin_m']
    coord.unitOrigin = origin
    body.rigidCoordSystem = coord
    qxcmd.ICmdAddRigidBody('air', actual.id, body)
    qxcmd.ICmdSetBoundaryReferenceFrame(CFG['rotating_wall_boundaries'], 1)
    qxcmd.ICmdSetBoundaryReferenceFrame(sorted(expected-set(CFG['rotating_wall_boundaries'])-{'if_rotor_stat','if_rotor_rot'}), 0)
    KEEP.extend([motion, actual, body, rotate, coord, origin])
    operation = m.regionMng[0].operationCondition
    pressure = operation.unitPress
    pressure.value = CFG['physics']['reference_pressure_Pa']
    operation.unitPress = pressure
    refdensity = operation.unitDensity
    refdensity.value = CFG['physics']['density_kg_m3']
    operation.unitDensity = refdensity
    position = operation.unitPosition
    position.value = [0., 0., .2]
    operation.unitPosition = position
    gravity = operation.unitGravity
    gravity.on = False
    operation.unitGravity = gravity
    qxcmd.ICmdSetOperationCondition('air', operation)
    KEEP.extend([operation, pressure, refdensity, position, gravity])
    init = m.regionMng[0].initialize.flowInit
    init.initMethod = 1
    public = init.fieldParam
    values = [('unitVelocity',[0.,0.,0.]),('unitPressure',0.),('unitTemperature',CFG['physics']['temperature_K']),
              ('unitDensity',CFG['physics']['density_kg_m3']),('unitK',CFG['solver']['initial_k_m2_s2']),
              ('unitEpsilon',CFG['solver']['initial_epsilon_m2_s3'])]
    for name, val in values:
        obj = getattr(public,name)
        obj.value = val
        obj.on = True
        setattr(public, name, obj)
        KEEP.append(obj)
    init.fieldParam = public
    qxcmd.ICmdSetFluidInitCondition('air', init)
    KEEP.extend([init,public])
    nm = m.regionMng[0].numMethod
    ds = nm.discreteScheme
    fmt = ds.discreteFormat
    mom = fmt.momentum
    mom.convection = int(numerics.momentumDiscreteOption.momentumTypeEnum.FirstUpwind)
    fmt.momentum = mom
    fmt.stable = True
    ds.discreteFormat = fmt
    nm.discreteScheme = ds
    relax = nm.relaxationFactor
    # 数值及 method 均从同版本新工程探测结果恢复，保留软件原生定义。
    for name, entry in CFG['default_relaxFactor'].items():
        prop = {'pressure':'pressureCurve','momentum':'momentumCurve','energy':'energyCurve',
                'composition':'compositionCurve','turbulence':'turbulenceCurve',
                'species':'speciesCurve','radiation':'radiationCurve'}.get(name)
        if prop:
            curve = getattr(relax, prop)
            curve.method = entry['method']
            curve.value = entry['value']
            setattr(relax, prop, curve)
            KEEP.append(curve)
    nm.relaxationFactor = relax
    control = nm.solverControl
    ps = control.pressure
    ps.nNonOrthCorrs = 2
    control.pressure = ps
    nm.solverControl = control
    qxcmd.ICmdSetFluidNumMethod('air',nm)
    KEEP.extend([nm,ds,fmt,mom,relax,control,ps])
    circ = types.qxCircle()
    circ.coord = CFG['measurement']['center_m']
    circ.radius = CFG['measurement']['radius_m']
    circ.normal = CFG['measurement']['normal']
    geom = post.markFaceGeomParam()
    geom.shape = circ
    geom.useRemesh = True
    geom.meshSize = CFG['measurement']['mesh_size_m']
    qxcmd.ICmdAddCustomGeomFace(geom)
    face = monitor.txMonitorFaceDefine()
    face.postFaceNames = ['customface']
    monitor_face(m,CFG['measurement']['name'],face,monitor.txMonitorFaceMethod.VolumeFlowRate)
    for name in ['if_rotor_rot','if_rotor_stat']:
        face = monitor.txMonitorFaceDefine()
        face.ids = [boundaries[name].id]
        monitor_face(m,'mass_'+name,face,monitor.txMonitorFaceMethod.MassFlowRate)
    KEEP.extend([circ,geom])
    mpi = solverset.txMPIParallel()
    mpi.flagMPI = True
    mpi.numCoreMPI = CFG['solver']['cores']
    qxcmd.ICmdSetMPIParallel(mpi)
    it = m.solverSet.iteration
    it.iterations = CFG['solver']['max_iterations']
    it.autoSaveFreqType = 0
    it.autoSaveIteration = CFG['solver']['save_interval']
    it.name = CFG['names']['QFlux']
    it.folder = CFG['qflux_run']
    it.savePathType = 0
    it.dataFormat = 'qfx'
    qxcmd.ICmdSetIterationControl(it)
    KEEP.extend([mpi,it])
    for mon in m.monitorMng:
        if mon.name == 'Residual' and CFG['solver'].get('run_full_iterations',False):
            criterion = mon.criterion
            criterion.flag = False
            for item in ['continuityOn','momentumOn','energyOn','turbulenceOn','speciesOn','radiationOn','vofOn']:
                if hasattr(criterion,item):
                    setattr(criterion,item,False)
            mon.criterion = criterion
            qxcmd.ICmdSetMonitorProperty(mon.name,mon)
            KEEP.extend([mon,criterion])
    # 完成其他工况后再次写入显式初值，避免自动初值模式重算湍流量。
    qxcmd.ICmdSetFluidInitCondition('air', init)
    save = qxcmd.ICmdSaveCaseParameter()
    # 厂商保存接口不会截断已有HDF5组，先保存全新临时工程再原子替换。
    staging = target.with_name(target.stem+'_staging.qfx')
    if staging.exists():
        raise FileExistsError('存在未完成暂存工程，请检查来源后再处理')
    target.parent.mkdir(parents=True,exist_ok=True)
    save.caseFile = str(staging)
    save.fileType = 1
    save.persistence = qxcmd.ESaveCasePersistence.ProjectFile
    qxcmd.ICmdSaveCase(save)
    os.replace(str(staging), str(target))
    print('QFLUX_SETUP_SAVED_NO_SOLVE', target, flush=True)


def readback():
    """从新进程重新导出实际设置，而不是引用保存前的JSON。"""
    opened = qxcmd.ICmdOpenCaseParameter()
    opened.caseFile = CFG['files']['QFlux']
    qxcmd.ICmdOpenCase(opened)
    m = getActiveModel()
    settings_path = ROOT/'qflux_readback_settings.json'
    qxcmd.ICmdExportCaseJson(str(settings_path))
    settings = json.loads(settings_path.read_text(encoding='utf-8'))
    r = settings['region'][0]
    turb = r['solver']['turbModel']['RANS']
    assert turb['type'] == 2 and turb['subType'] == 2 and turb['wallFunction'] == 3, turb
    assert settings['couplingSolver']['mpi']['core'] == CFG['solver']['cores']
    assert sum(z.cellCount for z in m.qxZoneMng) == CFG['mesh']['cells']
    assert {z.name: z.cellCount for z in m.qxZoneMng} == CFG['mesh']['zone_names_cells']
    assert {b.name for b in m.boundaryMng} == set(CFG['boundaries'])
    assert r['numericMethod']['linearEquation']['pressure']['nonOrthCorrs'] == 2
    assert r['solver']['time'] == 1 and not r['solver']['energy']
    assert not r['operationCondition']['gravity']['on']
    assert r['operationCondition']['pressure']['value'] == CFG['physics']['reference_pressure_Pa']
    actual_material = next(x for x in settings['material'] if x['id']==r['material'])
    assert actual_material['density']['const'] == [CFG['physics']['density_kg_m3']]
    assert actual_material['viscosity']['const'] == [CFG['physics']['viscosity_Pa_s']]
    explicit = r['initialize']['global']
    assert explicit['method'] == 1
    for name,val in [('temperature',CFG['physics']['temperature_K']),('k',CFG['solver']['initial_k_m2_s2']),
                     ('epsilon',CFG['solver']['initial_epsilon_m2_s3']),('pressure',0.)]:
        assert abs(explicit['publicData'][name]['value']-val)<1e-10, name
    assert explicit['publicData']['velocity']['value'] == [0.,0.,0.]
    movement = r['motion'][0]
    rotating_id = next(z.id for z in m.qxZoneMng if 'rotating' in z.name)
    assert movement['meshMotion'] == {'zone':[rotating_id],'type':0,'motionType':0}
    rigid = movement['rigidBodySystem']['rigidBody'][0]['custom']
    axisangle = rigid['rotate']['axisAngleVelocity']
    omega = [v*axisangle['velocity']['const'][0] for v in axisangle['axis']]
    assert abs(omega[2]-CFG['physics']['omega_rad_s'])<1e-10
    assert rigid['coordSystem']['origin']['value'] == CFG['physics']['axis_origin_m']
    for b in r['bc']:
        if b['name'].startswith('wall_'):
            expected_frame = int(b['name'] in CFG['rotating_wall_boundaries'])
            assert b['type'] == 1 and b['publicData']['momentum']['referenceSystem'] == expected_frame,b['name']
    pair = settings['interfaceGroup'][0]
    ids = {b.name:b.id for b in m.boundaryMng}
    assert set(pair['sideA']+pair['sideB']) == {ids['if_rotor_stat'],ids['if_rotor_rot']}
    assert settings['couplingSolver']['steady']['iters'] == CFG['solver']['max_iterations']
    assert settings['couplingSolver']['steady']['savedIters'] == CFG['solver']['save_interval']
    assert settings['couplingSolver']['save']['path'] == CFG['qflux_run']
    monitor_names = {item['name'] for item in settings['monitor']}
    assert CFG['measurement']['name'] in monitor_names, monitor_names
    assert {'mass_if_rotor_rot','mass_if_rotor_stat'} <= monitor_names, monitor_names
    face_monitor = next(item for item in settings['monitor'] if item['name'] == CFG['measurement']['name'])
    assert face_monitor['type'] == int(monitor.txMonitorType.Face) and face_monitor['on'] == 1
    native_monitor = next(item for item in m.monitorMng if item.name == CFG['measurement']['name'])
    assert native_monitor.method == int(monitor.txMonitorFaceMethod.VolumeFlowRate)
    assert native_monitor.faceDefinition.postFaceNames == ['customface']
    assert r['numericMethod']['relaxFactor'] == CFG['default_relaxFactor']
    criterion = settings['monitor'][0]['criterion']
    if CFG['solver'].get('run_full_iterations',False):
        assert all(not criterion[key]['on'] for key in ['continuity','momentum','turbulence'])
    for b in m.boundaryMng:
        if b.name.startswith('if_rotor_'):
            assert b.bCondition.isPaired() and b.bCondition.pri.mergeable, b.name
    report = {'passed': True, 'independent_readback': True, 'setup_only': True, 'solved': False,
              'qfx_sha256':digest(CFG['files']['QFlux']), 'source_mesh_sha256':digest(CFG['mesh']['source_cgns']),
              'turbulence_RANS': turb, 'cells_total':sum(z.cellCount for z in m.qxZoneMng),
              'material_name':actual_material['name'],'omega_vector_rad_s':omega,
              'mrf_origin_m':rigid['coordSystem']['origin']['value'],
              'initial_values':explicit['publicData'],'save':settings['couplingSolver']['save'],
              'numericMethod':r['numericMethod'],'interface':pair,
              'zones':[{'name':z.name,'cells':z.cellCount,'nodes':z.pointCount,'bbox':list(z.aabb)} for z in m.qxZoneMng],
              'boundaries':[{'name':b.name,'type':type(b.bCondition).__name__} for b in m.boundaryMng]}
    (ROOT/'qflux_readback.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)


if __name__ == '__main__':
    try:
        # 参数在导入厂商API前解析，--help无需加载商业运行时。
        qxapp.initialize()
        (configure if ARGS.action=='setup' else readback)()
        sys.stdout.flush()
        os._exit(0)
    except Exception:
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)

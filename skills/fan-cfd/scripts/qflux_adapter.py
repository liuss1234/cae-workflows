# -*- coding: utf-8 -*-
"""配置或独立回读单转子多区 QFlux MRF；不在此脚本内启动求解。"""
import argparse
import os
import sys
import traceback
from pathlib import Path
# 厂商嵌入式 Python 的 ._pth 可能禁用脚本目录自动加入，显式解析随包模块。
sys.path.insert(0,str(Path(__file__).resolve().parent))
from fan_case import case_path, check_mesh, config_hash, digest, load_case, read_json, require, write_json
from qflux_verify import verify_inventory, verify_settings

# 原生对象应保留到保存完成，防止 Python 包装对象提前释放；工况来自 case.json。
KEEP = []
REGION_NAME = 'fan_fluid'


def main():
    """帮助与输入核验先于商业 API 导入；setup/readback 必须分两个进程执行。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['setup','readback'])
    parser.add_argument('--case',required=True)
    parser.add_argument('--qflux-home',default=os.environ.get('QFLUX_HOME'))
    args = parser.parse_args()
    root = Path(args.case).resolve(); cfg = load_case(root)
    gate = read_json(root/'checks/mesh_gate.json')
    evidence = read_json(root/'checks/mesh_evidence.json')
    require(gate['passed'] and gate['case_sha256'] == config_hash(cfg), '质量准入与本次配置不符')
    require(gate['evidence_sha256'] == digest(root/'checks/mesh_evidence.json'), '质量证据在准入后变化')
    check_mesh(root,cfg,evidence)
    require(digest(case_path(root,cfg['source']['file'])) == cfg['source']['sha256'], '原始CAD发生变化')
    require(bool(args.qflux_home), '请指定 --qflux-home 或 QFLUX_HOME')
    home = Path(args.qflux_home).resolve()
    require((home/'qfxPyApi').is_dir(), '安装目录缺少 qfxPyApi')
    sys.path.insert(0,str(home))
    cookie = os.add_dll_directory(str(home)) if hasattr(os,'add_dll_directory') else None
    os.environ['PATH'] = str(home)+os.pathsep+os.environ.get('PATH','')
    from qfxPyApi import qxapp, qxcmd
    from qfxPyApi.qxmod import boundary as bc, dynamicMesh as dm, material, monitor, physics, region, solverset, types, numerics
    from qfxPyApi.qxmod.runtime import getActiveModel

    def scalar(value):
        """保留原生常量及引用。"""
        obj = types.variant(); obj.value = value; KEEP.append(obj)
        return obj

    def collect(model):
        """将原生 interleaved aabb 转为 xmin/ymin/zmin/xmax/ymax/zmax。"""
        zones = []
        faces = {}
        for zone in model.qxZoneMng:
            box = list(zone.aabb)
            zones.append({'id':zone.id,'name':zone.name,'cells':zone.cellCount,'nodes':zone.pointCount,
                          'bbox_m':[box[i] for i in (0,2,4,1,3,5)]})
            for i in range(zone.surfaceCount):
                surface = zone.surface(i)
                faces[(zone.id,surface.name)] = surface.count
        boundaries = []
        for boundary in model.boundaryMng:
            condition = boundary.bCondition
            entry = {'id':boundary.id,'name':boundary.name,'zone_id':boundary.zoneId,
                     'faces':faces[(boundary.zoneId,boundary.name)],'condition_class':type(condition).__name__,
                     'paired':bool(condition.isPaired())}
            if entry['condition_class'] == 'CBCPressInlet':
                entry['pressure_Pa'] = float(condition.pri.totalPressure.value)
            if entry['condition_class'] == 'CBCPressOutlet':
                entry['pressure_Pa'] = float(condition.pri.staticPressure.value)
            boundaries.append(entry)
        return {'zones':zones,'boundaries':boundaries,
                'regions':[{'name':r.name,'zone_ids':list(r.zoneIds)} for r in model.regionMng],
                'momentum_convection':int(model.regionMng[0].numMethod.discreteScheme.discreteFormat.momentum.convection)}

    qfx = case_path(root,cfg['files']['qfx']); run = case_path(root,cfg['files']['run'])
    solver = cfg['solver']; ph = cfg['physics']; rot = cfg['rotation']
    scheme_enum = int(getattr(numerics.momentumDiscreteOption.momentumTypeEnum,solver['momentum_scheme']))
    qxapp.initialize()
    if args.action == 'setup':
        require(not qfx.exists(), '拒绝覆盖已有工程，重试请新建阶段')
        qxcmd.ICmdImportMesh([str(case_path(root,cfg['mesh']['file']))])
        model = getActiveModel()
        imported = collect(model)
        write_json(root/'checks/qflux_import_inventory.json',imported)
        verify_inventory(cfg,imported,evidence)
        require(len(model.regionMng) == 1 and not any(len(r.motions) for r in model.regionMng), '仅接受单流体纯网格源工程')
        qxcmd.ICmdSetRegionName(model.regionMng[0].id,REGION_NAME)
        zones = {z.name:z for z in model.qxZoneMng}
        qxcmd.ICmdSetRegionZone(REGION_NAME,[z.id for z in zones.values()])
        qxcmd.ICmdSetTimeMode(region.txSolverPatternESTType.Steady)
        turbulence = physics.CTurbulenceModel.Create(physics.CTurbulenceModelTurbulenceMethod.KE)
        turbulence.options = 2; turbulence.wallFunction = 3; turbulence.buoyancy = False
        qxcmd.ICmdSetTurbulence(REGION_NAME,turbulence); qxcmd.ICmdSetEnergy(REGION_NAME,False)
        air = material.material.Create(material.materialTypeEnum.Gas); air.name = 'fan_constant_gas'
        for key,value in [('Density',ph['density_kg_m3']),('Viscosity',ph['viscosity_Pa_s']),('SpecialHeat',1006.),('ThermalConduct',.0263)]:
            prop = air.getProperty(getattr(material.matPropertyBase,key)); variant = material.materialVariant()
            variant.value = value; prop.method = 1; prop.value = variant; KEEP.extend([prop,variant])
        qxcmd.ICmdAddProjectMaterial(air); qxcmd.ICmdSetRegionMaterial(REGION_NAME,air.name)
        KEEP.extend([air,turbulence])
        boundaries = {b.name:b for b in model.boundaryMng}
        for name,entry in cfg['boundaries'].items():
            kind = entry['kind']
            if kind == 'wall':
                condition = bc.CBCWall()
            elif kind == 'interface':
                condition = bc.CBCInterfaceBoundary(); pri = condition.pri; pri.mergeable = True; condition.pri = pri; KEEP.append(pri)
            elif kind == 'pressure_inlet':
                condition = bc.CBCPressInlet(); pri = condition.pri; pri.directionType = 1
                pri.totalPressure = scalar(entry['pressure_Pa']); pri.staticPressure = scalar(0.); condition.pri = pri; KEEP.append(pri)
            elif kind == 'pressure_outlet':
                condition = bc.CBCPressOutlet(); pri = condition.pri
                pri.staticPressure = scalar(entry['pressure_Pa']); condition.pri = pri; KEEP.append(pri)
            qxcmd.ICmdSetBoundaryCondition(name,condition); KEEP.append(condition)
        for a,b in cfg['interface_pairs']:
            condition = bc.CBCInterfaceBoundary(); pri = condition.pri; pri.mergeable = True; condition.pri = pri
            condition.surfaceId = boundaries[b].id
            qxcmd.ICmdSetBoundaryPaired(a,b,condition); KEEP.extend([condition,pri])
        motion = dm.txDynMeshRegion.Create(0); motion.name = 'fan_MRF'; motion.motionType = 0
        qxcmd.ICmdAddDynamicMesh(REGION_NAME,motion); actual = model.regionMng[0].motions[0]
        qxcmd.ICmdDynamicMeshAddZone(REGION_NAME,actual.id,[zones[rot['zone']].id])
        body = dm.txCustomRigidBody(); body.name = 'fan_rotor'; body.boundaryType = 0; body.walls = []
        rotate = dm.txDefineAxisAngleVelocity(); rotate.axis = rot['axis_unit']; rotate.velocity = scalar(rot['omega_rad_s']); body.rotate = rotate
        coord = body.rigidCoordSystem; origin = coord.unitOrigin; origin.value = cfg['geometry']['axis_origin_m']; coord.unitOrigin = origin; body.rigidCoordSystem = coord
        qxcmd.ICmdAddRigidBody(REGION_NAME,actual.id,body)
        for frame in ('global','rotating'):
            names = [n for n,b in cfg['boundaries'].items() if b['kind'] == 'wall' and b['frame'] == frame]
            if names:
                qxcmd.ICmdSetBoundaryReferenceFrame(names,int(frame == 'rotating'))
        operation = model.regionMng[0].operationCondition
        for key,value in [('unitPress',ph['reference_pressure_Pa']),('unitDensity',ph['density_kg_m3']),('unitPosition',solver['reference_position_m'])]:
            prop = getattr(operation,key); prop.value = value; setattr(operation,key,prop); KEEP.append(prop)
        gravity = operation.unitGravity; gravity.on = False; operation.unitGravity = gravity
        qxcmd.ICmdSetOperationCondition(REGION_NAME,operation)
        init = model.regionMng[0].initialize.flowInit; init.initMethod = 1; public = init.fieldParam
        for key,value in [('unitVelocity',solver['initial_velocity_m_s']),('unitPressure',0.),('unitTemperature',ph['temperature_K']),('unitDensity',ph['density_kg_m3']),('unitK',solver['initial_k_m2_s2']),('unitEpsilon',solver['initial_epsilon_m2_s3'])]:
            prop = getattr(public,key); prop.value = value; prop.on = True; setattr(public,key,prop); KEEP.append(prop)
        init.fieldParam = public; qxcmd.ICmdSetFluidInitCondition(REGION_NAME,init)
        nm = model.regionMng[0].numMethod; ds = nm.discreteScheme; fmt = ds.discreteFormat; momentum = fmt.momentum
        momentum.convection = scheme_enum; fmt.momentum = momentum; fmt.stable = True; ds.discreteFormat = fmt; nm.discreteScheme = ds
        relax = nm.relaxationFactor
        for key,value in solver['relaxation'].items():
            prop = key+'Curve'; curve = getattr(relax,prop); curve.value = value; setattr(relax,prop,curve); KEEP.append(curve)
        nm.relaxationFactor = relax; control = nm.solverControl; pressure = control.pressure
        pressure.nNonOrthCorrs = solver['nonorth_corrections']; control.pressure = pressure; nm.solverControl = control
        qxcmd.ICmdSetFluidNumMethod(REGION_NAME,nm)
        for name,entry in cfg['boundaries'].items():
            if entry['kind'] == 'wall':
                continue
            for prefix,method in [('mass_',monitor.txMonitorFaceMethod.MassFlowRate),('volume_',monitor.txMonitorFaceMethod.VolumeFlowRate)]:
                face = monitor.txMonitorFaceDefine(); face.ids = [boundaries[name].id]
                mon = monitor.txMonitorBase.Create(monitor.txMonitorType.Face); mon.name = prefix+name
                mon.regions = [model.regionMng[0].id]; mon.faceDefinition = face; mon.method = int(method)
                qxcmd.ICmdAddMonitor(mon); KEEP.extend([face,mon])
        mpi = solverset.txMPIParallel(); mpi.flagMPI = True; mpi.numCoreMPI = solver['cores']; qxcmd.ICmdSetMPIParallel(mpi)
        it = model.solverSet.iteration; it.iterations = solver['max_iterations']; it.autoSaveFreqType = 0
        it.autoSaveIteration = solver['save_interval']; it.name = cfg['name']; it.folder = str(run)
        it.savePathType = 0; it.dataFormat = 'qfx'; qxcmd.ICmdSetIterationControl(it)
        qxcmd.ICmdSetFluidInitCondition(REGION_NAME,init)
        KEEP.extend([motion,actual,body,rotate,coord,origin,operation,gravity,init,public,nm,ds,fmt,momentum,relax,control,pressure,mpi,it])
        staging = qfx.with_name(qfx.stem+'_staging.qfx')
        require(not staging.exists(), '存在未完成 staging 工程，先检查来源')
        qfx.parent.mkdir(parents=True,exist_ok=True)
        save = qxcmd.ICmdSaveCaseParameter(); save.caseFile = str(staging); save.fileType = 1; save.persistence = qxcmd.ESaveCasePersistence.ProjectFile
        qxcmd.ICmdSaveCase(save); require(staging.is_file() and staging.stat().st_size > 0,'保存未生成工程')
        os.replace(str(staging),str(qfx))
        write_json(qfx.parent/'setup_provenance.json',{'qfx_sha256':digest(qfx),'case_sha256':config_hash(cfg),'setup_pid':os.getpid(),'solved':False})
        print('QFLUX_SETUP_SAVED_NO_SOLVE',flush=True)
    else:
        provenance = read_json(qfx.parent/'setup_provenance.json')
        require(provenance['case_sha256'] == config_hash(cfg) and provenance['qfx_sha256'] == digest(qfx),'工程或配置在setup后变化')
        opened = qxcmd.ICmdOpenCaseParameter(); opened.caseFile = str(qfx); qxcmd.ICmdOpenCase(opened)
        model = getActiveModel(); output = qfx.parent/'qflux_readback_settings.json'; qxcmd.ICmdExportCaseJson(str(output))
        settings = read_json(output); inventory = collect(model)
        verify_settings(cfg,settings,inventory,evidence,scheme_enum)
        require(Path(settings['couplingSolver']['save']['path']).resolve() == run, '原生保存路径不符')
        report = {'passed':True,'independent_readback':True,'solved':False,'case_sha256':config_hash(cfg),
                  'qfx_sha256':digest(qfx),'mesh_sha256':cfg['mesh']['sha256'],'mesh_gate_sha256':digest(root/'checks/mesh_gate.json'),
                  'settings_sha256':digest(output),'inventory':inventory,'readback_pid':os.getpid()}
        write_json(qfx.parent/'qflux_readback.json',report)
        print('QFLUX_INDEPENDENT_READBACK_PASSED_NO_SOLVE',flush=True)
    # 某些厂商版本在解释器析构时崩溃；上述文件全部关闭并刷出后结束独立进程。
    sys.stdout.flush(); sys.stderr.flush(); os._exit(0)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc(); sys.stdout.flush(); sys.stderr.flush(); os._exit(1)

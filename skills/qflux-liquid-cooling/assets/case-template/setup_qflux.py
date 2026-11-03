# -*- coding: utf-8 -*-
"""用官方 API 建立稳态水力工程；脚本可在远程 Windows 台式机直接执行。"""
from pathlib import Path
ROOT=Path(__file__).resolve().parent
import sys
sys.path.insert(0,str(ROOT))  # 嵌入式 Python 的 _pth 可能不包含脚本目录。
from runtime_config import read_config, bootstrap_qflux
CFG=read_config()
SOLVER=CFG['solver']
MAX_ITERATIONS=SOLVER['max_iterations']
SAVE_INTERVAL=SOLVER['save_interval']
MPI_CORES=SOLVER['mpi_cores']
RESIDUAL_LIMIT=SOLVER['residual_limit']
import os,sys,json,traceback
COOKIE=bootstrap_qflux()
from qfxPyApi import qxapp,qxcmd
from qfxPyApi.qxmod import material,region,physics,boundary as bc,types,monitor,solverset
from qfxPyApi.qxmod.runtime import getActiveModel
from qfxPyApi.qxmod.numerics import momentumDiscreteOption
KEEP=[]

def scalar(value):
    """创建常量标量；延长原生子对象寿命到工程保存结束。"""
    obj=types.variant();obj.value=float(value);KEEP.append(obj);return obj

def add_monitor(model,name,patch,method,variables):
    """使用真实边界 ID 监测压强、流速和质量流量。"""
    mon=monitor.txMonitorBase.Create(monitor.txMonitorType.Face);mon.name=name
    mon.regions=[model.regionMng[0].id]
    faces=monitor.txMonitorFaceDefine();faces.ids=[model.boundaryMng[i].id for i in range(len(model.boundaryMng)) if model.boundaryMng[i].name==patch]
    if len(faces.ids)!=1:raise RuntimeError('监测边界缺失或重名：'+patch)
    mon.faceDefinition=faces;mon.method=int(method);mon.precision=10
    for var in mon.variable:var.state=1 if var.innerName in variables else 0
    qxcmd.ICmdAddMonitor(mon);KEEP.extend([mon,faces])

def main():
    config=json.loads((ROOT/'case_parameters.json').read_text(encoding='utf-8'))
    check=json.loads((ROOT/'mesh_check.json').read_text(encoding='utf-8'))
    op=config['operating'];qxapp.initialize();qxcmd.ICmdImportMesh([str(ROOT/'parallel_cooling_m.cgns')]);model=getActiveModel()
    qxcmd.ICmdSetRegionName(model.regionMng[0].id,'coolant')
    actual={model.boundaryMng[i].name for i in range(len(model.boundaryMng))}
    if actual!=set(check['regions']['fluid_network']['boundaries']):raise RuntimeError('QFlux 导入边界名称不一致')
    qxcmd.ICmdSetTimeMode(region.txSolverPatternESTType.Steady)
    turb=physics.CTurbulenceModel.Create(physics.CTurbulenceModelTurbulenceMethod.KW)
    qxcmd.ICmdSetTurbulence('coolant',turb);qxcmd.ICmdSetEnergy('coolant',False);KEEP.append(turb)
    water=material.material.Create(material.materialTypeEnum.Liquid);water.name='Water_'+format(op['temperature_C'],'g')+'C'
    for propname,val in [('Density',op['density_kg_m3']),('Viscosity',op['viscosity_Pa_s']),('SpecialHeat',4181.3),('ThermalConduct',.607)]:
        prop=water.getProperty(getattr(material.matPropertyBase,propname));value=material.materialVariant();value.value=val;prop.method=1;prop.value=value;KEEP.extend([prop,value])
    qxcmd.ICmdAddProjectMaterial(water);qxcmd.ICmdSetRegionMaterial('coolant',water.name);KEEP.append(water)
    area=check['regions']['fluid_network']['inlet_area_m2'];speed=op['flow_lpm']*1e-3/60/area
    inlet=bc.CBCVeloInlet();p=inlet.pri;p.directionType=1;p.velocityMag=scalar(speed);inlet.pri=p
    qxcmd.ICmdSetBoundaryCondition('inlet',inlet);KEEP.extend([inlet,p])
    outlet=bc.CBCPressOutlet();p=outlet.pri;p.staticPressure=scalar(op['outlet_gauge_pressure_Pa']);outlet.pri=p
    qxcmd.ICmdSetBoundaryCondition('outlet',outlet);KEEP.extend([outlet,p])
    for name in actual-{'inlet','outlet'}:
        wall=bc.CBCWall();qxcmd.ICmdSetBoundaryCondition(name,wall);KEEP.append(wall)
    # 显式设置格式和松弛，不以默认值推测精度。
    num=model.regionMng[0].numMethod
    scheme=num.discreteScheme;spatial=scheme.discreteFormat;momentum=spatial.momentum
    scheme_name=SOLVER['momentum_scheme']
    if scheme_name not in ['FirstUpwind','SecondUpwind']:raise ValueError('不支持的动量格式')
    momentum.convection=int(getattr(momentumDiscreteOption.momentumTypeEnum,scheme_name))
    spatial.momentum=momentum;scheme.discreteFormat=spatial;num.discreteScheme=scheme
    qxcmd.ICmdSetFluidNumMethod('coolant',num)
    relaxation=num.relaxationFactor
    for key,value in [('continuity',SOLVER['pressure_relaxation']),('momentum',SOLVER['momentum_relaxation']),('turbulence',SOLVER['turbulence_relaxation'])]:
        curve=getattr(relaxation,key);curve.value=value;setattr(relaxation,key,curve);KEEP.append(curve)
    qxcmd.ICmdSetFluidRelaxationFactor('coolant',relaxation)
    KEEP.extend([num,scheme,spatial,momentum,relaxation])
    # 统一采用 QFlux KW 默认的近壁处理，实际方法编号写入 settings.json 供追溯。
    # 各部件 Reynolds 数不同；保留低速流道湍流模型的不确定性，不宣称完全湍流。
    for patch in ['inlet','outlet']:
        add_monitor(model,'pressure_'+patch,patch,monitor.txMonitorFaceMethod.AreaWeighted,['p'])
        add_monitor(model,'mass_'+patch,patch,monitor.txMonitorFaceMethod.MassFlowRate,['rho'])
        add_monitor(model,'speed_'+patch,patch,monitor.txMonitorFaceMethod.AreaWeighted,['U.abs'])
    for i in range(len(model.monitorMng)):
        residual=model.monitorMng[i]
        if not isinstance(residual,monitor.txMonitorResidual):continue
        criterion=residual.criterion;criterion.flag=True;criterion.continuityOn=True;criterion.momentumOn=True
        criterion.continuity=RESIDUAL_LIMIT;criterion.momentum=RESIDUAL_LIMIT
        residual.criterion=criterion;qxcmd.ICmdSetMonitorProperty(residual.name,residual);KEEP.extend([criterion,residual])
    mpi=solverset.txMPIParallel();mpi.flagMPI=True;mpi.numCoreMPI=MPI_CORES;qxcmd.ICmdSetMPIParallel(mpi);KEEP.append(mpi)
    iteration=model.solverSet.iteration;iteration.iterations=MAX_ITERATIONS;iteration.autoSaveIteration=SAVE_INTERVAL;iteration.folder=str(ROOT/'run');iteration.name='parallel_cooling';qxcmd.ICmdSetIterationControl(iteration);KEEP.append(iteration)
    qxcmd.ICmdExportCaseJson(str(ROOT/'settings.json'))
    settings=json.loads((ROOT/'settings.json').read_text(encoding='utf-8-sig'))
    reg=next(r for r in settings['region'] if r['name']=='coolant')
    print('PERSISTED_TURBULENCE',reg['solver']['turbModel'],flush=True)
    print('INLET_SPEED',speed,'TOTAL_FLOW_LPM',op['flow_lpm'],flush=True)
    save=qxcmd.ICmdSaveCaseParameter();save.caseFile=str(ROOT/'parallel_cooling.qfx');save.fileType=1;save.persistence=qxcmd.ESaveCasePersistence.ProjectFile
    qxcmd.ICmdSaveCase(save)
    (ROOT/'setup_check.json').write_text(json.dumps({'computer':os.environ.get('COMPUTERNAME'),'qfx':save.caseFile,'inlet_speed_m_s':speed,'boundaries':sorted(actual),'mpi_cores':MPI_CORES,'turbulence':reg['solver']['turbModel']},indent=2),encoding='utf-8')
    print('QFX_SAVED',save.caseFile,flush=True)

if __name__=='__main__':
    try:main();sys.stdout.flush();sys.stderr.flush();os._exit(0)
    except Exception:traceback.print_exc();sys.stdout.flush();sys.stderr.flush();os._exit(1)

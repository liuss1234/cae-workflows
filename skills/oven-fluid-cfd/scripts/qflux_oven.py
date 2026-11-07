"""配置烘箱稳态等温工况；采用同一STAR切割体网格，不重新网格化。"""
from pathlib import Path
import os
import sys
import traceback

# 参数从case.json读取，入口速度和物性不取历史案例。
sys.path.insert(0,str(Path(__file__).resolve().parent))
import qflux_case as core
BASE_SETUP = core.setup_basic


def setup(command, model, root, cfg, manifest):
    """在基础单流体设置后明确写入Realizable k-epsilon和双层近壁处理。"""
    BASE_SETUP(command, model, root, cfg, manifest)
    region_name = manifest["zones"][0]["region"]
    from qfxPyApi.qxmod import physics, monitor
    turbulence=physics.CTurbulenceModel.Create(physics.CTurbulenceModelTurbulenceMethod.KE)
    turbulence.options=2
    turbulence.wallFunction=3
    turbulence.buoyancy=False
    command.ICmdSetTurbulence(region_name,turbulence)
    core.KEEP.append(turbulence)
    # 明确参考绝压与等温物性温度；关闭浮力，保持两软件定义一致。
    operation=model.regionMng[0].operationCondition
    pressure=operation.unitPress;pressure.value=cfg["physics"]["reference_pressure_Pa"];operation.unitPress=pressure
    density=operation.unitDensity;density.value=cfg["physics"]["material"]["Density"];operation.unitDensity=density
    gravity=operation.unitGravity;gravity.on=False;operation.unitGravity=gravity
    command.ICmdSetOperationCondition(region_name,operation)
    init=model.regionMng[0].initialize.flowInit;init.initMethod=1
    public=init.fieldParam
    for name,value in [("unitVelocity",[0.,0.,0.]),("unitPressure",0.),("unitTemperature",cfg["physics"]["temperature_K"]),("unitDensity",cfg["physics"]["material"]["Density"]),("unitK",cfg["physics"]["initial_k_m2_s2"]),("unitEpsilon",cfg["physics"]["initial_epsilon_m2_s3"])]:
        entry=getattr(public,name);entry.value=value;entry.on=True;setattr(public,name,entry);core.KEEP.append(entry)
    init.fieldParam=public;command.ICmdSetFluidInitCondition(region_name,init)
    core.KEEP.extend([operation,pressure,density,gravity,init,public])
    for index in range(len(model.monitorMng)):
        item=model.monitorMng[index]
        if isinstance(item,monitor.txMonitorResidual):
            criterion=item.criterion
            criterion.flag=True
            criterion.continuityOn=True
            criterion.momentumOn=True
            criterion.turbulenceOn=True
            criterion.continuity=cfg["solver"]["residual_limit"]
            criterion.momentum=cfg["solver"]["residual_limit"]
            criterion.turbulence=cfg["solver"]["residual_limit"]
            item.criterion=criterion
            command.ICmdSetMonitorProperty(item.name,item)
            core.KEEP.extend([criterion,item])
    # 同时保留每个风嘴的实际体积流量，不强制均分。
    for patch in manifest["zones"][0]["boundaries"]:
        if patch["role"] in ["velocity_inlet","pressure_outlet"]:
            core.add_monitor(command,model,"volume_"+patch["name"],patch["name"],region_name,monitor.txMonitorFaceMethod.VolumeFlowRate,["rho"])


if __name__=="__main__":
    core.setup_basic=setup
    try:
        core.main()
        sys.stdout.flush()
        os._exit(0)
    except Exception:
        traceback.print_exc();sys.stderr.flush();os._exit(1)

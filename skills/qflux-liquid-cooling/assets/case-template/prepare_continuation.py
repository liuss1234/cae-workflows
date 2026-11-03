# -*- coding: utf-8 -*-
"""从已完成数据续算：降低松弛，保持网格、工况和空间离散格式。"""
from pathlib import Path
ROOT=Path(__file__).resolve().parent
import sys
sys.path.insert(0,str(ROOT))
from runtime_config import read_config, bootstrap_qflux
CFG=read_config()
FINAL_ITERATION=CFG['continuation']['additional_iterations']
PRESSURE_RELAXATION=CFG['solver']['pressure_relaxation']
MOMENTUM_RELAXATION=CFG['solver']['momentum_relaxation']
TURBULENCE_RELAXATION=CFG['solver']['turbulence_relaxation']
OUTPUT='run_stable'
import sys,os,traceback
COOKIE=bootstrap_qflux()
from qfxPyApi import qxapp,qxcmd
from qfxPyApi.qxmod.runtime import getActiveModel
KEEP=[]

def main():
    qxapp.initialize();p=qxcmd.ICmdOpenCaseParameter();p.caseFile=str(ROOT/CFG['continuation']['source_case']);p.onlyLoadCase=False;qxcmd.ICmdOpenCase(p)
    model=getActiveModel();num=model.regionMng[0].numMethod;relax=num.relaxationFactor
    for name,value in [('continuity',PRESSURE_RELAXATION),('momentum',MOMENTUM_RELAXATION),('turbulence',TURBULENCE_RELAXATION)]:
        curve=getattr(relax,name);curve.value=value;setattr(relax,name,curve);KEEP.append(curve)
    qxcmd.ICmdSetFluidRelaxationFactor('coolant',relax);KEEP.extend([num,relax])
    iteration=model.solverSet.iteration;iteration.iterations=FINAL_ITERATION;iteration.autoSaveType=1;iteration.autoSaveIteration=500;iteration.folder=str(ROOT/OUTPUT)
    qxcmd.ICmdSetIterationControl(iteration);KEEP.append(iteration)
    save=qxcmd.ICmdSaveCaseParameter();save.caseFile=str(ROOT/'parallel_cooling_stable.qfx');save.fileType=1;save.persistence=qxcmd.ESaveCasePersistence.ProjectFile;qxcmd.ICmdSaveCase(save)
    qxcmd.ICmdExportCaseJson(str(ROOT/'settings_stable.json'));print('PREPARED',save.caseFile,flush=True)

if __name__=='__main__':
    try:main();sys.stdout.flush();sys.stderr.flush();os._exit(0)
    except Exception:traceback.print_exc();sys.stdout.flush();sys.stderr.flush();os._exit(1)

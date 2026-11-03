# -*- coding: utf-8 -*-
"""生成一阶迎风稳健续算工程；仅在二阶阶段结束且未收敛时使用。"""
from pathlib import Path

# 所有可调参数集中于此，保持原几何、材料、湍流模型和边界条件。
ROOT = Path(__file__).resolve().parent
import sys
sys.path.insert(0,str(ROOT))
from runtime_config import read_config, bootstrap_qflux
CFG=read_config()
ADDITIONAL_ITERATIONS = CFG['continuation']['additional_iterations']
PRESSURE_RELAXATION = CFG['solver']['pressure_relaxation']
MOMENTUM_RELAXATION = CFG['solver']['momentum_relaxation']
TURBULENCE_RELAXATION = CFG['solver']['turbulence_relaxation']
OUTPUT = 'run_robust'

import os, sys, traceback
COOKIE = bootstrap_qflux()
from qfxPyApi import qxapp, qxcmd
from qfxPyApi.qxmod.runtime import getActiveModel
from qfxPyApi.qxmod.numerics import momentumDiscreteOption
KEEP = []


def main():
    """使用官方枚举修改动量对流格式，并导出可追溯原生配置。"""
    qxapp.initialize()
    param = qxcmd.ICmdOpenCaseParameter()
    param.caseFile = str(ROOT / CFG['continuation']['source_case'])
    param.onlyLoadCase = False
    qxcmd.ICmdOpenCase(param)
    model = getActiveModel()
    num = model.regionMng[0].numMethod
    scheme = num.discreteScheme
    spatial = scheme.discreteFormat
    momentum = spatial.momentum
    momentum.convection = int(momentumDiscreteOption.momentumTypeEnum.FirstUpwind)
    spatial.momentum = momentum
    scheme.discreteFormat = spatial
    num.discreteScheme = scheme
    qxcmd.ICmdSetFluidNumMethod('coolant', num)
    relaxation = num.relaxationFactor
    for name, value in [('continuity', PRESSURE_RELAXATION),
                        ('momentum', MOMENTUM_RELAXATION),
                        ('turbulence', TURBULENCE_RELAXATION)]:
        curve = getattr(relaxation, name)
        curve.value = value
        setattr(relaxation, name, curve)
        KEEP.append(curve)
    qxcmd.ICmdSetFluidRelaxationFactor('coolant', relaxation)
    iteration = model.solverSet.iteration
    iteration.iterations = ADDITIONAL_ITERATIONS
    iteration.folder = str(ROOT / OUTPUT)
    qxcmd.ICmdSetIterationControl(iteration)
    KEEP.extend([num, scheme, spatial, momentum, relaxation, iteration])
    save = qxcmd.ICmdSaveCaseParameter()
    save.caseFile = str(ROOT / 'parallel_cooling_robust.qfx')
    save.fileType = 1
    save.persistence = qxcmd.ESaveCasePersistence.ProjectFile
    qxcmd.ICmdSaveCase(save)
    qxcmd.ICmdExportCaseJson(str(ROOT / 'settings_robust.json'))
    print('PREPARED', save.caseFile, 'FirstUpwind=', momentum.convection, flush=True)


if __name__ == '__main__':
    try:
        main()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)

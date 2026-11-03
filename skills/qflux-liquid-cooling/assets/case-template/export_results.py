# -*- coding: utf-8 -*-
"""从远程求解的真实 DAT 导出 VTK，保存与源工程及迭代数的对应关系。"""
from pathlib import Path
ROOT=Path(__file__).resolve().parent
import sys
sys.path.insert(0,str(ROOT))
from runtime_config import bootstrap_qflux
SCALAR_FIELDS=['rho','U.x','U.y','U.z','U.mag','U.abs','p','nut','yPlus','y+']
import sys,os,json,traceback
COOKIE=bootstrap_qflux()
from qfxPyApi import qxapp,qxcmd
from qfxPyApi.qxmod.runtime import getActiveModel

def main():
    run=ROOT/(sys.argv[1] if len(sys.argv)>1 else 'run')
    finished=json.loads((run/'finished.json').read_text(encoding='utf-8-sig'))
    if finished['exitCode']!=0:raise RuntimeError('阶段未正常结束，拒绝导出')
    cases={'run':'parallel_cooling.qfx','run_stable':'parallel_cooling_stable.qfx','run_robust':'parallel_cooling_robust.qfx'}
    if run.name not in cases:raise ValueError('未定义该阶段的匹配工程：'+run.name)
    case=ROOT/cases[run.name]
    results=sorted(run.glob('parallel_cooling*-*.dat'),key=lambda p:int(p.stem.rsplit('-',1)[1]))
    if not results:raise RuntimeError('尚无求解结果')
    result=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else results[-1]
    if result.parent.resolve()!=run.resolve() or not result.is_file():raise ValueError('DAT 必须属于当前阶段')
    if result.stem.endswith('00000'):raise RuntimeError('只有初始化数据，不能作为仿真结果')
    qxapp.initialize();param=qxcmd.ICmdOpenCaseParameter();param.caseFile=str(case);param.onlyLoadCase=False;qxcmd.ICmdOpenCase(param)
    data=qxcmd.ICmdOpenDataParameter();data.dataFile=str(result);qxcmd.ICmdOpenData(data);model=getActiveModel()
    scalars=[{'id':model.scalarMng[i].id,'name':model.scalarMng[i].name,'field':model.scalarMng[i].fieldName} for i in range(len(model.scalarMng))]
    print('AVAILABLE_SCALARS',scalars,flush=True)
    selected=[s for s in scalars if s['field'] in SCALAR_FIELDS]
    output=ROOT/'post';output.mkdir(exist_ok=True)
    export=qxcmd.ICmdExportFileParameter();export.FileType=qxcmd.fileTypeEnum.vtk_xml;export.FilePath=str(output/'fluid_network.vtu');export.Zones=['fluid_network'];export.ScalarIDs=[s['id'] for s in selected];export.ScalarDataMethod=3
    qxcmd.ICmdExportFile(export)
    (output/'result_readback.json').write_text(json.dumps({'source_qfx':param.caseFile,'source_data':str(result),'selected_scalars':selected,'all_scalars':scalars,'zones':[{'name':model.qxZoneMng[i].name,'cells':model.qxZoneMng[i].cellCount,'nodes':model.qxZoneMng[i].pointCount} for i in range(len(model.qxZoneMng))]},indent=2),encoding='utf-8')
    print('EXPORTED',result,flush=True)

if __name__=='__main__':
    try:main();sys.stdout.flush();sys.stderr.flush();os._exit(0)
    except Exception:traceback.print_exc();sys.stdout.flush();sys.stderr.flush();os._exit(1)

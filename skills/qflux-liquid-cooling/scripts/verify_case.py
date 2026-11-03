# -*- coding: utf-8 -*-
"""独立进程回读 QFX，可选匹配 DAT；核对边界、类型、区域及格式。"""
from pathlib import Path
import argparse
import json
import os
import sys
import traceback
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))


def main():
    """不把保存成功等同于导入验收成功。"""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',default='parallel_cooling.qfx')
    parser.add_argument('--data')
    parser.add_argument('--scheme',choices=['FirstUpwind','SecondUpwind'])
    args=parser.parse_args()
    # 帮助参数先解析；真正回读时才加载工作副本配置和厂商 API。
    # 保留 DLL 目录句柄到函数结束，避免原生库在回读期间失去搜索路径。
    from runtime_config import bootstrap_qflux
    cookie=bootstrap_qflux()
    from qfxPyApi import qxapp,qxcmd
    from qfxPyApi.qxmod.runtime import getActiveModel
    expected=json.loads((ROOT/'mesh_check.json').read_text(encoding='utf-8'))['regions']['fluid_network']
    qxapp.initialize();p=qxcmd.ICmdOpenCaseParameter();p.caseFile=str((ROOT/args.case).resolve());p.onlyLoadCase=False;qxcmd.ICmdOpenCase(p)
    if args.data:
        d=qxcmd.ICmdOpenDataParameter();d.dataFile=str((ROOT/args.data).resolve());qxcmd.ICmdOpenData(d)
    model=getActiveModel()
    boundaries=[{'name':model.boundaryMng[i].name,'condition_class':type(model.boundaryMng[i].bCondition).__name__,'zone_id':model.boundaryMng[i].zoneId} for i in range(len(model.boundaryMng))]
    if {b['name'] for b in boundaries}!=set(expected['boundaries']):raise ValueError('边界名称不匹配')
    for b in boundaries:
        if b['condition_class']!={'inlet':'CBCVeloInlet','outlet':'CBCPressOutlet'}.get(b['name'],'CBCWall'):raise ValueError('边界类型不符：'+b['name'])
    if len(model.regionMng)!=1 or len(model.qxZoneMng)!=1:raise ValueError('区域数不匹配')
    z=model.qxZoneMng[0]
    if z.name!='fluid_network' or z.cellCount!=expected['cells'] or z.pointCount!=expected['nodes']:raise ValueError('区域名称或网格数量不匹配')
    qxcmd.ICmdExportCaseJson(str(ROOT/'readback_settings.json'))
    settings=json.loads((ROOT/'readback_settings.json').read_text(encoding='utf-8-sig'))
    actual=settings['region'][0]['numericMethod']['discreteAlgorithm']['spatial']['momentum']['convection']
    if args.scheme and actual!={'FirstUpwind':1,'SecondUpwind':2}[args.scheme]:raise ValueError('空间格式不符')
    report={'passed':True,'source_qfx':p.caseFile,'source_data':args.data,'cells':z.cellCount,'nodes':z.pointCount,'boundaries':boundaries,'momentum_convection_enum':actual,'turbulence':settings['region'][0]['solver']['turbModel']}
    (ROOT/'readback_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    try:main();sys.stdout.flush();sys.stderr.flush();os._exit(0)
    except Exception:traceback.print_exc();sys.stdout.flush();sys.stderr.flush();os._exit(1)

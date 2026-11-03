# -*- coding: utf-8 -*-
"""从本次参数、真实结果及回读记录生成技术说明，不填历史标杆值。"""
from pathlib import Path
import argparse
import csv
import json
ROOT=Path(__file__).resolve().parent


def main():
    """将工况、质量、收敛和精度限制一并交付。"""
    # 允许在尚未计算的电脑查看帮助，实际生成仍须在完整案例副本中运行。
    argparse.ArgumentParser(description=__doc__).parse_args()
    cfg=json.loads((ROOT/'case_parameters.json').read_text(encoding='utf-8'))
    mesh=json.loads((ROOT/'mesh_check.json').read_text(encoding='utf-8'))
    result=json.loads((ROOT/'results_summary/simulation_summary.json').read_text(encoding='utf-8'))
    readback=json.loads((ROOT/'readback_check.json').read_text(encoding='utf-8'))
    run=Path(result['run_directory'])
    job=json.loads((run/'job.json').read_text(encoding='utf-8-sig'))
    rows=list(csv.DictReader((ROOT/'results_summary/branch_flow.csv').open(encoding='utf-8-sig')))
    table='\n'.join('| '+r['支路编号_从下至上']+' | '+f"{float(r['流量_L_min']):.6f}"+' | '+f"{float(r['相对支路均值偏差_%']):+.3f}"+' |' for r in rows)
    status='通过本案例收敛检查' if result['convergence_checks_passed'] else '未通过全部收敛检查，属于阶段结果'
    report=f'''# 并联液冷管路 CFD 案例

计算状态：{status}。求解主机：{job['host']}，MPI 核数：{job.get('cores','原始记录未提供')}。

## 工况与模型

- 工况：{cfg['operating']}。
- 几何：{cfg['geometry']}。{cfg['branches']} 路；U 型异程布置；等效直通冷板，非产品实测结构。
- 稳态、不可压缩、标准 k–ω（非 SST）；无重力、无能量方程；光滑无滑移壁。
- 本次动量空间格式：{result['momentum_scheme']}。湍流/壁面设置原始记录：{readback['turbulence']}。
- CAD/STEP 长度单位 mm；CGNS/MSH/QFX 网格坐标 m。

## 网格与边界

HEX8 {mesh['regions']['fluid_network']['cells']} 单元，{mesh['regions']['fluid_network']['nodes']} 节点。
一个连通流体区域/网格区；{len(readback['boundaries'])} 个命名边界。

质量指标：{mesh['quality']}。零角度偏斜仅适用于本模板正交长方体单元。
CAD/网格相对体积差：{mesh['cad_mesh_relative_volume_error']:.3e}。

## 结果

| 指标 | 结果 |
|---|---:|
| 面积平均静压差 | {result['pressure_drop_Pa']:.3f} Pa |
| 单工况水力阻抗 Δp/Q | {result['hydraulic_resistance_Pa_s_m3']:.6g} Pa·s/m³ |
| 理论水力功率，不含泵效率 | {result['pump_hydraulic_power_W']:.6g} W |
| 支路 CV | {result['branch_CV_percent']:.3f}% |
| 最大相对均值偏差 | {result['branch_max_deviation_percent']:.3f}% |
| 最大/最小支路流量比 | {result['branch_max_min_ratio']:.6f} |
| 质量不平衡 | {result['mass_imbalance_percent']:.6g}% |
| 最后200次压降极差/末值 | {result['last_200_pressure_span_percent']:.6g}% |
| 重构积分总流量与入口通量偏差 | {result['reconstructed_sum_error_vs_inlet_percent']:.6g}% |

| 支路（从下至上） | 流量 L/min | 相对均值偏差 % |
|---|---:|---:|
{table}

最终残差：{result['residuals']}。支路流量来自真实单元速度场重构，未按总流量强制归一化；不等同于求解器修正后的守恒面通量。

## 打开结果

解压后打开 `{Path(result['source_qfx']).name}`，加载 `{run.name}/{Path(result['source_data']).name}`。
原保存路径可含求解机目录；本机重算先更新 workflow.json，并重新生成相应 QFX。
云图和统计见 results_summary；监测、stdout/stderr、启动/结束记录见 {run.name}。

## 限制

未开展网格收敛验证，不提供未经验证的离散误差。一阶迎风可能产生较大数值扩散；即使残差通过也不等于精度充分。
各支路 Re 见 CSV，局部层流/过渡流风险需结合实际工况判断；未核验的 y+ 不宣称合格。
本模板没有电芯产热、管壁导热和冷却液温升；单工况 Δp/Q 不代表完整阻力曲线。
'''
    (ROOT/'案例说明.md').write_text(report,encoding='utf-8')
    print(ROOT/'案例说明.md')


if __name__=='__main__':main()

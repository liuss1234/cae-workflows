# -*- coding: utf-8 -*-
"""按显式列读取真实监控历史，分别报告完整性与趋平，不推断物理有效性。"""
import argparse
import json
import math
import sys
from pathlib import Path

# 所有工况阈值通过命令行提供，不把历史项目值作为普适收敛标准。
def analyze(path, column, window, limit, minimum_scale, expected_iteration=None):
    """读取空白分隔历史，拒绝缺步/重复/NaN；零附近不给相对稳定通过。"""
    if window<2 or column<1 or limit<0 or minimum_scale<0:raise ValueError('列号、窗口或阈值不合法')
    rows=[]
    with Path(path).open(encoding='utf-8-sig') as f:
        for line in f:
            line=line.strip()
            if not line or line.startswith(('#','!')):continue
            fields=line.split()
            if len(fields)<=column:raise ValueError('历史列不完整')
            try:step=float(fields[0]);value=float(fields[column])
            except ValueError as exc:raise ValueError('非注释数据行无法解析') from exc
            if not step.is_integer() or not math.isfinite(step) or not math.isfinite(value):raise ValueError('非有限值或非整数迭代')
            if rows and step!=rows[-1][0]+1:raise ValueError('监控历史重复、缺步或顺序错误')
            rows.append((int(step),value))
    if len(rows)<window:raise ValueError('历史未达到完整统计窗口')
    if expected_iteration is not None and rows[-1][0]!=expected_iteration:raise ValueError('末步号与完成记录不同')
    tail=[r[1] for r in rows[-window:]];mean=sum(tail)/window;amplitude=max(tail)-min(tail)
    near_zero=abs(mean)<=minimum_scale
    span=None if near_zero else amplitude/abs(mean)*100
    return dict(window=window,iteration=rows[-1][0],mean=mean,minimum=min(tail),maximum=max(tail),
                absolute_span=amplitude,relative_span_percent=span,near_zero_mean=near_zero,
                plateau_passed=bool(not near_zero and span<=limit),limit_percent=limit,
                source_column=column,scope='monitor stability only; residual, conservation and physics separate')


def main():
    """列0为迭代，column从0计；单位沿用源历史。"""
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--history',required=True);p.add_argument('--column',type=int,default=1)
    p.add_argument('--window',type=int,required=True);p.add_argument('--limit-percent',type=float,required=True)
    p.add_argument('--minimum-scale',type=float,required=True);p.add_argument('--expected-iteration',type=int)
    p.add_argument('--output',required=True);a=p.parse_args()
    result=analyze(a.history,a.column,a.window,a.limit_percent,a.minimum_scale,a.expected_iteration)
    target=Path(a.output);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except Exception as exc:print(str(exc),file=sys.stderr);sys.exit(1)

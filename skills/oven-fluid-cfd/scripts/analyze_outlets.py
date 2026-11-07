# -*- coding: utf-8 -*-
"""对QFlux原生开口质量通量做同步窗口统计；只读小监控，不读完整场。"""
import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from cfd_common import read_json, sha256
from oven_case import boundary_map, positive

# 默认值来自本次诊断判据，并非行业统一标准；均可由命令行调整。
DEFAULT_WINDOW = 100
DEFAULT_MASS_LIMIT_PERCENT = 0.1
DEFAULT_SPAN_LIMIT_PERCENT = 0.5


def read_table(path):
    """跳过未完整写入的尾行；不把文件缺失、坏行或迭代重启隐藏成正常数据。"""
    path = Path(path)
    payload = path.read_bytes()
    text = payload.decode("utf-8-sig", errors="strict")
    lines = text.splitlines()
    if text and not text.endswith(("\n", "\r")):
        lines = lines[:-1]
    width, values, last = None, {}, -1
    for line in lines:
        fields = line.split()
        if not fields:
            continue
        if fields[0].lower() in ("#iter", "#iteration"):
            width = len(fields)
            if width != 2:
                raise ValueError("质量监控应为迭代与单标量两列：" + path.name)
            continue
        if fields[0].startswith("#"):
            continue
        if width is None or len(fields) != width:
            raise ValueError("监控头部缺失或完整行列数错误：" + path.name)
        row = [float(field.replace("D", "e").replace("d", "e")) for field in fields]
        if not math.isfinite(row[0]) or not row[0].is_integer():
            raise ValueError("迭代号无效：" + path.name)
        iteration = int(row[0])
        if iteration < last or (iteration in values and values[iteration] != row[1]):
            raise ValueError("监控迭代重启或冲突，请隔离阶段：" + path.name)
        values[iteration] = row[1]
        last = iteration
    if not values:
        raise ValueError("没有完整监控行：" + path.name)
    return values, {"name": path.name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def balance(values):
    """按全部外边界有符号通量计算收支，分母不采用净出口以免回流抵消。"""
    incoming = -sum(value for value in values if value < 0)
    outgoing = sum(value for value in values if value > 0)
    return 100 * abs(sum(values)) / max(incoming, outgoing, 1e-30)


def analyze(stage, manifest, region, density, window=DEFAULT_WINDOW,
            mass_limit=DEFAULT_MASS_LIMIT_PERCENT, span_limit=DEFAULT_SPAN_LIMIT_PERCENT):
    """同一迭代集合统计全部开口，明确窗口不足和反向流，不推定求解收敛。"""
    positive(density, "density")
    positive(mass_limit, "mass_limit", zero=True)
    positive(span_limit, "span_limit", zero=True)
    if not isinstance(window, int) or isinstance(window, bool) or window < 1:
        raise ValueError("窗口必须为正整数")
    patches = boundary_map(manifest)
    if region != manifest["zones"][0]["region"]:
        raise ValueError("监控region与语义清单不一致")
    inlets = [name for name, role in patches.items() if role == "velocity_inlet"]
    outlets = sorted(name for name, role in patches.items() if role == "pressure_outlet")
    if len(inlets) != 1 or not outlets:
        raise ValueError("当前统计要求一个入口和至少一个出口")
    histories, sources = {}, []
    for name in inlets + outlets:
        path = Path(stage) / "dat" / (region + "-mass_" + name + ".dat")
        histories[name], source = read_table(path)
        sources.append(source)
    common = sorted(set.intersection(*(set(history) for history in histories.values())))
    if not common:
        raise ValueError("所有开口没有共同完整迭代")
    end = common[-1]
    iterations = [iteration for iteration in common if iteration > end - window]
    complete = iterations == list(range(end - window + 1, end + 1))
    if any(not math.isfinite(history[iteration]) for history in histories.values() for iteration in iterations):
        raise ValueError("窗口存在NaN/Inf，拒绝输出有效分流统计")
    means = {name: sum(history[i] for i in iterations) / len(iterations) for name, history in histories.items()}
    incoming = -sum(means[name] for name in inlets)
    outgoing = sum(means[name] for name in outlets)
    negative_outlets = [name for name in outlets if any(histories[name][i] < 0 for i in iterations)]
    inlet_wrong = any(histories[name][i] >= 0 for name in inlets for i in iterations)
    direction_passed = not inlet_wrong and not negative_outlets and incoming > 0 and outgoing > 0
    conversion = 3600 / density
    average = outgoing / len(outlets)
    ideal = incoming / len(outlets)
    rows = []
    for name in outlets:
        samples = [histories[name][i] for i in iterations]
        mean = means[name]
        span = 100 * (max(samples) - min(samples)) / max(abs(mean), 1e-30)
        rows.append({"outlet": name, "mean_mass_flow_kg_s": mean, "mean_volume_flow_m3_h": mean * conversion,
                     "last_volume_flow_m3_h": histories[name][end] * conversion,
                     "deviation_from_outlet_mean_percent": 100 * (mean - average) / average if average > 0 else None,
                     "deviation_from_equal_inlet_percent": 100 * (mean - ideal) / ideal if ideal > 0 else None,
                     "outlet_share_percent": 100 * mean / outgoing if outgoing > 0 else None,
                     "relative_span_percent": span, "stable": complete and span <= span_limit})
    net = sum(means.values())
    errors = [balance([history[i] for history in histories.values()]) for i in iterations]
    inlet_errors = [100 * abs(sum(history[i] for history in histories.values())) /
                    max(abs(histories[inlets[0]][i]), 1e-30) for i in iterations]
    residual_error = 100 * abs(net) / max(abs(incoming), 1e-30)
    cv = 100 * math.sqrt(sum((means[name] - average) ** 2 for name in outlets) / len(outlets)) / average if average > 0 else None
    stable = all(row["stable"] for row in rows)
    mean_error = balance(list(means.values()))
    mass_passed = complete and direction_passed and max(errors) <= mass_limit and max(inlet_errors) <= mass_limit
    return {"scope": "仅监控诊断；不证明残差、网格或完整场验收通过",
            "density_kg_m3": density, "window_start": iterations[0], "window_end": end,
            "samples": len(iterations), "requested_window": window, "complete_window": complete,
            "mass_limit_percent": mass_limit, "span_limit_percent": span_limit,
            "inlet_mean_m3_h": incoming * conversion, "outlets_total_mean_m3_h": outgoing * conversion,
            "equal_inlet_share_m3_h": ideal * conversion, "outlet_mean_m3_h": average * conversion,
            "mean_mass_balance_error_percent": mean_error, "maximum_step_mass_balance_error_percent": max(errors),
            "mean_net_error_percent_of_inlet": residual_error, "maximum_step_net_error_percent_of_inlet": max(inlet_errors),
            "mass_balance_passed": mass_passed, "cv_percent": cv,
            "maximum_absolute_deviation_percent": max(abs(row["deviation_from_outlet_mean_percent"]) for row in rows) if average > 0 else None,
            "outlets_with_backflow": negative_outlets, "inlet_wrong_direction": inlet_wrong,
            "direction_passed": direction_passed, "distribution_valid": complete and direction_passed,
            "all_outlet_windows_stable": stable, "monitor_checks_passed": mass_passed and stable,
            "rows": rows, "source_monitor_files": sources}


def write_report(report, output):
    """新目录输出JSON/CSV及中文口径；拒绝覆盖已有统计。"""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with (output / "outlets.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with (output / "outlets.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(report["rows"][0]))
        writer.writeheader()
        writer.writerows(report["rows"])
    lines = ["# 出口流量监控诊断", "", report["scope"], "",
             "共同迭代{}–{}，{}步；完整窗口={}；反向出口={}。".format(
                 report["window_start"], report["window_end"], report["samples"], report["complete_window"], report["outlets_with_backflow"]), "",
             "| 出口 | 窗口平均m³/h | 相对出口平均偏差% | 窗口波动% |", "|---|---:|---:|---:|"]
    for row in report["rows"]:
        deviation = row["deviation_from_outlet_mean_percent"]
        lines.append("| {} | {:.6f} | {} | {:.6f} |".format(row["outlet"], row["mean_volume_flow_m3_h"],
                     "未定义" if deviation is None else "{:+.6f}".format(deviation), row["relative_span_percent"]))
    lines.extend(["", "CV={}%；均值通量守恒误差={}%；逐步最大守恒误差={}%。".format(
        report["cv_percent"], report["mean_mass_balance_error_percent"], report["maximum_step_mass_balance_error_percent"]), "",
        "分配偏差和守恒误差不等于网格或实验误差。残差、压力稳定性、调度状态和完整场需单独核对。", ""])
    (output / "outlets.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    """所有输入显式给定；默认不访问SSH、调度器或大型结果文件。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--regions", required=True, type=Path)
    parser.add_argument("--region", default="air")
    parser.add_argument("--density", required=True, type=float)
    parser.add_argument("--window", default=DEFAULT_WINDOW, type=int)
    parser.add_argument("--mass-limit-percent", default=DEFAULT_MASS_LIMIT_PERCENT, type=float)
    parser.add_argument("--span-limit-percent", default=DEFAULT_SPAN_LIMIT_PERCENT, type=float)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = analyze(args.stage, read_json(args.regions), args.region, args.density, args.window,
                     args.mass_limit_percent, args.span_limit_percent)
    report["regions_sha256"] = sha256(args.regions)
    write_report(report, args.output)
    print(json.dumps({key: value for key, value in report.items() if key not in ("rows", "source_monitor_files")}, ensure_ascii=False, indent=2))
    if not report["monitor_checks_passed"]:
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print("流量统计失败：" + str(error), file=sys.stderr)
        sys.exit(1)

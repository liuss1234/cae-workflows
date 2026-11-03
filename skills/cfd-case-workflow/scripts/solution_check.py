# -*- coding: utf-8 -*-
"""按外部规则验收残差、守恒、监测稳定与结果来源，不绑定变量数量或案例名称。"""
from pathlib import Path
import argparse
import json
import math
import sys
import traceback
from cfd_common import context, inside, read_json, write_json, sha256

# 守恒量使用求解器有符号通量；相对稳定性分母下限由每个监测自行指定。
REQUIRED_LOG_SUCCESS = "solver finished, code = 0"


def history(path):
    """读取 QFlux 文本监测，拒绝非有限、截断、重复或倒退的迭代记录。"""
    columns, rows = None, []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            names = line.lstrip("#").split()
            if names and names[0].lower() == "iter":
                columns = names
            continue
        if columns is None:
            raise ValueError("监测缺少 #iter 表头：" + str(path))
        values = [float(x) for x in line.split()]
        if len(values) != len(columns) or not all(math.isfinite(x) for x in values):
            raise ValueError("监测行截断或非有限：%s:%d" % (path, number))
        if values[0] != int(values[0]) or (rows and values[0] <= rows[-1]["iter"]):
            raise ValueError("监测迭代号重复或倒退：" + str(path))
        rows.append(dict(zip(columns, values)))
    if not rows:
        raise ValueError("监测没有有效数值：" + str(path))
    return rows


def balance(stage, spec, energy=False):
    """质量按进/出流量较大值归一化；能量按显式功率尺度归一化。"""
    terms, iterations = [], []
    for term in spec["terms"]:
        multiplier = float(term.get("multiplier", 1.0))
        if "constant_W" in term and energy:
            value = float(term["constant_W"])
            origin = "constant_W"
        else:
            rows = history(inside(stage, term["file"]))
            value = rows[-1][term["column"]]
            iterations.append(int(rows[-1]["iter"]))
            origin = term["file"] + ":" + term["column"]
        terms.append({"origin": origin, "signed_value": multiplier * value})
    if not terms or (iterations and len(set(iterations)) != 1):
        raise ValueError("守恒项为空或末迭代不一致")
    positive = sum(max(t["signed_value"], 0) for t in terms)
    negative = -sum(min(t["signed_value"], 0) for t in terms)
    denominator = float(spec["normalization_W"]) if energy else max(positive, negative)
    if denominator <= 0:
        raise ValueError("守恒归一化尺度必须大于零")
    error = 100 * abs(positive - negative) / denominator
    return {"passed": error <= spec["limit_percent"], "imbalance_percent": error,
            "limit_percent": spec["limit_percent"], "normalization": denominator,
            "iteration": iterations[0] if iterations else None, "terms": terms}


def main():
    """即使未合格也落盘验收记录；缺少必要证据时不报告计算合格。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--output", help="新 JSON 文件，默认 checks/acceptance_<stage>.json")
    parser.add_argument("--final-readback", help="可替代官方导出的最终 QFX+DAT 独立回读记录")
    args = parser.parse_args()
    root, cfg, _ = context(args.case)
    stage = inside(root, "runs/" + args.stage)
    out = inside(root, args.output or ("checks/acceptance_" + args.stage + ".json"))
    if out.exists():
        raise FileExistsError(out)
    finished = read_json(stage / "finished.json")
    rules = cfg["validation"]
    checks, issues = {}, []
    expected_iter = finished.get("final_iteration")
    if finished.get("exit_code") != 0 or not finished.get("final_data") or expected_iter is None:
        raise ValueError("没有正常完成阶段和完整 DAT")
    qfx_hash = sha256(inside(root, cfg["files"]["qfx"]))
    data_hash = sha256(inside(root, finished["final_data"]))
    checks["sources"] = {"passed": qfx_hash == finished["qfx_sha256"] and data_hash == finished["final_data_sha256"],
                         "qfx_sha256": qfx_hash, "data_sha256": data_hash, "final_iteration": expected_iter}
    final_check_path = inside(root, args.final_readback or ("post/" + args.stage + "/check.json"))
    final_check = read_json(final_check_path) if final_check_path.is_file() else {}
    checks["official_final_readback"] = {"passed": bool(final_check.get("passed") and final_check.get("independent_readback") and
                                                    final_check.get("source_sha256") == qfx_hash and final_check.get("source_data_sha256") == data_hash)}
    if not rules.get("residual"):
        issues.append("未配置残差验收")
    else:
        try:
            spec = rules["residual"]
            rows = history(inside(stage, spec["file"]))
            last = rows[-1]
            values = {k: {"value": last[k], "limit": float(v), "passed": 0 <= last[k] <= float(v)} for k, v in spec["columns"].items()}
            difference = expected_iter - int(last["iter"])
            allowed = int(spec.get("allow_final_iteration_offset", 0))
            stdout = (stage / "solver_stdout.log").read_text(encoding="utf-8", errors="replace")
            offset_ok = difference == 0 or (difference == 1 and allowed == 1 and "Convergent: Residual" in stdout and REQUIRED_LOG_SUCCESS in stdout)
            checks["residual"] = {"passed": bool(values) and all(v["passed"] for v in values.values()) and offset_ok,
                                  "iteration": int(last["iter"]), "final_iteration_offset": difference,
                                  "offset_evidence_valid": offset_ok, "columns": values}
        except Exception as exc:
            checks["residual"] = {"passed": False, "error": str(exc)}
    for label, key, energy in [("mass", "mass_balance", False), ("energy", "energy_balance", True)]:
        spec = rules.get(key)
        if spec:
            try:
                check = balance(stage, spec, energy)
                check["passed"] = check["passed"] and check["iteration"] in [None, expected_iter]
                checks[label] = check
            except Exception as exc:
                checks[label] = {"passed": False, "error": str(exc)}
        elif label == "mass" or cfg.get("physics", {}).get("energy") is True:
            issues.append("未配置" + label + "守恒验收")
    monitors = []
    for spec in rules.get("monitors", []):
        try:
            rows = history(inside(stage, spec["file"]))
            count = int(spec["tail"])
            if count < 2:
                raise ValueError("稳定性窗口至少两个采样")
            sample = [row[spec["column"]] for row in rows[-count:]]
            mean = sum(sample) / len(sample)
            denominator = max(abs(mean), float(spec["absolute_floor"]))
            if denominator <= 0:
                raise ValueError("稳定性分母下限必须为正")
            span = max(sample) - min(sample)
            relative = 100 * span / denominator
            passed = len(sample) == count and relative <= spec["relative_span_limit_percent"] and int(rows[-1]["iter"]) == expected_iter
            monitors.append({"passed": passed, "file": spec["file"], "column": spec["column"], "tail_count": len(sample),
                             "last": sample[-1], "mean": mean, "absolute_span": span, "relative_span_percent": relative,
                             "normalization": denominator, "limit_percent": spec["relative_span_limit_percent"]})
        except Exception as exc:
            monitors.append({"passed": False, "file": spec["file"], "error": str(exc)})
    checks["monitor_stability"] = {"passed": bool(monitors) and all(m["passed"] for m in monitors), "monitors": monitors}
    if not monitors:
        issues.append("未配置工程量稳定性验收")
    report = {"accepted": not issues and all(c["passed"] for c in checks.values()), "checks": checks, "missing_evidence": issues,
              "case_config_changed_since_run": finished.get("case_config_sha256") != sha256(root / "case.json"),
              "grid_convergence_study": cfg["mesh"].get("grid_convergence_study"), "prism_layers": cfg["mesh"].get("prism_layers"),
              "scope": "仅本次阶段的代数收敛、守恒、监测稳定及来源；不证明网格无关、模型正确或实验符合度"}
    write_json(out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)

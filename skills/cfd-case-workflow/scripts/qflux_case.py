# -*- coding: utf-8 -*-
"""QFlux 官方 API：基础等温设置、通用独立回读与完成场导出。需匹配 ABI 的 Python。"""
from pathlib import Path
import argparse
import json
import os
import sys
import traceback
import xml.etree.ElementTree as ET

# 嵌入式 Python 的 _pth 可能不含脚本目录，先显式加入，再加载同目录工具。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cfd_common import context, inside, read_json, write_json, sha256, exclusive_directory

# 仅对基础设置使用默认类别；高级适配器应在 regions.json 指定 condition_class。
CONDITION_CLASSES = {"velocity_inlet": "CBCVeloInlet", "pressure_inlet": "CBCPressInlet",
                     "pressure_outlet": "CBCPressOutlet", "wall": "CBCWall", "symmetry": "CBCSymmetricBoundary",
                     "interface": "CBCInterfaceBoundary"}
KEEP = []


def bootstrap(env):
    """保持 DLL 目录句柄到原生操作结束，不在普通 Python 中混载厂商 ABI。"""
    if os.name != "nt":
        raise RuntimeError("本 QFlux API 适配器仅实测 Windows，其他平台需按厂商发行版适配")
    home = env.get("qflux_home", "")
    if not home or not Path(home).is_dir():
        raise ValueError("请在 environment.json 配置 qflux_home")
    sys.path.insert(0, home)
    KEEP.append(os.add_dll_directory(home))
    os.environ["PATH"] = home + os.pathsep + os.environ.get("PATH", "")
    from qfxPyApi import qxapp, qxcmd
    from qfxPyApi.qxmod.runtime import getActiveModel
    qxapp.initialize()
    return qxcmd, getActiveModel


def scalar(value):
    """原生常量及其子对象延长生命周期，避免在保存前失效。"""
    from qfxPyApi.qxmod import types
    result = types.variant()
    result.value = float(value)
    KEEP.append(result)
    return result


def collect(model):
    """读取真正的管理器对象，不把预期清单作为实际结果。"""
    report = {"regions": [], "zones": [], "boundaries": []}
    for i in range(len(model.regionMng)):
        item = model.regionMng[i]
        report["regions"].append({"id": item.id, "name": item.name, "is_solid": bool(item.isSolid), "zone_ids": list(item.zoneIds)})
    for i in range(len(model.qxZoneMng)):
        z = model.qxZoneMng[i]
        report["zones"].append({"id": z.id, "name": z.name, "nodes": z.pointCount, "cells": z.cellCount, "bbox": list(z.aabb),
                                "boundaries": {z.surface(j).name: z.surface(j).count for j in range(z.surfaceCount)}})
    for i in range(len(model.boundaryMng)):
        b = model.boundaryMng[i]
        report["boundaries"].append({"id": b.id, "name": b.name, "zone_id": b.zoneId,
                                     "condition_class": type(b.bCondition).__name__})
    return report


def validate(report, mesh, manifest, cfg, check_conditions=True):
    """核对完整名称集合、归属、节点/体/面数量、物理区域和米制尺寸。"""
    if mesh.get("units") != "m":
        raise ValueError("网格检查文件需要 units=m")
    zones = {z["name"]: z for z in report["zones"]}
    expected = mesh["zones"]
    if len(zones) != len(report["zones"]) or set(zones) != set(expected):
        raise ValueError("网格区缺失、重复或多余")
    metadata = {z["name"]: z for z in manifest["zones"]}
    for name, source in expected.items():
        actual = zones[name]
        if any(actual[k] != source[k] for k in ["cells", "nodes", "boundaries"]):
            raise ValueError("节点、单元或边界面数改变：" + name)
        target = [v for pair in zip(*source["bbox_m"]) for v in pair]
        if len(actual["bbox"]) != 6 or max(abs(a - b) for a, b in zip(actual["bbox"], target)) > cfg["validation"]["bbox_tolerance_m"]:
            raise ValueError("米制包围盒改变：" + name)
    patches = {b["name"]: (z["name"], b) for z in manifest["zones"] for b in z["boundaries"]}
    actual_names = [b["name"] for b in report["boundaries"]]
    if len(actual_names) != len(patches) or set(actual_names) != set(patches):
        raise ValueError("边界名称缺失、重复或多余")
    for b in report["boundaries"]:
        zone_name, spec = patches[b["name"]]
        if zones[zone_name]["id"] != b["zone_id"]:
            raise ValueError("边界归属错误：" + b["name"])
        expected_class = spec.get("condition_class") or CONDITION_CLASSES[spec["role"]]
        if check_conditions and b["condition_class"] != expected_class:
            raise ValueError("边界类别错误：%s %s != %s" % (b["name"], b["condition_class"], expected_class))
    if check_conditions:
        regions = {r["name"]: r for r in report["regions"]}
        expected_names = {z["region"] for z in manifest["zones"]}
        if len(regions) != len(report["regions"]) or set(regions) != expected_names:
            raise ValueError("求解计算域名称与清单不一致")
        for name, region in regions.items():
            members = [z for z in manifest["zones"] if z["region"] == name]
            if sorted(region["zone_ids"]) != sorted(zones[z["name"]]["id"] for z in members):
                raise ValueError("网格区所属求解计算域错误：" + name)
            if any((z["kind"] == "solid") != region["is_solid"] for z in members):
                raise ValueError("流体/固体计算域类别错误：" + name)


def json_assertions(settings, assertions):
    """按 JSON Pointer 比较持久化设置；高级适配器可增加模型、接口、热源等约束。"""
    result = []
    for assertion in assertions:
        value = settings
        pointer = assertion["pointer"]
        for part in pointer.lstrip("/").split("/") if pointer else []:
            part = part.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]
        passed = value == assertion["equals"]
        result.append({"pointer": pointer, "actual": value, "expected": assertion["equals"], "passed": passed})
        if not passed:
            raise ValueError("QFlux 持久化参数不符合配置：" + pointer)
    return result


def add_monitor(command, model, name, patch, region_name, method, fields):
    """使用真实边界和计算域 ID 建立守恒/压降监测。"""
    from qfxPyApi.qxmod import monitor
    mon = monitor.txMonitorBase.Create(monitor.txMonitorType.Face)
    mon.name = name
    mon.regions = [model.regionMng[i].id for i in range(len(model.regionMng)) if model.regionMng[i].name == region_name]
    face = monitor.txMonitorFaceDefine()
    face.ids = [model.boundaryMng[i].id for i in range(len(model.boundaryMng)) if model.boundaryMng[i].name == patch]
    if len(face.ids) != 1:
        raise ValueError("监测边界未唯一匹配：" + patch)
    mon.faceDefinition = face
    mon.method = int(method)
    mon.precision = 10
    for variable in mon.variable:
        variable.state = int(variable.innerName in fields)
    command.ICmdAddMonitor(mon)
    KEEP.extend([mon, face])


def setup_basic(command, model, root, cfg, manifest):
    """基础单流体稳态等温设置；明确拒绝高级物理，避免产生看似完成的错误案例。"""
    from qfxPyApi.qxmod import boundary as bc, physics, material, region, monitor, solverset
    from qfxPyApi.qxmod.numerics import momentumDiscreteOption
    operating = cfg["physics"]
    regions = {z["region"] for z in manifest["zones"]}
    if len(regions) != 1 or any(z["kind"] != "fluid" for z in manifest["zones"]) or operating.get("energy") is not False or manifest.get("interfaces"):
        raise ValueError("setup-basic 仅支持无接口的单流体稳态等温；CHT/MRF 请编写物理适配器")
    if len(model.regionMng) != 1:
        raise ValueError("基础设置不自动合并已有计算域")
    region_name = next(iter(regions))
    command.ICmdSetRegionName(model.regionMng[0].id, region_name)
    command.ICmdSetRegionZone(region_name, [model.qxZoneMng[i].id for i in range(len(model.qxZoneMng))])
    command.ICmdSetTimeMode(region.txSolverPatternESTType.Steady)
    if operating["turbulence"] not in ["Laminar", "KW", "KE", "SA"]:
        raise ValueError("基础适配器不猜测其他湍流模型的子类型")
    turbulence = physics.CTurbulenceModel.Create(getattr(physics.CTurbulenceModelTurbulenceMethod, operating["turbulence"]))
    command.ICmdSetTurbulence(region_name, turbulence)
    command.ICmdSetEnergy(region_name, False)
    KEEP.append(turbulence)
    material_cfg = operating["material"]
    mat = material.material.Create(getattr(material.materialTypeEnum, material_cfg["kind"]))
    mat.name = material_cfg["name"]
    for key in ["Density", "Viscosity", "SpecialHeat", "ThermalConduct"]:
        prop = mat.getProperty(getattr(material.matPropertyBase, key))
        value = material.materialVariant()
        value.value = float(material_cfg[key])
        prop.method = 1
        prop.value = value
        KEEP.extend([prop, value])
    command.ICmdAddProjectMaterial(mat)
    command.ICmdSetRegionMaterial(region_name, mat.name)
    KEEP.append(mat)
    for zone in manifest["zones"]:
        for patch in zone["boundaries"]:
            role, name = patch["role"], patch["name"]
            if role == "velocity_inlet":
                condition = bc.CBCVeloInlet()
                p = condition.pri
                p.directionType = 1
                p.velocityMag = scalar(operating["inlet_speed_m_s"])
                t = p.turbulence
                t.method = 0
                t.intensity = scalar(operating["turbulence_intensity_percent"])
                t.ratio = scalar(operating["turbulence_viscosity_ratio"])
                p.turbulence = t
                condition.pri = p
                KEEP.extend([p, t])
            elif role == "pressure_outlet":
                condition = bc.CBCPressOutlet()
                p = condition.pri
                p.staticPressure = scalar(operating["outlet_gauge_pressure_Pa"])
                condition.pri = p
                KEEP.append(p)
            elif role in ["wall", "symmetry"]:
                condition = bc.CBCWall() if role == "wall" else bc.CBCSymmetricBoundary()
            else:
                raise ValueError("基础适配器不支持的边界：" + role)
            command.ICmdSetBoundaryCondition(name, condition)
            KEEP.append(condition)
            if role in ["velocity_inlet", "pressure_outlet"]:
                add_monitor(command, model, "mass_" + name, name, region_name, monitor.txMonitorFaceMethod.MassFlowRate, ["rho"])
                add_monitor(command, model, "pressure_" + name, name, region_name, monitor.txMonitorFaceMethod.AreaWeighted, ["p"])
    num = model.regionMng[0].numMethod
    scheme = num.discreteScheme
    spatial = scheme.discreteFormat
    momentum = spatial.momentum
    momentum.convection = int(getattr(momentumDiscreteOption.momentumTypeEnum, operating["momentum_scheme"]))
    spatial.momentum = momentum
    scheme.discreteFormat = spatial
    num.discreteScheme = scheme
    command.ICmdSetFluidNumMethod(region_name, num)
    KEEP.extend([num, scheme, spatial, momentum])
    for i in range(len(model.monitorMng)):
        mon = model.monitorMng[i]
        if isinstance(mon, monitor.txMonitorResidual):
            criterion = mon.criterion
            criterion.flag = True
            criterion.continuityOn = True
            criterion.momentumOn = True
            criterion.continuity = cfg["solver"]["residual_limit"]
            criterion.momentum = cfg["solver"]["residual_limit"]
            mon.criterion = criterion
            command.ICmdSetMonitorProperty(mon.name, mon)
            KEEP.extend([mon, criterion])
    parallel = solverset.txMPIParallel()
    parallel.flagMPI = cfg["solver"]["cores"] > 1
    parallel.numCoreMPI = cfg["solver"]["cores"]
    command.ICmdSetMPIParallel(parallel)
    iteration = model.solverSet.iteration
    iteration.iterations = cfg["solver"]["max_iterations"]
    iteration.autoSaveIteration = cfg["solver"]["save_interval"]
    iteration.folder = str(root / "runs")
    iteration.name = cfg["name"]
    command.ICmdSetIterationControl(iteration)
    KEEP.extend([parallel, iteration])


def main():
    """三个子命令均输出新目录，避免混淆旧检查记录和真实新工程。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup-basic", "inspect", "export"])
    parser.add_argument("--case", required=True)
    parser.add_argument("--input", help="inspect 的 QFX 或 CGNS 输入，默认配置中的 QFX")
    parser.add_argument("--mesh", action="store_true", help="inspect 仅验证 CGNS 几何网格，不证明物理设置")
    parser.add_argument("--data", help="inspect 可附加已完成 DAT，默认不读场")
    parser.add_argument("--stage", default="baseline")
    parser.add_argument("--output", help="新报告/导出目录，相对案例目录")
    args = parser.parse_args()
    root, cfg, env = context(args.case)
    manifest = read_json(inside(root, cfg["files"]["regions"]))
    mesh = read_json(inside(root, cfg["files"]["mesh_check"]))
    qfx = inside(root, cfg["files"]["qfx"])
    source = Path(args.input) if args.input else (inside(root, cfg["files"]["mesh_cgns"]) if args.mesh else qfx)
    source = (source if source.is_absolute() else root / source).resolve()
    if args.mesh and args.action != "inspect":
        raise ValueError("--mesh 仅适用于 inspect")
    if args.mesh and args.data:
        raise ValueError("网格检查不能同时加载结果场")
    if args.action == "setup-basic" and qfx.exists():
        raise FileExistsError(qfx)
    out = exclusive_directory(inside(root, args.output or ("checks/setup" if args.action == "setup-basic" else "checks/readback" if args.action == "inspect" else "post/" + args.stage)))
    command, get_model = bootstrap(env)
    if args.action == "setup-basic":
        cgns = inside(root, cfg["files"]["mesh_cgns"])
        if sha256(cgns) != mesh["cgns_sha256"]:
            raise ValueError("CGNS 已变更，检查报告失效")
        command.ICmdImportMesh([str(cgns)])
        model = get_model()
        setup_basic(command, model, root, cfg, manifest)
        save = command.ICmdSaveCaseParameter()
        save.caseFile = str(qfx)
        save.fileType = 1
        save.persistence = command.ESaveCasePersistence.ProjectFile
        command.ICmdSaveCase(save)
        source = qfx
        KEEP.append(save)
    elif args.mesh:
        if sha256(source) != mesh["cgns_sha256"]:
            raise ValueError("CGNS 与网格检查来源不一致")
        command.ICmdImportMesh([str(source)])
    else:
        op = command.ICmdOpenCaseParameter()
        op.caseFile = str(source)
        op.onlyLoadCase = False
        command.ICmdOpenCase(op)
        KEEP.append(op)
    data = (Path(args.data) if Path(args.data).is_absolute() else root / args.data).resolve() if args.data else None
    if args.action == "export":
        stage = inside(root, "runs/" + args.stage)
        finished = read_json(stage / "finished.json")
        if finished.get("exit_code") != 0 or not finished.get("final_data"):
            raise ValueError("阶段未正常完成或没有完整结果场")
        if sha256(qfx) != finished["qfx_sha256"]:
            raise ValueError("QFX 与本次求解来源不一致")
        data = inside(root, finished["final_data"])
        if sha256(data) != finished["final_data_sha256"]:
            raise ValueError("DAT 与完成记录不一致")
    if data:
        if not data.is_file() or data.stat().st_size == 0:
            raise ValueError("DAT 不存在或为空")
        op = command.ICmdOpenDataParameter()
        op.dataFile = str(data)
        command.ICmdOpenData(op)
        KEEP.append(op)
    model = get_model()
    report = collect(model)
    validate(report, mesh, manifest, cfg, check_conditions=not args.mesh)
    command.ICmdExportCaseJson(str(out / "settings.json"))
    settings = read_json(out / "settings.json")
    assertions = [] if args.mesh else json_assertions(settings, cfg.get("qflux_assertions", []))
    report.update({"passed": True, "source": str(source), "source_sha256": sha256(source), "source_data": str(data) if data else None,
                   "source_data_sha256": sha256(data) if data else None, "independent_readback": args.action != "setup-basic",
                   "mesh_only": bool(args.mesh), "assertions": assertions, "explicit_interface_groups": len(settings.get("interfaceGroup", [])),
                   "motion_count": sum(len(r.get("motion", [])) for r in settings.get("region", [])),
                   "scope": "名称/类型/归属/网格尺寸与显式参数断言；接口守恒和物理精度另行验收"})
    if args.action == "export":
        available = [{"id": model.scalarMng[i].id, "field": model.scalarMng[i].fieldName, "name": model.scalarMng[i].name} for i in range(len(model.scalarMng))]
        zone_fields = cfg["post"].get("zone_fields", {})
        if zone_fields and set(zone_fields) != set(cfg["post"]["zones"]):
            raise ValueError("zone_fields 必须完整覆盖所选网格区")
        wanted = {field for names in zone_fields.values() for field in names} if zone_fields else set(cfg["post"]["fields"])
        selected = [s for s in available if s["field"] in wanted]
        write_json(out / "available_fields.json", available)
        if {s["field"] for s in selected} != wanted or not wanted:
            raise ValueError("所需场变量缺失；检查本目录 available_fields.json 和当前版本有效物理场")
        available_zones = {z["name"] for z in report["zones"]}
        if not cfg["post"]["zones"] or not set(cfg["post"]["zones"]) <= available_zones:
            raise ValueError("导出区缺失或未指定")
        parameter = command.ICmdExportFileParameter()
        parameter.FileType = command.fileTypeEnum.vtk_xml
        parameter.FilePath = str(out / "fields.vtu")
        parameter.Zones = cfg["post"]["zones"]
        parameter.ScalarIDs = [s["id"] for s in selected]
        parameter.ScalarDataMethod = 3
        command.ICmdExportFile(parameter)
        KEEP.append(parameter)
        files = sorted(out.rglob("*.vtu"))
        if not files or any(f.stat().st_size == 0 for f in files):
            raise ValueError("官方导出未生成有效 VTU")
        if len(files) != len(cfg["post"]["zones"]) or {f.stem for f in files} != set(cfg["post"]["zones"]):
            raise ValueError("实际 VTU 与所选区不一一对应，请适配该版本导出结构")
        actual_arrays = {}
        for file in files:
            tree = ET.parse(file)
            names = {a.get("Name") for parent in ["PointData", "CellData"] for a in tree.findall(".//" + parent + "/DataArray")}
            effective = set(zone_fields.get(file.stem, cfg["post"]["fields"]))
            if not effective:
                raise ValueError("每个导出区需指定有效场变量")
            missing = [s["field"] for s in selected if s["field"] in effective and s["name"] not in names and s["field"] not in names]
            if missing:
                raise ValueError("VTU 实际缺少请求场（常物性字段也可能不导出）：" + repr(missing))
            actual_arrays[str(file.relative_to(root))] = sorted(names)
        report.update({"selected_fields": selected, "available_fields": available,
                       "actual_vtu_arrays": actual_arrays,
                       "exported_vtu": [{"path": str(f.relative_to(root)), "sha256": sha256(f)} for f in files]})
    write_json(out / "check.json", report)
    print("QFLUX_" + args.action.upper() + "_COMPLETE", str(out), flush=True)


if __name__ == "__main__":
    try:
        main()
        sys.stdout.flush()
        sys.stderr.flush()
        # 部分 Windows 原生绑定退出析构异常；只在保存/导出全部验证后采用立即退出。
        os._exit(0)
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)

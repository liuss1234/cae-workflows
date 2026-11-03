# -*- coding: utf-8 -*-
"""在独立 QFlux 进程导入或回读工程，按外部清单核对全部网格区和边界。"""

# 可调默认参数。QFlux 13.77.1 的 qfxPyApi.pyd 需配套 Python 3.8 x64。
from pathlib import Path
import os
DEFAULT_QFLUX_DIRECTORY = os.environ.get("QFLUX_HOME") or None
COORDINATE_TOLERANCE_M = 1.0e-9
DEFAULT_REGION_NAME = "fluid"

import argparse
import json
import sys
import traceback


def collect(model):
    """仅查询管理器实际对象，记录名称、归属、尺寸及边界单元数。"""
    report = {"regions": [], "zones": [], "boundaries": []}
    for index in range(len(model.regionMng)):
        region = model.regionMng[index]
        report["regions"].append({"id": region.id, "name": region.name, "zone_ids": list(region.zoneIds)})
    for index in range(len(model.qxZoneMng)):
        zone = model.qxZoneMng[index]
        surfaces = [{"name": zone.surface(i).name, "faces": zone.surface(i).count}
                    for i in range(zone.surfaceCount)]
        report["zones"].append({"id": zone.id, "name": zone.name, "cells": zone.cellCount,
                                "nodes": zone.pointCount, "bbox": list(zone.aabb), "surfaces": surfaces})
    for index in range(len(model.boundaryMng)):
        boundary = model.boundaryMng[index]
        report["boundaries"].append({"id": boundary.id, "name": boundary.name, "zone_id": boundary.zoneId,
                                     "condition_class": type(boundary.bCondition).__name__,
                                     "condition_type": boundary.bCondition.typeName})
    return report


def validate(report, expected):
    """比较导出清单与 QFlux 实读数据；名称集合、面数、单元数和米制尺寸都要一致。"""
    if expected.get("units") != "m":
        raise ValueError("期望清单须明确 units=m；本工具不猜测输入单位")
    zones = {zone["name"]: zone for zone in report["zones"]}
    reference = expected["regions"]
    if len(zones) != len(report["zones"]) or set(zones) != set(reference):
        raise RuntimeError("网格区名称缺失、重复或多余")
    expected_names = []
    for name, source in reference.items():
        zone = zones[name]
        if zone["cells"] != source["cells"] or zone["nodes"] != source["nodes"]:
            raise RuntimeError("单元数或节点数改变：" + name)
        actual_patches = {side["name"]: side["faces"] for side in zone["surfaces"]}
        if len(actual_patches) != len(zone["surfaces"]) or actual_patches != source["boundaries"]:
            raise RuntimeError("边界名称或面数改变：" + name)
        minimum, maximum = source["bbox_m"]
        target = [value for pair in zip(minimum, maximum) for value in pair]
        if max(abs(a-b) for a, b in zip(zone["bbox"], target)) > COORDINATE_TOLERANCE_M:
            raise RuntimeError("米制包围盒不一致：" + name)
        expected_names.extend(source["boundaries"])
    actual_names = [boundary["name"] for boundary in report["boundaries"]]
    if len(set(expected_names)) != len(expected_names):
        raise ValueError("期望清单中的边界名称跨区重复，不能唯一设置边界")
    if sorted(actual_names) != sorted(expected_names):
        raise RuntimeError("QFlux 边界管理器的名称集合与清单不一致")
    # 核对边界属于哪个网格区，避免同名边界关联到错误零件。
    for boundary in report["boundaries"]:
        zone = next(zone for zone in zones.values() if zone["id"] == boundary["zone_id"])
        if boundary["name"] not in reference[zone["name"]]["boundaries"]:
            raise RuntimeError("边界归属错误：" + boundary["name"])
    report["validation"] = {"passed": True, "units": "m", "zone_count": len(zones),
                             "boundary_count": len(actual_names),
                             "tetrahedra": sum(zone["cells"] for zone in zones.values())}


def main():
    """按需保存新工程；不会连接已打开的 GUI 会话，也不会启动求解。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--expected", type=Path, required=True, help="si_export_check.json 或相同结构的期望清单")
    parser.add_argument("--output-dir", type=Path, required=True, help="必须是新的报告目录")
    parser.add_argument("--qflux-directory", type=Path, default=DEFAULT_QFLUX_DIRECTORY,
                        help="QFlux 安装目录；也可设置当前进程的 QFLUX_HOME")
    parser.add_argument("--open-case", action="store_true", help="回读 .qfx，默认导入网格")
    parser.add_argument("--save-project", action="store_true", help="在报告目录保存 project.qfx，统一一个流体计算域")
    parser.add_argument("--region-name", default=DEFAULT_REGION_NAME)
    args = parser.parse_args()
    if args.qflux_directory is None or not args.qflux_directory.is_dir():
        raise ValueError("请用 --qflux-directory 或 QFLUX_HOME 指定有效的 QFlux 安装目录")
    if os.name != "nt":
        raise RuntimeError("该 QFlux API 适配器仅验证 Windows；Linux 需按其本机 API 重新适配")
    if args.open_case and args.save_project:
        raise ValueError("回读检查不同时改写工程；请分别执行")
    expected = json.loads(args.expected.read_text(encoding="utf-8-sig"))
    if not args.input.is_file():
        raise FileNotFoundError(args.input)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    dll_directory = str(args.qflux_directory.resolve())
    sys.path.insert(0, dll_directory)
    dll_cookie = os.add_dll_directory(dll_directory)
    os.environ["PATH"] = dll_directory + os.pathsep + os.environ.get("PATH", "")
    from qfxPyApi import qxapp, qxcmd
    from qfxPyApi.qxmod.runtime import getActiveModel
    qxapp.initialize()
    try:
        if args.open_case:
            parameter = qxcmd.ICmdOpenCaseParameter()
            parameter.caseFile = str(args.input.resolve())
            parameter.onlyLoadCase = True
            qxcmd.ICmdOpenCase(parameter)
        else:
            qxcmd.ICmdImportMesh([str(args.input.resolve())])
        model = getActiveModel()
        report = collect(model)
        validate(report, expected)
        if args.save_project:
            if len(model.regionMng) != 1:
                raise RuntimeError("此保存模式只整理已归属一个求解计算域的流体网格，不自动合并多物理计算域")
            from qfxPyApi.qxmod.boundary import CBCWall, CBCInterfaceBoundary
            qxcmd.ICmdSetRegionName(model.regionMng[0].id, args.region_name)
            qxcmd.ICmdSetRegionZone(args.region_name, [zone["id"] for zone in report["zones"]])
            for boundary in report["boundaries"]:
                name = boundary["name"]
                if name.startswith("wall_"):
                    qxcmd.ICmdSetBoundaryCondition(name, CBCWall())
                elif name.startswith("interface_"):
                    condition = CBCInterfaceBoundary()
                    properties = condition.pri
                    properties.mergeable = False
                    condition.pri = properties
                    qxcmd.ICmdSetBoundaryCondition(name, condition)
            report = collect(model)
            validate(report, expected)
            for boundary in report["boundaries"]:
                target = "CBCWall" if boundary["name"].startswith("wall_") else "CBCInterfaceBoundary" if boundary["name"].startswith("interface_") else None
                if target and boundary["condition_class"] != target:
                    raise RuntimeError("显式设置边界类别未生效：" + boundary["name"])
            save = qxcmd.ICmdSaveCaseParameter()
            save.caseFile = str((args.output_dir / "project.qfx").resolve())
            save.fileType = 1
            save.persistence = qxcmd.ESaveCasePersistence.ProjectFile
            qxcmd.ICmdSaveCase(save)
        settings_path = args.output_dir / "settings.json"
        qxcmd.ICmdExportCaseJson(str(settings_path.resolve()))
        settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        report.update(input=str(args.input.resolve()), expected=str(args.expected.resolve()))
        report["explicit_interface_group_count"] = len(settings.get("interfaceGroup", []))
        report["motion_count"] = sum(len(region.get("motion", [])) for region in settings.get("region", []))
        report["solver_coupling_verified"] = False
        report["note"] = "本检查验证名称、几何、单元数及实际边界类别；不证明接口守恒或旋转运动已就绪。"
        (args.output_dir / "check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report["validation"], ensure_ascii=False), flush=True)
    except Exception:
        (args.output_dir / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    # dll_cookie 在所有 QFlux API 调用结束前保持存活，不提前卸载依赖。


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)

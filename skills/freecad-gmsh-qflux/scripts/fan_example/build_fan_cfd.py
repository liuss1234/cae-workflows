# -*- coding: utf-8 -*-
"""用 FreeCAD/OCC 为当前轴流风扇生成 CFD 几何、流体域和旋转区域。

依赖：FreeCAD 1.1 自带 FreeCAD、Part、Import；无需 Blender 或额外 Python 包。
输入：当前 FreeCAD 文档的独立快照 source_current.FCStd。
输出：新的 CFD 文档、三域 STEP、清理后固体、边界面及几何核验报告。
运行：freecadcmd.exe -c "exec(compile(open(r'本脚本路径','rb').read(),r'本脚本路径','exec'))"
"""
# 本文件为七叶风扇参考实现；其他 CAD 必须重新映射零件与边界，不能直接套用。


from pathlib import Path
import os
import datetime
import itertools
import json
import math
import time
import traceback

import FreeCAD as App
import Part
import Import


# ======================== 可调参数：长度单位 mm ========================
WORK_DIRECTORY = Path(os.environ["CFD_WORK_DIRECTORY"]).resolve()  # 由运行器指定独立项目目录
SOURCE_FILE = WORK_DIRECTORY / "source_current.FCStd"
BASE_OUTPUT_DIRECTORY = WORK_DIRECTORY / "prepared"
INLET_EXTENSION_DIAMETERS = 2.0
OUTLET_EXTENSION_DIAMETERS = 5.0
ROTOR_FRONT_CLEARANCE_MM = 2.0
MIN_INTERFACE_CLEARANCE_MM = 0.25
LINEAR_TOLERANCE_MM = 1.0e-5
VOLUME_ABS_TOLERANCE_MM3 = 1.0e-4
VOLUME_REL_TOLERANCE = 1.0e-8
AREA_REL_TOLERANCE = 1.0e-7
PREVIEW_HALF_LENGTH_MM = 55.0
FLOW_DIRECTION = (0.0, 0.0, -1.0)
ROTATION_AXIS = (0.0, 0.0, 1.0)
# 转速不影响几何抽取，保留为空，交给后续工况设置。
ROTATION_RPM = None


def box_values(shape):
    """返回形状包围盒；不以显示三角网格作为布尔运算输入。"""
    box = shape.BoundBox
    return [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax]


def volume(shape):
    """空形状的体积按零处理。"""
    return 0.0 if shape.isNull() else abs(shape.Volume)


def refine(shape):
    """只在有界、小型形状上移除布尔运算后的共面冗余边。"""
    if shape.isNull():
        raise RuntimeError("布尔运算得到空形状")
    result = shape.removeSplitter()
    if result.isNull() or not result.isValid():
        raise RuntimeError("几何精化后形状无效")
    return result


def united(shapes):
    """合并同一物理部件的实体，删除内部重叠面。"""
    result = shapes[0].copy()
    if len(shapes) > 1:
        result = result.multiFuse(shapes[1:])
    return refine(result)


def shape_record(shape, expected_solids=None):
    """检查有效性、封闭壳体、实体个数和正体积。"""
    record = {
        "valid": shape.isValid(), "closed": shape.isClosed(),
        "solids": len(shape.Solids), "shells": len(shape.Shells),
        "faces": len(shape.Faces), "edges": len(shape.Edges),
        "volume_mm3": volume(shape), "area_mm2": shape.Area,
        "bbox_mm": box_values(shape),
        "all_shells_closed": all(shell.isClosed() for shell in shape.Shells),
    }
    if not (record["valid"] and record["closed"] and record["all_shells_closed"] and record["volume_mm3"] > 0):
        raise RuntimeError("形状不是有效封闭实体：" + json.dumps(record))
    if expected_solids is not None and record["solids"] != expected_solids:
        raise RuntimeError("意外的断开区域数量：" + json.dumps(record))
    return record


def make_cylinder(radius, lower, upper):
    """沿全局 Z 轴创建圆柱域。"""
    if upper <= lower:
        raise ValueError("圆柱域上界必须高于下界")
    return Part.makeCylinder(radius, upper-lower, App.Vector(0,0,lower))


def tight_z_extents(shape):
    """通过到包围平面的精确距离求 Z 极值，避免 B 样条保守包围盒引入薄层。"""
    box = shape.BoundBox
    margin = 10.0
    lower_plane_z, upper_plane_z = box.ZMin-margin, box.ZMax+margin
    lower = Part.makePlane(box.XLength+2*margin, box.YLength+2*margin, App.Vector(box.XMin-margin,box.YMin-margin,lower_plane_z))
    upper = Part.makePlane(box.XLength+2*margin, box.YLength+2*margin, App.Vector(box.XMin-margin,box.YMin-margin,upper_plane_z))
    return lower_plane_z+shape.distToShape(lower)[0], upper_plane_z-shape.distToShape(upper)[0]


def planar_at(face, z_value):
    """以平面包围盒判断端面，容忍 OCC 数值公差。"""
    box = face.BoundBox
    return abs(box.ZMin-z_value) <= LINEAR_TOLERANCE_MM and abs(box.ZMax-z_value) <= LINEAR_TOLERANCE_MM


def is_duct_face(face, radius):
    """识别与全局 Z 轴同轴的圆管壁。"""
    surface = face.Surface
    if not isinstance(surface, Part.Cylinder):
        return False
    return abs(surface.Radius-radius) <= LINEAR_TOLERANCE_MM and abs(abs(surface.Axis.z)-1.0) <= 1.0e-8


def main():
    """依次执行源模型检查、清理、抽域、区域分割、命名与导出。"""
    started = time.perf_counter()
    output = BASE_OUTPUT_DIRECTORY
    if (output / "fan_cfd.FCStd").exists():
        output = WORK_DIRECTORY / ("prepared_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    output.mkdir(parents=True, exist_ok=True)

    def progress(number, message):
        """及时保存进度，遇到 OCC 错误时也能定位到具体阶段。"""
        print("CFD %d/8 %s" % (number, message), flush=True)
        (output / "progress.json").write_text(json.dumps({"step": number, "message": message, "elapsed_seconds": time.perf_counter()-started}, ensure_ascii=False), encoding="utf-8")

    source = result = None
    try:
        progress(1, "读取当前模型快照")
        source = App.openDocument(str(SOURCE_FILE))
        required = ["FrameFinal", "Hub", "HubCap", "MotorHousing", "BladeMaster", "BoreTool"]
        if any(source.getObject(name) is None for name in required):
            raise RuntimeError("源模型缺少预期的风扇零件")
        blades = [source.getObject("BladeMaster")] + sorted([obj for obj in source.Objects if obj.Name.startswith("BladeLink")], key=lambda obj: obj.Name)
        supports = sorted([obj for obj in source.Objects if obj.Name.startswith("SupportArm")], key=lambda obj: obj.Name)
        if len(blades) != 7 or len(supports) != 4:
            raise RuntimeError("源模型叶片/支撑数量发生变化，请先核对当前装配")
        frame_original = source.getObject("FrameFinal").Shape.copy()
        rotor_sources = [source.getObject("Hub").Shape.copy(), source.getObject("HubCap").Shape.copy()] + [obj.Shape.copy() for obj in blades]
        motor_original = source.getObject("MotorHousing").Shape.copy()
        support_shapes = [obj.Shape.copy() for obj in supports]
        for shape in [frame_original, motor_original] + rotor_sources + support_shapes:
            shape_record(shape, 1)
        bore_radius = float(source.getObject("BoreTool").Radius.Value)
        duct_diameter = 2*bore_radius
        frame_box = frame_original.BoundBox
        if abs(frame_box.XMin+frame_box.XMax) > LINEAR_TOLERANCE_MM or abs(frame_box.YMin+frame_box.YMax) > LINEAR_TOLERANCE_MM:
            raise RuntimeError("源机框不再位于全局 Z 轴中心，不能沿用当前域设置")

        progress(2, "封安装孔、去机框外角、合并转子并消除内部重叠")
        # 精确保留接触流体的圆形风道；将不接触流体的外框简化为方形。
        frame_blank = Part.makeBox(frame_box.XLength, frame_box.YLength, frame_box.ZLength, App.Vector(frame_box.XMin, frame_box.YMin, frame_box.ZMin))
        frame_clean = refine(frame_blank.cut(make_cylinder(bore_radius, frame_box.ZMin-1, frame_box.ZMax+1)))
        rotor = united(rotor_sources)
        stator_before_trim = united([frame_clean, motor_original] + support_shapes)
        rotor_stator_overlap = volume(rotor.common(stator_before_trim))
        stator = refine(stator_before_trim.cut(rotor))
        all_solids = united([rotor, stator])
        original_union = united([frame_original, motor_original] + support_shapes + rotor_sources)
        rotor_info = shape_record(rotor, 1)
        stator_info = shape_record(stator, 1)

        progress(3, "建立圆管域和旋转区包络")
        rotor_actual_lower, rotor_actual_upper = tight_z_extents(rotor)
        supports_top = max(tight_z_extents(shape)[1] for shape in support_shapes)
        if rotor_actual_lower-supports_top < 2*MIN_INTERFACE_CLEARANCE_MM:
            raise RuntimeError("旋转零件与后支撑之间没有可放置接口的轴向间隙")
        rotor_lower = (supports_top+rotor_actual_lower)/2
        rotor_upper = rotor_actual_upper+ROTOR_FRONT_CLEARANCE_MM
        model_front = max(frame_box.ZMax, rotor_actual_upper)
        model_back = min(frame_box.ZMin, motor_original.BoundBox.ZMin)
        inlet_z = model_front+INLET_EXTENSION_DIAMETERS*duct_diameter
        outlet_z = model_back-OUTLET_EXTENSION_DIAMETERS*duct_diameter
        duct = make_cylinder(bore_radius, outlet_z, inlet_z)
        rotor_envelope = make_cylinder(bore_radius, rotor_lower, rotor_upper)
        inlet_envelope = make_cylinder(bore_radius, rotor_upper, inlet_z)
        outlet_envelope = make_cylinder(bore_radius, outlet_z, rotor_lower)
        duct_wall_face = next(face for face in duct.Faces if is_duct_face(face, bore_radius))
        tip_distance, tip_points, _ = united([obj.Shape.copy() for obj in blades]).distToShape(duct_wall_face)
        if tip_distance <= LINEAR_TOLERANCE_MM:
            raise RuntimeError("叶片碰到圆管壁，没有正的叶尖间隙")

        progress(4, "从完整圆管扣除固体，抽取三个流体区域")
        fluid_total = refine(duct.cut(all_solids))
        fluids = {
            "fluid_stationary_inlet": refine(fluid_total.common(inlet_envelope)),
            "fluid_rotating": refine(fluid_total.common(rotor_envelope)),
            "fluid_stationary_outlet": refine(fluid_total.common(outlet_envelope)),
        }
        fluid_info = {name: shape_record(shape, 1) for name, shape in fluids.items()}
        shape_record(fluid_total, 1)

        progress(5, "核验封闭性、无重叠与体积守恒")
        volume_tolerance = max(VOLUME_ABS_TOLERANCE_MM3, fluid_total.Volume*VOLUME_REL_TOLERANCE)
        overlaps = {}
        for left, right in itertools.combinations(fluids, 2):
            overlaps[left+"__"+right] = volume(fluids[left].common(fluids[right]))
        sum_volume = sum(shape.Volume for shape in fluids.values())
        closure_error = abs(sum_volume-fluid_total.Volume)
        fluid_union = united(list(fluids.values()))
        uncovered_volume = volume(fluid_total.cut(fluid_union))
        extra_volume = volume(fluid_union.cut(fluid_total))
        changed_wetted_volume = volume(original_union.common(duct).cut(all_solids.common(duct))) + volume(all_solids.common(duct).cut(original_union.common(duct)))
        post_cleanup_solid_overlap = volume(rotor.common(stator))
        if max(list(overlaps.values())+[closure_error, uncovered_volume, extra_volume, changed_wetted_volume, post_cleanup_solid_overlap]) > volume_tolerance:
            raise RuntimeError("流体分区存在重叠、遗漏或意外改变流道：" + str([overlaps, closure_error, uncovered_volume, extra_volume, changed_wetted_volume]))
        # 对输出区域执行 OCC 的额外布尔运算检查。
        for shape in fluids.values():
            shape.check(True)

        progress(6, "识别入口、出口、静止壁、转动壁和配对接口")
        patches = {}
        face_map = {}
        def assign(name, region_name, face_index, face):
            patches.setdefault(name, []).append(face)
            face_map.setdefault(name, {"region": region_name, "faces": [], "area_mm2": 0.0})
            face_map[name]["faces"].append("Face%d" % face_index)
            face_map[name]["area_mm2"] += face.Area

        for region_name, shape in fluids.items():
            for face_index, face in enumerate(shape.Faces, 1):
                patch = None
                if planar_at(face, inlet_z):
                    patch = "inlet"
                elif planar_at(face, outlet_z):
                    patch = "outlet"
                elif planar_at(face, rotor_upper):
                    patch = "interface_inlet_rotating" if region_name == "fluid_rotating" else "interface_inlet_stationary"
                elif planar_at(face, rotor_lower):
                    patch = "interface_outlet_rotating" if region_name == "fluid_rotating" else "interface_outlet_stationary"
                elif is_duct_face(face, bore_radius):
                    patch = "wall_duct_" + region_name.replace("fluid_", "")
                else:
                    rotor_contact = face.common(rotor).Area
                    stator_contact = face.common(stator).Area
                    threshold = face.Area*(1-AREA_REL_TOLERANCE)
                    if rotor_contact >= threshold:
                        patch = "wall_rotor_" + region_name.replace("fluid_", "")
                    elif stator_contact >= threshold:
                        patch = "wall_stator_" + region_name.replace("fluid_", "")
                    else:
                        raise RuntimeError("无法归类的边界面：%s Face%d，面积 %.9g，转子/定子接触 %.9g / %.9g" % (region_name, face_index, face.Area, rotor_contact, stator_contact))
                assign(patch, region_name, face_index, face)

        interface_checks = []
        for side in ("inlet", "outlet"):
            rotating_name = "interface_"+side+"_rotating"
            stationary_name = "interface_"+side+"_stationary"
            left = Part.makeCompound(patches[rotating_name])
            right = Part.makeCompound(patches[stationary_name])
            common_area = left.common(right).Area
            area_error = max(abs(left.Area-right.Area), abs(left.Area-common_area))
            left_normal = patches[rotating_name][0].normalAt(0,0)
            right_normal = patches[stationary_name][0].normalAt(0,0)
            normal_dot = left_normal.dot(right_normal)
            if area_error > left.Area*AREA_REL_TOLERANCE or normal_dot > -0.999999:
                raise RuntimeError("接口面不匹配或法向不相反：" + side)
            interface_checks.append({"rotating_patch": rotating_name, "stationary_patch": stationary_name, "area_mm2": left.Area, "matched_area_mm2": common_area, "area_error_mm2": area_error, "outward_normal_dot": normal_dot, "z_mm": rotor_upper if side == "inlet" else rotor_lower})
        total_mapped_area = sum(item["area_mm2"] for item in face_map.values())
        total_region_area = sum(shape.Area for shape in fluids.values())
        if abs(total_mapped_area-total_region_area) > total_region_area*AREA_REL_TOLERANCE:
            raise RuntimeError("边界面未完整覆盖所有流体区域")

        progress(7, "创建可审查的 FreeCAD 文档和 STEP 文件")
        result = App.newDocument("Fan_CFD_Prepared")
        result.Label = "风扇 CFD · 清理 / 流体域 / 旋转区"
        def group(name, label):
            obj = result.addObject("App::DocumentObjectGroup", name)
            obj.Label = label
            return obj
        solid_group = group("CleanSolids", "01 CFD 简化固体")
        fluid_group = group("FluidRegions", "02 三个流体区域（用于网格）")
        boundary_group = group("BoundaryPatches", "03 边界命名与接口配对")
        reference_group = group("ReferenceVolumes", "04 参考包络（不要作为流体重复导入）")
        preview_group = group("PreviewOnly", "05 局部剖切预览（不参与网格）")
        def feature(name, shape, parent):
            obj = result.addObject("Part::Feature", name)
            obj.Label = name
            obj.Shape = shape
            parent.addObject(obj)
            return obj
        solid_objects = [feature("solid_rotor", rotor, solid_group), feature("solid_stator", stator, solid_group)]
        fluid_objects = [feature(name, shape, fluid_group) for name, shape in fluids.items()]
        boundary_objects = []
        for name, faces in patches.items():
            obj = feature(name, Part.makeCompound(faces), boundary_group)
            obj.addProperty("App::PropertyString", "AdjacentRegion", "CFD")
            obj.AdjacentRegion = face_map[name]["region"]
            obj.addProperty("App::PropertyStringList", "RegionFaces", "CFD")
            obj.RegionFaces = face_map[name]["faces"]
            boundary_objects.append(obj)
        envelope_object = feature("rotor_envelope", rotor_envelope, reference_group)
        envelope_object.addProperty("App::PropertyString", "Purpose", "CFD")
        envelope_object.Purpose = "旋转区域的圆柱参考包络；实际流体为 fluid_rotating。"
        feature("duct_envelope", duct, reference_group)
        # 预览只保留后半圆和风扇附近，使旋转域与叶片同时可见。
        clip = Part.makeBox(2*bore_radius+2, bore_radius+1, 2*PREVIEW_HALF_LENGTH_MM, App.Vector(-bore_radius-1,0,-PREVIEW_HALF_LENGTH_MM))
        preview_objects = []
        for name, shape in fluids.items():
            preview = feature("preview_"+name, refine(shape.common(clip)), preview_group)
            preview.addProperty("App::PropertyString", "Purpose", "CFD")
            preview.Purpose = "仅用于近场剖切显示，不代表完整流体域。"
            preview_objects.append(preview)
        preview_stator = feature("preview_stator_cutaway", refine(stator.common(clip)), preview_group)
        preview_stator.addProperty("App::PropertyString", "Purpose", "CFD")
        preview_stator.Purpose = "静止固体半剖视图，仅显示。"
        parameters = result.addObject("App::FeaturePython", "CFDParameters")
        parameters.Label = "00 域参数与假设"
        for name, value in (("DuctDiameter",duct_diameter),("InletZ",inlet_z),("OutletZ",outlet_z),("RotorZMin",rotor_lower),("RotorZMax",rotor_upper),("TipClearance",tip_distance)):
            parameters.addProperty("App::PropertyLength", name, "CFD")
            setattr(parameters, name, value)
            parameters.setEditorMode(name, 1)
        parameters.addProperty("App::PropertyString", "FlowDirection", "CFD")
        parameters.FlowDirection = "入口 +Z，出口 -Z；流向 (0,0,-1)"
        parameters.addProperty("App::PropertyString", "RotationAxis", "CFD")
        parameters.RotationAxis = "原点 (0,0,0)；轴向 (0,0,1)；转速与正负转向待设"
        result.recompute()
        fcstd = output / "fan_cfd.FCStd"
        result.saveAs(str(fcstd))
        Import.export(fluid_objects, str(output / "fluid_regions.step"))
        for obj in fluid_objects:
            Import.export([obj], str(output / (obj.Name+".step")))
        Import.export(solid_objects, str(output / "cleaned_solids.step"))
        Import.export(boundary_objects, str(output / "boundary_patches.step"))
        Import.export([envelope_object], str(output / "rotor_envelope.step"))

        progress(8, "保存量化核验与边界说明")
        report = {
            "source_snapshot": str(SOURCE_FILE), "output_directory": str(output),
            "units": "mm; volumes mm^3; areas mm^2", "flow_direction": FLOW_DIRECTION,
            "rotation_axis": ROTATION_AXIS, "rotation_origin_mm": [0,0,0], "rotation_rpm": ROTATION_RPM,
            "domain": {"diameter_mm": duct_diameter, "inlet_z_mm": inlet_z, "outlet_z_mm": outlet_z, "inlet_extension_D": INLET_EXTENSION_DIAMETERS, "outlet_extension_D": OUTLET_EXTENSION_DIAMETERS, "rotor_z_min_mm": rotor_lower, "rotor_z_max_mm": rotor_upper, "rotor_envelope_diameter_mm": duct_diameter, "rotor_actual_z_min_mm": rotor_actual_lower, "rotor_actual_z_max_mm": rotor_actual_upper, "outlet_interface_to_support_mm": rotor_lower-supports_top, "outlet_interface_to_rotor_mm": rotor_actual_lower-rotor_lower},
            "cleanup": {"mounting_holes_removed": 4, "external_corner_rounds_removed": 4, "rotor_source_solids": len(rotor_sources), "rotor_output_solids": len(rotor.Solids), "stator_source_solids": 2+len(supports), "stator_output_solids": len(stator.Solids), "rotor_root_internal_overlap_removed_mm3": sum(s.Volume for s in rotor_sources)-rotor.Volume, "rotor_stator_overlap_removed_mm3": rotor_stator_overlap, "solid_overlap_after_mm3": post_cleanup_solid_overlap, "frame_volume_added_outside_flow_mm3": frame_clean.Volume-frame_original.Volume, "fluid_obstruction_symmetric_difference_mm3": changed_wetted_volume, "tip_clearance_mm": tip_distance, "tip_clearance_closest_points_mm": [[[p.x,p.y,p.z] for p in pair] for pair in tip_points], "preserved": ["七片扭转叶片及真实厚度", "轮毂和前锥罩", "电机外露表面及后支撑", "叶尖间隙与轴向流道"]},
            "solid_rotor": rotor_info, "solid_stator": stator_info,
            "fluid_regions": fluid_info, "fluid_total_volume_mm3": fluid_total.Volume,
            "verification": {"volume_tolerance_mm3": volume_tolerance, "pairwise_overlap_mm3": overlaps, "volume_sum_error_mm3": closure_error, "uncovered_fluid_mm3": uncovered_volume, "extra_fluid_mm3": extra_volume, "all_fluid_regions_valid_closed_single_solids": True, "occ_bop_check_passed": True, "assigned_faces": sum(len(x["faces"]) for x in face_map.values()), "total_faces": sum(len(s.Faces) for s in fluids.values()), "boundary_area_error_mm2": abs(total_mapped_area-total_region_area)},
            "interfaces": interface_checks, "boundary_patches": face_map,
            "files": {"fcstd": str(fcstd), "fluid_regions_step": str(output / "fluid_regions.step"), "cleaned_solids_step": str(output / "cleaned_solids.step"), "boundary_patches_step": str(output / "boundary_patches.step"), "rotor_envelope_step": str(output / "rotor_envelope.step")},
            "notes": [
                "采用圆管内流模型；延长段长度是初始几何假设，需要后续检查边界距离敏感性。",
                "旋转区延伸至圆管内壁，避免人为制造狭窄静止环隙；该区圆管壁必须设置为绝对静止壁。",
                "电机壳有少量同轴表面位于旋转流体区；wall_stator_rotating 必须设置绝对静止，不能随转子旋转。",
                "接口为几何重合的两侧独立面；导入网格器后需共享拓扑，或配置非共形配对接口。",
                "Face 编号对应本 FCStd 文件；STEP 导入器可能重排编号，请结合 boundary_patches.step 的命名面核对。",
                "仅完成几何准备与 CAD 检查；尚未生成体网格，也未设置转速、流量、湍流模型或求解器。",
                "原叶片为建模示意形状，未经气动性能优化。",
            ],
            "elapsed_seconds": time.perf_counter()-started,
        }
        (output / "geometry_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (WORK_DIRECTORY / "latest_output.json").write_text(json.dumps({"output_directory": str(output), "report": str(output / "geometry_report.json"), "fcstd": str(fcstd)}, ensure_ascii=False, indent=2), encoding="utf-8")
        write_readme(output, report)
        print("CFD_DONE " + str(fcstd), flush=True)
        print("VERIFICATION " + json.dumps(report["verification"], ensure_ascii=False), flush=True)
        return report
    except Exception:
        (output / "build_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        for document in (result, source):
            if document is not None:
                App.closeDocument(document.Name)


def write_readme(output, report):
    """写入中文处理记录、区域/边界表和导入约定。"""
    d = report["domain"]
    v = report["verification"]
    c = report["cleanup"]
    lines = [
        "# 风扇 CFD 几何准备记录", "",
        "本文件记录已完成的几何清理、流体域抽取和旋转区域建立，不包含网格和流场结果。", "",
        "## 输入与几何假设", "",
        "- 输入来自当前 FreeCAD 风扇文档的独立快照 source_current.FCStd。",
        "- 圆管内径 %.3f mm，流向为全局 −Z；锥罩侧为入口，电机支撑侧为出口。" % d["diameter_mm"],
        "- 入口位于 z = %.3f mm，出口位于 z = %.3f mm；入口延长 2D，出口延长 5D。" % (d["inlet_z_mm"], d["outlet_z_mm"]),
        "- 旋转包络为同轴圆柱，直径 %.3f mm，z = %.3f 至 %.3f mm。" % (d["rotor_envelope_diameter_mm"], d["rotor_z_min_mm"], d["rotor_z_max_mm"]),
        "- 后接口分别距后支撑和转子 %.6f mm / %.6f mm；位置根据真实表面距离确定，避免保守包围盒造成的薄流体层。" % (d["outlet_interface_to_support_mm"], d["outlet_interface_to_rotor_mm"]),
        "- 旋转轴：(0,0,1)，原点：(0,0,0)。转速和旋转正负方向尚未设置。", "",
        "## 几何处理与量化结果", "",
        "- 去掉四个安装孔和四个机框外角圆角；圆形风道内壁保持不变。",
        "- 将轮毂、七片叶片和锥罩融合为一个转子实体，消除叶根内部交叠 %.6f mm³。" % c["rotor_root_internal_overlap_removed_mm3"],
        "- 合并机框、电机壳和四根支撑；从定子中扣除与转子重叠的 %.6f mm³，消除原电机顶部与轮毂的内部干涉。" % c["rotor_stator_overlap_removed_mm3"],
        "- 保留叶尖间隙 %.6f mm；保留叶片厚度、扭转、锥罩和后支撑。" % c["tip_clearance_mm"],
        "- 清理前后圆管内固体占据体积的对称差为 %.9g mm³，即本次清理未改变流道边界。" % c["fluid_obstruction_symmetric_difference_mm3"], "",
        "## 流体区域", "",
        "| 区域名称 | 参考系 | 体积 mm³ | 封闭有效单实体 |",
        "|---|---|---:|---|",
    ]
    for name, info in report["fluid_regions"].items():
        lines.append("| %s | %s | %.6f | 是 |" % (name, "旋转" if name == "fluid_rotating" else "静止", info["volume_mm3"]))
    lines += ["", "## 边界与接口", "", "| 名称 | 相邻流体区 | 面积 mm² |", "|---|---|---:|"]
    for name, info in report["boundary_patches"].items():
        lines.append("| %s | %s | %.6f |" % (name, info["region"], info["area_mm2"]))
    lines += [
        "", "- inlet/outlet 的具体边界类型由后续工况决定；当前仅作几何命名。",
        "- interface_inlet_rotating ↔ interface_inlet_stationary 配对；interface_outlet_rotating ↔ interface_outlet_stationary 配对。",
        "- wall_rotor_rotating 是转子壁，在 MRF 中相对旋转区静止。",
        "- 所有 wall_duct_* 和 wall_stator_* 均为绝对静止壁；尤其不能将 wall_duct_rotating 或 wall_stator_rotating 设成随旋转区运动。", "",
        "## 几何验收", "",
        "- 三个流体区均通过有效性、封闭壳体、单一连通实体及 OCC 布尔检查。",
        "- 区域体积和误差：%.9g mm³；允许的数值公差：%.9g mm³。" % (v["volume_sum_error_mm3"], v["volume_tolerance_mm3"]),
        "- 未覆盖流体体积 %.9g mm³，多出流体体积 %.9g mm³。" % (v["uncovered_fluid_mm3"], v["extra_fluid_mm3"]),
        "- 所有流体区两两体积交叠：" + json.dumps(v["pairwise_overlap_mm3"], ensure_ascii=False),
        "- 边界归类覆盖 %d / %d 个面。" % (v["assigned_faces"],v["total_faces"]),
    ]
    for item in report["interfaces"]:
        lines.append("- %s：两侧接口匹配面积 %.6f mm²，面积差 %.9g mm²，外法向点积 %.6f。" % (item["rotating_patch"], item["area_mm2"],item["area_error_mm2"],item["outward_normal_dot"]))
    lines += [
        "", "## 文件与导入", "",
        "- fan_cfd.FCStd：完整审查文档，包含简化固体、流体区、命名边界和参考包络。",
        "- fluid_regions.step：仅包含三个流体体积，优先用于网格划分；也提供每个区域的独立 STEP。",
        "- cleaned_solids.step：两个清理后的固体，供壁面或共轭传热几何参考。",
        "- boundary_patches.step：命名边界面参考，不要与流体域当成重叠实体一起布尔。",
        "- rotor_envelope.step：参考旋转圆柱，含转子占据部分；实际旋转流体是 fluid_rotating。",
        "- 05 局部剖切预览：仅供显示，不作为计算域。",
        "- 几何以毫米保存；使用米制求解器时检查 STEP 单位识别，必要时采用 0.001 的长度缩放。",
        "- 三域接口采用匹配的独立面。网格前处理器需要共享拓扑，或建立非共形接口配对。", "",
        "## 尚待确定", "",
        "- 转速与转向、目标求解器、流量/压差及介质参数。",
        "- 体网格、边界层和湍流模型尚未建立；不能将 CAD 检查通过解释为网格质量已合格。",
        "- 入口/出口延长距离需要结合回流与压力恢复检查；叶片为未经过气动优化的建模示例。", "",
        "## 复现", "",
        "依赖 FreeCAD 1.1 自带 Python 模块。使用 freecadcmd.exe 的 -c 参数执行 build_fan_cfd.py；所有域尺寸设置位于脚本头部。再次运行会新建带时间戳的结果目录，保留已有 CFD 文档。", "",
    ]
    (output / "CFD处理记录.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()

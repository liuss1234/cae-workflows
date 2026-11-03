# -*- coding: utf-8 -*-
"""从已核验 CFD 文档导出面几何特征，用于 Gmsh 导入后的边界名称恢复。"""
# 本文件为七叶风扇参考实现；其他 CAD 必须重新映射零件与边界，不能直接套用。

from pathlib import Path
import os
import json
import FreeCAD as App

WORK_DIRECTORY = Path(os.environ["CFD_WORK_DIRECTORY"]).resolve()  # 由运行器指定独立项目目录


def main():
    """按面积和形心匹配面，不依赖 CAD 导入后的临时面序号。"""
    location = json.loads((WORK_DIRECTORY / "latest_output.json").read_text(encoding="utf-8"))
    directory = Path(location["output_directory"])
    report = json.loads(Path(location["report"]).read_text(encoding="utf-8"))
    document = App.openDocument(location["fcstd"])
    try:
        signatures = []
        for name, patch in report["boundary_patches"].items():
            obj = document.getObject(patch["region"])
            for face_name in patch["faces"]:
                face = obj.Shape.getElement(face_name)
                center = face.CenterOfMass
                signatures.append({"patch": name, "region": patch["region"], "face": face_name, "area_mm2": face.Area, "center_mm": [center.x,center.y,center.z]})
        (directory / "face_signatures.json").write_text(json.dumps(signatures,ensure_ascii=False,indent=2),encoding="utf-8")
        print("EXPORTED_FACE_SIGNATURES",len(signatures),flush=True)
    finally:
        App.closeDocument(document.Name)


if __name__ == "__main__":
    main()

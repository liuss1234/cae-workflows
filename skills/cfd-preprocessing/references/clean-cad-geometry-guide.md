# CAD 几何清理脚本使用手册

脚本路径：`scripts/clean_cad_geometry.py`

## 1. 适用范围

该脚本适用于对 STEP、IGES/IGS、BREP 几何执行基础拓扑清理，目标是提高后续 CFD 前处理和网格划分的可用性。

它适合处理：

- CAD 导入后的断裂拓扑或轻微几何不连续
- 重复点、线、面或实体
- 相邻面未缝合
- 闭合曲面壳未构造成实体
- 小边、小面导致的基础拓扑问题

它不负责自动生成流体域、识别边界条件或生成网格。

## 2. 安装依赖

建议使用 Python 3.9 或更高版本：

```powershell
python -m pip install gmsh
```

验证安装：

```powershell
python -c "import gmsh; print(gmsh.__version__)"
```

## 3. 最简单用法

在脚本所在目录执行：

```powershell
python clean_cad_geometry.py input.step
```

默认生成：

```text
input_cleaned.step
input_cleaned.json
```

原始 `input.step` 不会被覆盖。

## 4. 推荐用法

```powershell
python clean_cad_geometry.py `
  "D:\CFD\geometry\housing.step" `
  --output "D:\CFD\cleaned\housing_cleaned.step" `
  --report "D:\CFD\cleaned\housing_report.json" `
  --tolerance 1e-8
```

PowerShell 使用反引号 `` ` `` 换行；也可以写成单行命令。

## 5. 参数说明

| 参数 | 说明 |
|---|---|
| `input` | 输入 STEP、IGES/IGS 或 BREP 文件，必填 |
| `-o` / `--output` | 清理后的输出文件 |
| `--tolerance` | OCC 几何修复容差，必须为正数 |
| `--no-small-edge-fix` | 关闭小边修复 |
| `--no-small-face-fix` | 关闭小面修复 |
| `--no-sew` | 关闭相邻面缝合 |
| `--no-make-solids` | 关闭闭合壳实体构造 |
| `--force` | 允许覆盖已有输出文件 |
| `--report` | 指定 JSON 检查报告路径 |

### 容差选择

容差必须与 CAD 文件的单位和建模精度一致。默认值为 `1e-8`，只适合作为初始值，不应盲目增大。容差过大可能把真实窄缝、薄壁或小间隙错误地合并。

## 6. 典型场景

### 6.1 常规清理

```powershell
python clean_cad_geometry.py model.step -o model_cleaned.step
```

### 6.2 保留小边和小面

当小孔、窄槽、薄壁或圆角具有明确物理意义时：

```powershell
python clean_cad_geometry.py model.step `
  -o model_cleaned.step `
  --no-small-edge-fix `
  --no-small-face-fix
```

### 6.3 只做拓扑导入和重复实体清理

```powershell
python clean_cad_geometry.py model.step `
  -o model_deduplicated.step `
  --no-sew `
  --no-make-solids
```

### 6.4 已存在输出文件时强制覆盖

```powershell
python clean_cad_geometry.py model.step -o model_cleaned.step --force
```

生产流程中不建议默认使用 `--force`，应保留不同版本输出。

## 7. JSON 报告解读

报告主要字段：

- `entities_before`：清理前点、线、面、实体数量
- `entities_after`：清理后点、线、面、实体数量
- `highest_dimension`：最高几何维度，通常 `3` 表示存在实体
- `bounding_box_before` / `bounding_box_after`：清理前后包围盒
- `options`：实际启用的修复选项
- `warnings`：需要人工复核的事项

如果 `highest_dimension` 仍为 `2`，说明模型可能只有曲面壳，不能直接当作封闭流体体积使用。

## 8. CFD 后处理前复核

导出后应在目标前处理器中继续检查：

1. 几何是否封闭，是否存在泄漏边或非流形边。
2. 内部流动是否已抽取流体体积。
3. 外部流动远场尺寸和阻塞比是否合理。
4. 小孔、间隙、圆角和薄壁是否符合研究目标。
5. 单位、尺度和坐标方向是否正确。
6. 是否需要重新命名入口、出口、壁面和接口区域。

## 9. 常见错误

### `未找到 gmsh Python 包`

执行：

```powershell
python -m pip install gmsh
```

如果系统存在多个 Python，请使用执行脚本的同一个解释器安装：

```powershell
python -m pip --version
python -c "import sys; print(sys.executable)"
```

### `输入文件不存在`

检查路径是否正确。Windows 路径建议使用引号包围，避免空格导致解析错误。

### `输出文件已存在`

更换输出路径，或确认确实需要覆盖后添加 `--force`。

### 输出仍无法网格化

脚本只执行基础 OCC 清理。应在 CAD/CFD 前处理器中进一步执行修补、封孔、流体域抽取和局部特征简化，并定位具体坏面或泄漏位置。

## 10. 安全与可追溯性

- 永远保留原始 CAD 文件。
- 每次清理使用独立输出目录或版本化文件名。
- 保存 JSON 报告和实际命令行参数。
- 不要因为网格困难而未经评估删除可能影响压降、换热、泄漏、分离或声学的几何特征。

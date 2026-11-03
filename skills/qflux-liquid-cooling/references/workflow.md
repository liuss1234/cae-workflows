# 建模与本地运行

## 1. 独立副本和参数

运行 `init_case.py`，编辑新案例的 `workflow.json`。脚本拒绝覆盖现有目录。软件路径必须在实际运行的电脑上有效；案例不依赖原电脑用户名或父目录。

支持配置支路数量、间距、高度、矩形总管边长、支管边长/长度、冷板长度/宽度/间隙、流量、恒定密度/黏度、网格分层及求解参数。模板限制 `plate_gap < neck < header`、`plate_width > neck`、`pitch > plate_width`，支路须完整落在总管高度内。超出时需重建几何逻辑，不能绕过校验。

温度标签不自动计算水物性：改变温度时同步设置经可靠来源核对的密度、黏度。默认 25°C 水 ρ=997 kg/m³、μ=0.000890 Pa·s；不含温升。

## 2. 米制网格和 CAD

```powershell
& <build_python> <案例目录>\build_case.py
& <FreeCAD.exe> <案例目录>\create_cad.FCMacro
```

`build_case.py` 输出 case_parameters.json、mesh_check.json、mesh_arrays.npz、CGNS 和 MSH 2.2 ASCII。网格按各 box 的几何分界对齐并共节点，Gmsh 写出/检查离散单元，不是任意 CAD 自动六面体剖分器。

宏读取 SI boxes，转换 mm 后融合为一个有效实体，输出 STEP/FCStd、cad_check.json。GUI 会连续显示结果，不人为逐步暂停。命令行启动行为随 FreeCAD 版本有差异；若只打开而不执行，通过 Macro 菜单运行该文件。完成证据为 CAD_COMPLETE 日志和 cad_check 文件，不能凭窗口出现判断完成。

默认网格：597760 HEX8、672098 节点、28 边界、体积 0.00056256 m³。参数不同时数量必须重新计算。报告体积、包络和接口邻接，检查 cad_check 与 mesh_check 一致。

## 3. 原生工程和独立回读

```powershell
& <qflux_python> <案例目录>\setup_qflux.py
& <qflux_python> <案例目录>\verify_case.py --scheme FirstUpwind
```

先探测 API。设置标准 k–ω、能量关闭、入口法向速度 Q/A、出口表压、无滑移壁、实际边界 ID 的监测和 MPI。空间格式显式指定；若配置 SecondUpwind，回读 `--scheme SecondUpwind`。

API 设置写回嵌套对象，延长临时原生对象寿命，导出 settings.json。QFX 独立回读确认名称、类型、区域、节点/单元数量及格式；差异时停止，不提交求解。

## 4. 求解与阶段记录

```powershell
powershell -NoProfile -File <案例目录>\run_solver.ps1 -CaseRoot <案例目录> -Stage run
```

启动器不创建 QFX，先完成配置/回读。默认核数4，可按许可证和硬件修改，不固定继承原机16核。阶段目录不能预先存在；日志、job.json、finished.json 位于 run 内。存在目录时先检查任务及结果，保护原始文件，换新案例或明确的新阶段，不直接删除规避检查。

## 5. 可选续算

残差平台先诊断边界/拓扑/质量、质量守恒、监测趋势和物理稳态适用性。需要时：

- `prepare_continuation.py`：保留源工程空间格式，应用当前配置的松弛，保存 parallel_cooling_stable.qfx/run_stable。
- `prepare_robust.py`：明确改为 FirstUpwind，保存 parallel_cooling_robust.qfx/run_robust。

来源工程由 continuation.source_case 配置，迭代限额由 additional_iterations 配置；QSolver 对迭代参数的实际解释按日志确认，不能承诺一定为新增次数。独立回读后用启动器 `-Stage run_robust -InitialData <已完整写完的DAT>`。不要把重启输入简单指定为最新文件：最新文件可能仍在写入。

一阶续算不保证保持二阶精度。所有降阶/模型变化记录到报告，未收敛要保留阶段状态，不冒称求解完成。

## 6. 最终导出、统计、报告

求解正常结束后，以本阶段匹配的工程/数据独立回读，再导出：

```powershell
& <qflux_python> <案例目录>\verify_case.py --case parallel_cooling.qfx --data run\<实际结果.dat> --scheme FirstUpwind
& <qflux_python> <案例目录>\export_results.py run <实际DAT绝对路径>
& <build_python> <案例目录>\postprocess.py run
& <build_python> <案例目录>\write_report.py
python <技能目录>\scripts\package_delivery.py --case <案例目录> --output <新的交付ZIP路径>
```

续算把 run/工程替换为 run_stable 或 run_robust 配对。官方导出器可以输出 .vtm 和子目录 .vtu；必须等导出进程结束后解析。`post` 仅容纳一个最终阶段，切换阶段先将已有 post 保留为阶段归档，避免递归找到多个同名 VTU。

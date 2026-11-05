# QFlux 工程、MRF 与计算

## 运行环境与边界

普通 Python 工具与厂商匹配的 API Python 分开。使用目标机器实际安装，不在技能中保存 IP、账户或安装路径；远程连接沿用当前用户已授权的方式。检查 CPU/内存、许可、磁盘空间及同机作业，避免多套大网格同时争抢内存。

可使用目标 QFlux MCP、原生 GUI 或 API。MCP 需先列工具/宿主、核对宿主和当前模型，再读该版本声明，不能套用不存在的工具名。当前适配器使用 `qfxPyApi` 的既有 Windows API；Linux 通用工具可用，但厂商 ABI/求解器命令必须现场验证。

`qflux_adapter.py` 内置范围：一个空气类气体求解域、任意多个连通网格区、单转子、任意多对一对一接口、压力总压入口/静压出口或闭式壁面、常物性、等温无重力、稳态 MRF、KE 原生 subtype=2 / wallFunction=3。此枚举组合不应在未经版本文档确认时重新命名为其他湍流模型。其他边界/模型用目标版本扩展并回读。

## 配置与独立回读

1. `fan_case.py validate/check-mesh` 通过。源 CAD、CGNS 和质量证据哈希一致，全部壁面有明确层策略；门槛由本次工程目标制定。
2. 新进程 `qflux_adapter.py setup` 导入网格，核对区、边界、边界所属区、实际面数与米制包围盒；所有网格区归到同一个流体求解域。设置总/静压、物性、MRF、轴线/原点、各壁参考系、接口配对和数值参数。
3. 添加开口与接口质量/体积通量监控；按需要另设扭矩、压升、截面量。内置脚本不自动创建任意检测圆面，吊扇试验检测面需按真实布置设置。
4. 保存全新 QFX，禁止覆盖源文件或旧阶段。厂商 HDF5 保存可能不截断旧组，使用全新 staging 文件，成功后替换新目标。
5. 退出 API 进程，以 `readback` 新进程打开落盘 QFX，导出完整设置 JSON，并核对所有上述量。生成 `qflux_readback.json`，含 case/QFX/mesh/gate 哈希。

```text
<匹配API的python> scripts/qflux_adapter.py setup --case <案例目录> --qflux-home <安装目录>
<匹配API的python> scripts/qflux_adapter.py readback --case <案例目录> --qflux-home <安装目录>
python scripts/run_solver.py --case <案例目录> --solver-exe <QSolver实际路径> --min-free-gb <本次空间预算>
python scripts/run_solver.py --case <案例目录> --solver-exe <QSolver实际路径> --min-free-gb <本次空间预算> --execute
```

第一条 `run_solver` 只核验并显示命令。第二条在本次任务授权的计算范围内启动，使用 QFX 副本，记录 PID、日志、返回码与场文件清单。无需因脚本有 `--execute` 再重复向用户请求已给出的授权。每次重试新建阶段并修改 `files.qfx/run`，重新配置/独立回读；同一目录拒绝重复提交。

旋向采用右手定则；`view_direction_unit` 表示观察者看向模型的视线方向。`omega*dot(axis, view)>0` 对应从此视角顺时针。与叶片螺距、入口方向和有符号通量交叉判断；若不一致，报告证据，不擅自翻转用户指定转向。

## 工况与数值控制

自由送风是否使用 0 Pa 总压入口/0 Pa 静压出口由用户目标确认，报告中分清总压和静压。转速换算 `omega=sign*2*pi*rpm/60`。固定外框/静叶壁为 global，叶片/转动轮毂为 rotating；位于哪个网格区不能单独决定参考系。

动量格式、松弛和非正交修正次数均显式配置并回读。本脚本不假装已经设置速度上限、非正交限制开关或 correctFlux；若需这些试验，使用目标版本声明单独适配并记录前后导出 JSON，见 [诊断](diagnostics.md)。

用户指定 500 步时按该阶段上限执行；可能提前停止，最终以实际步号和终止原因为准。不要为凑步数静默取消收敛判定。原生求解器退出码 0 也可能未产生完整最终场；`run_solver` 只报告进程与文件，不签发收敛证明。

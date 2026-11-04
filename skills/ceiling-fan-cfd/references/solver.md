# QFlux适配、MCP和运行

查本机qxcmd.pyi/qxmod声明后使用API，不猜枚举。适配器来自项目验证链，当前支持+Z轴、双网格区、等温稳态MRF、Realizable k–ε；其他物理先适配。

```text
<API Python> scripts/qflux_adapter.py setup --config setup.json --output-dir checks --qflux-home <installation>
<API Python> scripts/qflux_adapter.py readback --config setup.json --output-dir checks --qflux-home <installation>
```

配置见`assets/qflux.setup.example.json`，所有路径需改成本机新阶段。两次独立进程；setup不求解，目标存在则停止。自动回读区数、单元/节点、边界、转速/原点、壁面参考系、物性、接口实际配对、检测面监控名称/类型/绑定和迭代保存。当前回读器尚不独立核验检测圆的实际几何半径/位置；该项须另用本机API或可视化证据确认。嵌套绑定逐层写回，保留对象生命周期；保存全新暂存QFX后原子改名，避免旧HDF5组残留。

可由本案例与网格验收报告生成配置：`make_qflux_config.py --case CASE --quality quality.json --mesh fan.cgns --target new/fan.qfx --result-dir new/result --output setup.json`。其中松弛和初始化值沿模板示例，应在运行前按本机API及已确认方案复核。

MCP实际可用时先发现/选宿主/查询信息，读automation guide与API，再getActiveModel只读确认。后台可完成则不开GUI。宿主中不重复initialize；CLI适配器独立initialize，不可直接塞进宿主。API成功、MCP成功、GUI显示、落盘回读分别举证。超时先检查状态/输出，避免重复提交。ICmdNewCase会清空活动模型，先确认归属和落盘。

运行时复制已验收源QFX到新阶段solver_input.qfx，记录输入哈希/命令/PID/核数/起止时刻；求解器可能改工作副本，源工程哈希应保持。Windows参考`QSolver.exe -q <input> -o <new-stage> -n <cores>`，以实际版本为准。资源忙时排队，不杀其他任务。PID不证明正在迭代；有界seek/read日志，避免全量或Get-Content -Tail。

换转速同步ω、运动体、输出和监测口径；只改文件名不算。2000步/4核是示例；仅用户要求跑满时将`solver.run_full_iterations`设为true，适配器才关闭残差提前终止，默认false保留软件原设置。数值调整另建阶段，跨软件对比说明格式、松弛和壁面处理差异。

`source_qfx`可选输入只接受纯网格工程，含运动设置则拒绝重复叠加。

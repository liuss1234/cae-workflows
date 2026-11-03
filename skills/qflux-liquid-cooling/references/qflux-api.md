# QFlux API 中容易遗漏的细节

- 官方 API 来自目标安装目录 qfxPyApi。Windows 已验证 CPython3.8 x64，使用 os.add_dll_directory 并保持句柄，PATH 加软件目录。通用 Python 与厂商 Python 分开，避免 NumPy/HDF5 ABI 混用。
- 嵌入式 Python 的 python38._pth 可能不包含脚本所在目录；API 脚本需先把自身目录加入 sys.path，才能加载同目录 runtime_config.py，不修改厂商的全局 _pth。
- 导入 CGNS 后，从 manager 读取真实对象/id；对比名称集合。不能凭 MSH Physical Groups 存在推定 QFlux 全部恢复。CGNS 保留网格区、QUAD4 命名边界与 m 单位元数据；MSH 2.2 ASCII 只是兼容备份。
- 对 `boundary.pri`、`num.discreteScheme.discreteFormat.momentum`、松弛曲线等嵌套对象，修改后逐层写回，再调用命令。API 的临时包装对象可能提前析构，KEEP 列表延长生命周期至保存结束。
- 已验证入口 CBCVeloInlet，directionType=1，速度 Q/A；出口 CBCPressOutlet；壁面 CBCWall。所有监测用真实 boundary id，物理区域名 coolant；无重力、无能量，压降为水力静压差。
- 流体材料的恒定属性使用 materialVariant；属性 API 名称包括 Density、Viscosity、SpecialHeat、ThermalConduct，不根据英语拼写猜测替代字段。
- 标准 KW 设置：CTurbulenceModelTurbulenceMethod.KW；已验证持久化 RANS type=1/subType=0/wallFunction=0，当前软件手册对应标准壁面函数。新版本需复核；不能把 KW 称为 SST。
- 已验证官方动量枚举 FirstUpwind=1、SecondUpwind=2。使用 momentumDiscreteOption.momentumTypeEnum 赋值，不猜编号。脚本独立回读该版本输出 JSON 后再标注格式。
- 入口湍流可能同时序列化 intensity、ratio、k、omega 等默认字段，必须按有效定义 method 解读；不能声称所有字段同时生效。
- 一些版本残差收敛后 DAT/最终边界监测编号比最后残差编号多1。只在 stdout 确认 `Convergent: Residual`、实际 DAT 文件名、`solver finished, code = 0` 且差值恰为1时接受。其他迭代差异拒绝混用。
- API 独立进程不是对正在打开 GUI 的实时控制；不要把 API 操作描述成界面点击。QFX 保存后另进程打开才算回读验证。
- VTU 必须通过官方 ICmdExportFile，选择实际 scalar fieldName/id 并包含点/单元场。导出可能是 vtm/子目录结构，等待进程退出再读取。模板只支持 ASCII HEX8；其他编码/单元要适配解析器。
- Python 原生 API 进程退出可能在包装对象析构时异常；本模板在成功保存/导出、flush 完成后 os._exit。失败打印 traceback 并 exit1；不吞掉真实错误。换版本应重新核验退出与落盘行为。

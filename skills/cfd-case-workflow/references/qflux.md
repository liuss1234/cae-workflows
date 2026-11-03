# QFlux 适配与实际持久化

## 官方 API 而非 GUI 会话

API 是独立进程，不是实时控制当前 GUI。需要用户观看操作时应明确说明，保存工程后在 GUI 打开；不能声称 API 脚本进行了界面点击。

Windows 实测官方 API 需要 CPython3.8 x64，普通建模用 Python3.11。启动时：

```python
# 安装路径来自本机配置，不写进技能。
sys.path.insert(0, qflux_home)
cookie = os.add_dll_directory(qflux_home)  # 持续保留句柄
os.environ['PATH'] = qflux_home + os.pathsep + os.environ.get('PATH', '')
from qfxPyApi import qxapp, qxcmd
qxapp.initialize()
```

嵌入式 Python `_pth` 不含脚本目录时，先把当前脚本目录加到 `sys.path`，不要擅改厂商全局文件。原生子对象保存在 `KEEP` 列表中到保存/导出结束，嵌套属性修改后逐层写回。部分绑定在解释器析构阶段异常，工具仅在成功验证、flush 后 `os._exit(0)`，失败打印 traceback 并退出1；不吞掉真实操作错误。

实际 API 以目标安装目录 `qfxPyApi/qxcmd.pyi`、`qxmod/*.pyi` 为准。本包不分发厂商 API 文件。

## 导入、保存和回读

- `ICmdImportMesh([cgns_path])`；以实际管理器名称/id建立映射。网格区 `qxZoneMng`、物理计算域 `regionMng`、边界 `boundaryMng` 分别检查。
- 保存：`ICmdSaveCaseParameter`，`fileType=1`、`persistence=ESaveCasePersistence.ProjectFile`。
- 回读：`ICmdOpenCaseParameter.onlyLoadCase=False`，随后可 `ICmdOpenData`。单独进程读落盘 QFX 才是独立验证。
- `qflux_case.py inspect` 对照 `regions.json` 和 `checks/mesh.json` 校验真实区、面数、节点单元、bbox、边界类别、流体/固体类别与所属计算域。另导出完整 `settings.json` 和配置中的 JSON Pointer 断言结果。
- `inspect --mesh --input <CGNS>` 只验证网格，明确不证明物理场配置。

## 基础等温设置

已用的命令：`ICmdSetRegionName`、`ICmdSetRegionZone`、`ICmdSetTimeMode`、`ICmdSetTurbulence`、`ICmdSetEnergy`、`ICmdAddProjectMaterial`、`ICmdSetRegionMaterial`、`ICmdSetBoundaryCondition`、`ICmdAddMonitor`、`ICmdSetFluidNumMethod`、`ICmdSetIterationControl`。

常物性材料属性 API 名：`Density`、`Viscosity`、`SpecialHeat`、`ThermalConduct`，属性值用 `materialVariant`，常数方法本机为1。不是按英文习惯猜 `SpecificHeat`。温度与粘度范围不适合常物性时另做函数/表格模型。

入口 `CBCVeloInlet`，本机 `pri.directionType=1` 沿入口内法向，`velocityMag` 为SI速度。多方向入口要检查法向，不能统一假定全局+X。出口 `CBCPressOutlet` 的 `staticPressure` 是表压定义，另核对参考绝压。壁面 `CBCWall`，对称面 `CBCSymmetricBoundary`。

离散格式用 `momentumDiscreteOption.momentumTypeEnum` 真实枚举，不猜数字。本包直管自检使用一阶迎风促进基础链路稳定，不作为所有案例推荐格式。

## CHT 与 MRF 编写适配器时

以下是本机历史案例实际使用的 API 路径，供查本机声明并实现。字段存在不是新案例成功证据，设置后独立回读关键值和检查接口通量。

| 工作 | 本机 API 与关键点 |
|---|---|
| 固体域 | `ICmdNewRegion(1)`；从新出现的真实ID找到域，命名并 `ICmdSetRegionZone` 分配固体区 |
| 能量 | 流体 `ICmdSetEnergy(region, True)`；固体导热设置、材料、初始化温度均需实际生效 |
| 温度/热流/外对流 | `txEnergyCondition` + `CTemperatureThermal` / `CHeatFluxThermal` / `CConvectionThermal`；设置 thermalConditionType 与真实子对象，写回边界 pri |
| 体积热源 | `txSourceTerm.Create(sourceVariable.typeEnum.Energy)`，`variable.publicData.energy`，domain.zones 指向真实加热区；`ICmdAddSourceTerm`；核对实际 W/m³ × m³ = W |
| 双侧接口 | `CBCInterfaceBoundary`、`surfaceId`、`ICmdSetBoundaryPaired`；可用性取决于区域组织/版本，成功后核对实际配对和几何，不把类型名称当配对结果 |
| 运动区域 | `dynamicMesh.txDynMeshRegion.Create`、`ICmdAddDynamicMesh`、`ICmdDynamicMeshAddZone`；核对 MRF/运动类型的实际枚举与序列化 |
| 旋转刚体 | `txCustomRigidBody`、`txDefineAxisAngleVelocity`、轴向/原点、`velocity=2*pi*rpm/60`、`ICmdAddRigidBody` |
| 壁面参考系 | `ICmdSetBoundaryReferenceFrame`；转子和定子分别核对绝对/相对参考系 |
| 理想气体 | 材料密度方法/variant由实际版本决定；检查导出 JSON 的有效模型，不能只改材料名。不要将旧案例数字编码当跨版本常量 |

接口经验：某版本跨独立流体计算域配对报 energy equation is off，不能为绕过错误随意开启能量；先检查计算域组织。空 `interfaceGroup=[]` 既不证明耦合完成，也不能泛化断言软件不支持该功能。

## 求解来源保护

本机 QSolver 在结束时会回写 `-q` 输入的 QFX。因此 `run_solver.py` 将已验证的源 QFX 复制到新阶段的 `solver_input.qfx`，对副本运行；源工程哈希保留，另记录副本结束哈希。不能因回写造成哈希改变就静默接受任意工程变更。

命令实测：`QSolver -q <阶段副本.qfx> -o <新阶段目录> -n <核数> [-i <完整DAT>]`，工作目录设安装根目录。自动保存间隔/最大迭代在工程中设置；命令行 `-o` 不能替代全部求解参数。

## 官方场导出

`qflux_case.py export` 从已完成记录选择非00000 DAT，核对源工程与场的哈希后回读，枚举实际 `scalarMng.fieldName/id`。本机速度模字段是 `U.mag`；`U.abs` 不能假定存在。若请求字段缺失，会保存 `available_fields.json` 并失败，按实际物理和名字适配，不能静默漏掉目标变量。管理器有某个名字也不证明对应方程已启用。

导出 `ICmdExportFileParameter.FileType=vtk_xml`、`ScalarDataMethod=3`。实际可能是 `.vtm` + 子目录 `.vtu`，不要只找顶层同名VTU。工具记录所有实际VTU及哈希，并检查请求变量实际写入；常物性密度虽可在管理器列出，某版本并不将其导出为场，需明确从材料常数重构并说明来源，不能谎称已导出密度场。

CHT 等多区可用 `post.zone_fields` 为每个导出区指定有效字段，例如 `{"fluid_main":["p","U.mag","T"],"solid_shell":["T"]}`，覆盖 `post.zones` 全部区。否则 `post.fields` 对所有区生效。不要要求固体必须有速度/压力场，或忽略热算例的温度。

`plot_vtu.py` 对单Piece、ASCII、纯TET4作真实平面求交；节点值线性插值、单元值常值，不跨固体/空洞外插。其他编码/单元必须用 ParaView/相应读取器或新适配器，不能伪解析。

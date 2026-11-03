# 环境、软件职责与迁移

历史验证日期为 2026-10-14。版本用于说明已验证组合；实际路径由接收电脑的环境配置指定。

| 软件/运行时 | 用途 | 已验证版本与约束 |
|---|---|---|
| FreeCAD | 参数建模、OCC 布尔、FCStd/STEP 与面签名 | 1.1；脚本通过 FreeCADCmd 执行，宏通过 GUI 执行 |
| Gmsh | 共享拓扑、物理组、四面体网格、CGNS 独立回读 | 4.14.1；需要可导入的 Python API，不能只安装 GUI |
| QFlux | CGNS 导入、区域/边界检查、QFX 保存与回读 | Windows V2026 / 13.77.1；自备安装与许可 |
| 普通 Python | Gmsh、NumPy、h5py 转换与检查 | CPython 3.11 x64 |
| QFlux API Python | 导入厂商 qfxPyApi | 历史为 CPython 3.8 x64；以目标安装 ABI 为准 |
| NumPy、h5py | 网格质量、拓扑与 CGNS 独立检查 | 安装到普通 Python 环境 |
| CGNS 原生 C 库 | 写入多区 CGNS | 历史为 QFlux 自带 qxcgns64.dll，64 位 cgsize_t |

Blender 不是本 BREP/CGNS 示例的必需依赖。通用几何方法可以迁移，QFlux 原生适配仅实测 Windows，Linux 需按厂商发行版核对库和 API。

## 配置和检查

从仓库根目录执行以下 PowerShell 命令；环境配置保存在被 Git 忽略的 `local/` 中：

```powershell
New-Item -ItemType Directory -Force local | Out-Null
Copy-Item skills/freecad-gmsh-qflux/assets/environment.example.json local/fan-environment.json
# 编辑 local/fan-environment.json，填写所有必要路径，再运行：
python skills/freecad-gmsh-qflux/scripts/probe_environment.py --profile local/fan-environment.json --check-imports
```

独立安装技能时，以上 `skills/freecad-gmsh-qflux` 改为实际技能目录。Python 和第三方库可安装在自备虚拟环境中，不修改厂商运行时。

| 配置字段 | 填写内容 |
|---|---|
| `freecad_gui`、`freecad_cmd` | FreeCAD GUI 和批处理程序的完整路径 |
| `gmsh_exe` | Gmsh 程序完整路径 |
| `gmsh_api` | 可找到 gmsh Python 模块及其库的目录 |
| `exchange_api` | 可找到 h5py 等交换依赖的目录 |
| `python_mesh` | 装有 Gmsh、NumPy、h5py 的普通 Python 完整路径 |
| `python_qflux` | ABI 匹配官方 API 的 Python 完整路径 |
| `qflux_directory` | 目标电脑的 QFlux 安装目录 |
| `blender_gui` | 可选，不参与必需项验收 |

当依赖由 pip 安装到虚拟环境时，`gmsh_api` 和 `exchange_api` 可以填该环境的 site-packages 路径；用该 Python 的 `python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"` 查询。Windows JSON 路径推荐使用 `/`，避免反斜线转义错误。

空字段会直接报错，不把当前目录误判为已配置路径。检查验证路径存在性和两套 Python 的真实导入结果，不代表已经执行几何生成、求解或许可证验证。

## 原生 API 与可见操作

QFlux API 初始化须将安装目录加入 `sys.path`，保留 `os.add_dll_directory()` 返回对象到操作结束，并将安装目录加入当前进程 PATH。所有变化限于该进程。

FreeCAD 展示宏中的 QTimer 在 GUI 主线程执行一步建模，再将下一步提交事件循环；大型 OCC 运算可使用 FreeCADCmd，结果随后在 GUI 中打开。不要将 OCC/文档树操作随意放入 GUI 后台线程。

本包不依赖 FreeCAD MCP 或自建 RPC；QFlux 独立 API 进程也不代表控制当前 GUI 会话。缺少桌面工具时不声称完成了界面点击。

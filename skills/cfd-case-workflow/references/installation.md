# 安装与迁移

## 给接收技能的智能体

解压后保持 `cfd-case-workflow/SKILL.md`、`scripts/`、`assets/`、`references/` 的相对结构。无需安装其他技能。

- Codex：把整个 `cfd-case-workflow` 文件夹放到本机 `$CODEX_HOME/skills/`；未设置 `CODEX_HOME` 时使用用户目录下 `.codex/skills/`。重载技能或新开会话，调用 `$cfd-case-workflow`。
- DeepSeek Harness：把整个 `cfd-case-workflow` 文件夹放到本机 `$DSH_HOME/skills/`；未设置 `DSH_HOME` 时使用用户目录下 `.dsh/skills/`。重载技能或新开会话后按技能名加载。
- 其他智能体：放到该平台规定的本地技能目录；若平台不自动发现技能，要求智能体先完整读取 `SKILL.md`，再按其链接读取当前阶段参考。不要假设不同产品有相同安装目录。
- 环境配置是每台电脑自己的文件，不包含在通用包中。仅有软件安装仍需核对 API ABI、许可和路径。

## 依赖与实测平台

| 依赖 | 用途与要求 |
|---|---|
| TF-QFLUX | 有效安装与许可，包含 QSolver、官方 qfxPyApi 和 CGNS 库；Windows V2026/13.77.1 路径实测 |
| QFlux MCP（可选） | 本机 QFLUX 安装提供的 `qflux-mcp.exe` 与 `qflux.exe --lc` 原生宿主；MCP 接入实测范围见 [QFlux MCP](qflux-mcp.md) |
| QFlux API Python | 与厂商 `.pyd` ABI 一致，本机为 CPython 3.8.10 x64；不能拿普通 Python 3.11 强行导入 |
| 普通 Python | 建议单独虚拟环境，脚本语法兼容 3.8+；实测 Python 3.11.9 |
| Gmsh + Python API | OCC 建模、网格、命名；实测 4.14.1。只有 gmsh.exe 不等于 Python 可以 import gmsh |
| NumPy、h5py | 网格质量、连接检查和独立 CGNS 回读；h5py 不负责拼造 CGNS |
| Matplotlib | 可选，实际场截面云图；不影响求解和基础验收 |
| FreeCAD | 可选，复杂 CAD 建模/几何清理/可视化；实测 1.1.1。直管自检使用 Gmsh 内置 OCC，不要求启动 GUI |
| SSH/OpenSSH | 仅远程任务需要，使用接收电脑自己的安全连接配置 |

通用 Python 工具适用于 Windows/Linux；**本包 QFlux Python API 适配器仅实测 Windows**。Linux Slurm 的原生命令链路已在基础直管验证，见 [验证范围](validated-scope.md) 和 [远程运行](remote.md)；它独立于 Windows API 启动器。Linux 路径、ABI、命令和库仍需按目标发行版核对，不能复制 Windows DLL 使用。

普通 Python 环境可按需安装：

```text
python -m venv .venv-cfd
<虚拟环境Python> -m pip install -r <技能目录>/assets/requirements-build.txt
```

新环境选择适合自身 Python 的版本；实测组合是 NumPy 2.4.6、h5py 3.16.0、Gmsh 4.14.1。不要把该组合装进 QFlux 的 Python 3.8 环境。

## 一次配置

用 `scripts/init_case.py` 生成案例。编辑案例的 `environment.json`，填写：

- `build_python`：普通 Python 的完整路径，或在当前 shell 可解析的命令；后续普通脚本都用同一个 Python 执行。
- `qflux_home`：QFlux 安装根目录。也可通过当前进程环境变量 `QFLUX_HOME` 覆盖；包不会修改全局设置。
- `qflux_python`：匹配官方 API 的 Python。检查 `qfxPyApi/*.pyi`、厂商文档和真实导入结果，不猜 ABI。
- `freecad_cmd`、`freecad_gui`、`gmsh_exe`：按需填写，不是强制路径。
- `extra_python_paths`：普通 Python 依赖已正常安装时为空；仅额外安装目录需要填写。
- `cgns_library`：默认 Windows 使用 `qflux_home/qxcgns64.dll`；其他库需显式指定。
- `cgns_index_bits`：本机库实测为 64；换库须确认 `cgsize_t` ABI，不能仅凭 DLL 名称推断。

配置中采用 JSON 合法路径：推荐 `/`；Windows 反斜线需写成 `\\`。避免把用户名、历史 SSH 地址写进技能。

```text
python tools/probe_environment.py --case . --check-api --output checks/environment.json
```

检测失败时报告具体缺项。探测只验证依赖和 API 导入，不代表许可证、求解和高级物理已验证。不要忽略非零退出码。

## 自检与正式案例

直管自检流程见 `SKILL.md` 的常用命令。完成一次几何→CGNS→QFX→独立回读→求解→场导出→验收即可验证该电脑的基础链路。采用新的案例目录和阶段名，不覆盖他人数据。

正式案例使用 `--example custom`，然后根据实际几何、工况写适配器。示例不是自动识别任意 STEP 并自动完成所有物理的按钮。无需在每个案例重写已通用化的环境探测、网格交换、回读、启动、验收和打包逻辑。

可转发给其他智能体的启动提示：

```text
请使用 cfd-case-workflow 技能。先读取 SKILL.md 和 references/installation.md，
检测本机 FreeCAD/Gmsh/TF-QFLUX、普通 Python 与 QFlux API Python，填写本机环境配置。
先运行包内直管自检，再根据我的几何和工况选择场景、编写适配器并执行相应阶段。
不要复制其他电脑的软件路径、账号或历史算例参数；按本次目标验收并打包。
```

软件升级后至少复核 API 导入、单区 QFX 保存回读及所需高级设置的持久化；不要声称本机实测自动覆盖所有版本。

选择 MCP 控制 QFlux 时，先按 [QFlux MCP 安装与使用](qflux-mcp.md)检查本机官方组件、Codex 配置和当前会话工具发现情况。MCP 是可选接入方式，不替代 QFlux API 环境检查，也不随技能包分发软件、许可证或 MCP 可执行文件。

# 换电脑安装与依赖

## 安装 skill

解压 ZIP，得到 `qflux-liquid-cooling` 文件夹。将整个文件夹放入目标电脑的技能目录：

- Codex，Windows：`%USERPROFILE%\.codex\skills\qflux-liquid-cooling`
- Codex，Linux/macOS：`~/.codex/skills/qflux-liquid-cooling`；设置过 `CODEX_HOME` 时使用该目录下的 `skills/qflux-liquid-cooling`。
- DeepSeek Harness，Windows：`%USERPROFILE%\.dsh\skills\qflux-liquid-cooling`
- DeepSeek Harness，Linux/macOS：`~/.dsh/skills/qflux-liquid-cooling`；设置过 `DSH_HOME` 时使用该目录下的 `skills/qflux-liquid-cooling`。

确认 `SKILL.md` 直接位于技能目录内，避免重复嵌套文件夹。重新打开 Codex 或新建会话后，输入：

> 使用 $qflux-liquid-cooling 创建储能柜八支路并联液冷管路，25°C 清水、8 L/min，计算压降和偏流，并输出流速/压力云图及支路流量表。

远程执行时补充用户自己的 SSH 目标和案例目录。不需要原电脑的历史聊天、原案例或另一份 skill。

可用 `python <技能目录>/scripts/verify_package.py <ZIP路径>` 只读核验 ZIP CRC 与 SHA256。技能已在原开发环境做过新目录建模、网格、QFX 回读及真实场后处理验证，具体边界见 [迁移验证记录](portability-check.md)。

## 软件职责与版本

| 软件/依赖 | 用途 | 迁移要求 |
|---|---|---|
| TF-QFLUX / QSolver | 配置、原生求解、QFX/DAT、官方 VTK 导出 | 自备合法安装与可用许可；检查公开 API 兼容性 |
| QFlux 兼容 Python | 导入 qfxPyApi | 已验证 Windows x64 CPython 3.8；随目标安装 ABI 调整，不能拿 3.12 强行加载 3.8 扩展 |
| 通用 Python | 建网格、图表、统计和打包 | 建议独立环境；numpy、gmsh、h5py、matplotlib |
| Gmsh | 离散 HEX8 网格写出与 Jacobian 检查 | 已验证 Python 包 gmsh 4.14.1；不是只安装 GUI 就有 Python 模块 |
| FreeCAD | 有效流体实体、STEP/FCStd | 已验证 1.1；执行原生宏，不要用普通 Python 直接 import FreeCAD |
| OpenSSH client/server | 按用户指定远程计算/传输 | SSH 登录事先可用；不在 skill 中保存私钥/密码 |
| MPI | QSolver 并行 | 按 TF-QFLUX 官方安装及配置 |

Blender 不属于本矩形 BREP/HEX8 水力案例的必需依赖。CFD 几何复杂时可改用其他建模/网格方式，但需同步更新边界和后处理映射。

软件二进制、厂商 API、DLL、完整手册和 Python 运行时均不在 ZIP 内。Linux/macOS 可阅读技能并运行通用 Python 助手；**本包原生 QFlux/CGNS 和 PowerShell 启动流程仅验证过 Windows**，其他平台须按厂商库适配，不能承诺零配置。

## 环境配置

用 `scripts/init_case.py --output <新案例目录>` 创建副本。`workflow.json` 集中配置几何、工况、软件目录、MPI、格式、验证阈值和字体。

```powershell
# 以下路径是占位示例，按目标电脑实际安装填写。
python <技能目录>\scripts\init_case.py --output D:\CFD\parallel_demo
python <技能目录>\scripts\probe_environment.py --config D:\CFD\parallel_demo\workflow.json --check-api
```

`software.build_python` 是装有 numpy/gmsh/h5py/matplotlib 的解释器；`software.qflux_python` 是兼容厂商 API 的解释器。依赖可在独立 venv 安装：`python -m pip install numpy gmsh==4.14.1 h5py matplotlib`。不要改装厂商内置 Python 的核心依赖；需要时由操作者维护单独兼容环境。

`software.extra_python_paths` 仅在已有离线依赖目录时填写；普通 pip 环境保持空数组。`QFLUX_HOME` 环境变量可覆盖 `software.qflux_home`。中文图表在 `post.font_path` 设置本机 CJK 字体绝对路径；字体不随包分发。

CGNS 写出使用目标安装的 `qxcgns64.dll`、64 位 cgsize_t 和 HDF5；这是已验证构建的 ABI，目标版本不同需确认，不能将任何 CGNS DLL 当作兼容替代。探测通过只代表环境可用，不能替代许可证/求解/实际网格回读验证。

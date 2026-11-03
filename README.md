# QFLUX2026 · 可复用 CAE 工作流

将本机已积累的 FreeCAD / Gmsh / TF-QFLUX 方法、脚本、参数模板及验证记录整理为四个独立技能包，支持复制到新电脑或新案例。当前内容以 CFD 前处理、水力计算和结果验收为主。

## 工作流选择

| 模块 | 用途 | 使用边界 |
|---|---|---|
| [cfd-case-workflow](skills/cfd-case-workflow/SKILL.md) | 推荐入口：几何、网格、QFX、求解、场导出、验收和打包 | 自动设置限单流体稳态等温；附直管安装自检 |
| [cfd-preprocessing](skills/cfd-preprocessing/SKILL.md) | 几何清理、区域命名、网格/y+ 策略与质量审查 | 不包含求解及后处理 |
| [freecad-gmsh-qflux](skills/freecad-gmsh-qflux/SKILL.md) | FreeCAD→Gmsh→米制多区 CGNS→QFlux 回读 | 附七叶风扇 FCStd 和前处理脚本；不启动求解 |
| [qflux-liquid-cooling](skills/qflux-liquid-cooling/SKILL.md) | 多支路液冷管路水力模板、求解和偏流统计 | 矩形流道演示；不自动包含共轭传热或真实冷板 |

各模块中的 `references/` 解释方法和验证范围，`scripts/` 提供工具，`assets/` 提供参数模板或示例输入。保留这些相对目录即可独立使用。

## 快速开始

以下命令从仓库根目录执行，路径同时适用于 PowerShell 和常见 Linux shell。案例放入被忽略的 `cases/`，避免提交生成结果。

```text
git clone https://github.com/Liuss1234/QFLUX2026.git
cd QFLUX2026
python -m venv .venv-cfd
```

激活虚拟环境：Windows PowerShell 使用 `.venv-cfd/Scripts/Activate.ps1`；Linux 使用 `source .venv-cfd/bin/activate`。随后安装普通建模环境依赖并初始化直管：

```text
python -m pip install -r skills/cfd-case-workflow/assets/requirements-build.txt
python skills/cfd-case-workflow/scripts/init_case.py --directory cases/duct-demo --example duct
```

编辑 `cases/duct-demo/environment.json`，填写本机 QFlux 安装目录和 API 匹配的 Python。普通建模 Python 与 QFlux API Python 分开；不要将普通环境依赖装入厂商 Python。

```text
python cases/duct-demo/tools/probe_environment.py --case cases/duct-demo --check-api
python cases/duct-demo/adapters/duct.py --case cases/duct-demo
python cases/duct-demo/tools/mesh_export.py --case cases/duct-demo
```

QFX 配置、独立回读、求解与场导出的后续命令见 [通用工作流入口](skills/cfd-case-workflow/SKILL.md)。正式模型使用 `--example custom`，根据实际几何与物理编写适配器。Codex 可选接入本机 QFlux MCP；安装注册、宿主检查和调用步骤见 [QFlux MCP 参考](skills/cfd-case-workflow/references/qflux-mcp.md)。风扇需要先复制并填写 [环境配置模板](skills/freecad-gmsh-qflux/assets/environment.example.json)，具体见 [风扇运行说明](skills/freecad-gmsh-qflux/references/fan-example.md)。

## 在其他电脑或智能体中复用

直接复制所需 `skills/<模块名>/` 到目标电脑的技能目录。Codex 默认目录为 Windows 的 `%USERPROFILE%/.codex/skills/` 或 Linux 的 `~/.codex/skills/`；设置了 `CODEX_HOME` 时使用其 `skills/` 子目录。重载后用 `$cfd-case-workflow` 等名称调用。其他智能体可先读取模块的 `SKILL.md`，再按阶段读取参考资料。

也可生成四个可直接解压安装的 ZIP，每个包都有内容 SHA256 清单和 ZIP 校验：

```text
python tools/package_workflows.py --output dist/cae-workflows
```

输出目录必须是新目录。ZIP 内保留完整模块结构和风扇示例模型；软件、厂商 API、DLL、许可证、SSH 凭据和本机配置由目标电脑自行准备。

## 仓库检查与验证范围

```text
python -m pip install -r requirements-dev.txt
python tools/check_repository.py
```

检查包含 Python/宏语法、JSON/YAML、技能元数据、相对文档链接、命令行入口、独立案例初始化、拒绝覆盖、风扇快照完整性以及打包后的 CRC/SHA256 回读。GitHub Actions 在 Windows 和 Linux 执行同一组检查，不启动商业求解器。

历史端到端证据与本次仓库检查分开记录，见 [验证范围](docs/VALIDATION.md)。通用 Python 工具可迁移；QFlux 原生 API/CGNS 链路仅实测 Windows。MRF、CHT、滑移、overset 等需要按目标软件与实际模型适配，基础链路验证不能代替这些物理场验证。

## 维护约定

- 可调案例参数集中在 `case.json`、`workflow.json` 或脚本头部；本机环境配置使用示例副本，放在 `local/` 或案例目录。
- 新案例使用新目录，原始 CAD、已交付结果和其他任务不覆盖。
- 变更通用脚本后运行仓库检查；涉及几何、接口、单位或求解设置时，还需执行相应原生软件验证并记录结果。
- 历史报告的数值仅说明特定案例；新报告使用本次真实测量和求解数据，明确网格、模型及误差限制。

本仓库分发自编工作流与示例，不包含厂商软件本体；第三方软件和库遵守其各自许可。仓库暂未声明统一开源许可证。

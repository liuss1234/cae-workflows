# cae-workflows · 可复用 CAE 工作流

面向 FreeCAD、Gmsh、TF-QFLUX 和 Slurm 的可迁移 CAE 技能包。仓库重点是 CFD 前处理、烘箱供风、风扇与液冷案例、求解验收和可追溯交付；商业软件、许可证、客户模型和本机配置不随仓库分发。

## 工作流选择

<!-- WORKFLOWS:START -->
| 模块 | 用途 | 使用边界 |
|---|---|---|
| [fluent-cae](skills/fluent-cae/SKILL.md) | Fluent 经验工作流：局部区域统计、边界条件复用和跨网格初场插值 | 面向公开 CFD 经验的可迁移操作整理；菜单、TUI 和变量名称需按 Fluent 版本复核 |
| [pointwise-cae](skills/pointwise-cae/SKILL.md) | Pointwise 经验工作流：NACA0012 几何、C-H 结构网格、T-Rex 边界层和局部加密 | 用于公开翼型教学和网格策略整理；不包含商业软件安装包、许可配置或产品网格验收结论 |
| [tecplot-cae](skills/tecplot-cae/SKILL.md) | Tecplot 经验工作流：Fluent 三维数据分开导出、局部切面和局部三维流线 | 面向后处理显示与数据组织；插值和消隐不等于增加物理精度或裁剪原始求解数据 |
| [oven-fluid-cfd](skills/oven-fluid-cfd/SKILL.md) | 烘箱供风域抽取、保形简化、挡片恢复、STAR切割体层覆盖、QFlux/Slurm诊断及逐出口风量统计 | 供风腔与多排风嘴；附真实失败/未收敛记录，不代替传热、回风全域或精度验证 |
| [fan-cfd](skills/fan-cfd/SKILL.md) | 风扇行业入口：几何清理、流体分区、STAR/Gmsh 网格、QFlux MRF 计算及风量/云图交付 | 单转子多区多接口适配；具体几何、软件版本及物理有效性需按案例验证 |
| [cfd-case-workflow](skills/cfd-case-workflow/SKILL.md) | 通用入口：几何、网格、QFX、VOF/UDF 初始相、求解、场导出、验收和打包 | 自动设置限单流体稳态等温；高级物理按目标软件能力和单独证据适配 |
| [cfd-preprocessing](skills/cfd-preprocessing/SKILL.md) | 几何清理、区域命名、网格/y+ 策略与质量审查 | 不包含求解及后处理 |
| [freecad-gmsh-qflux](skills/freecad-gmsh-qflux/SKILL.md) | FreeCAD 到 Gmsh 到米制多区 CGNS，再到 QFlux 回读 | 附七叶风扇 FCStd 和前处理脚本；不启动求解 |
| [qflux-liquid-cooling](skills/qflux-liquid-cooling/SKILL.md) | 多支路液冷管路水力模板、求解和偏流统计 | 矩形流道演示；不自动包含共轭换热或真实冷板 |
| [ceiling-fan-cfd](skills/ceiling-fan-cfd/SKILL.md) | 吊扇保形清理、试验室流体域、STAR/Gmsh 网格、QFlux MRF 和检测量交付 | 经验参数化入口；新产品需重新复核几何、标面、工况和商业 API 版本 |
| [qflux-slurm](skills/qflux-slurm/SKILL.md) | 复用目标超算 Slurm 脚本，隔离核数工况、登记作业号并汇总并行耗时 | 辅助工具不提交作业；多节点、GPU 和混合并行需单独适配 |
<!-- WORKFLOWS:END -->

烘箱供风腔和多排风嘴使用 `oven-fluid-cfd`；通用案例优先从 `cfd-case-workflow` 开始；散热风机和轴流风扇使用 `fan-cfd`；吊扇试验室复算使用 `ceiling-fan-cfd`。每个技能的 `SKILL.md` 负责入口和路由，详细方法放在对应 `references/`。

## 快速开始

```text
git clone https://github.com/liuss1234/cae-workflows.git
cd cae-workflows
python -m venv .venv-cfd
python -m pip install -r skills/cfd-case-workflow/assets/requirements-build.txt
python skills/cfd-case-workflow/scripts/init_case.py --directory cases/duct-demo --example duct
```

Windows PowerShell 使用 `.venv-cfd/Scripts/Activate.ps1` 激活环境，Linux 使用 `source .venv-cfd/bin/activate`。案例放入被忽略的 `cases/`；本机 QFlux 路径写入案例自己的 `environment.json`，不提交到仓库。

只安装单个技能时，复制对应的 `skills/<名称>/` 到宿主的技能目录：Codex 使用 `%USERPROFILE%/.codex/skills/`、`~/.codex/skills/` 或 `$CODEX_HOME/skills/`；DeepSeek Harness 使用 `%USERPROFILE%/.dsh/skills/`、`~/.dsh/skills/` 或 `$DSH_HOME/skills/`。保留技能内部的 `scripts/`、`references/`、`assets/` 和 `agents/` 相对结构。

也可以运行安装脚本，脚本会核对 `SKILL.md` 的 `name` 与目录名一致，默认跳过已存在的同名目录：

```text
python tools/install_skills.py --target codex
python tools/install_skills.py --target dsh --skill cfd-case-workflow --dry-run
```

## 仓库验证

```text
python -m pip install -r requirements-dev.txt
python -m ruff check tools tests
python -m pytest
python tools/check_repository.py
```

自动检查覆盖 Windows/Linux、Python 3.8/3.11、仓库工具 lint、源码与元数据、文档链接、CLI 帮助、案例初始化、拒绝覆盖、自检和安装包哈希回读。技能中的厂商 API 脚本常需先配置 DLL 路径再延迟导入，因此不统一套用导入顺序规则。自动检查不运行商业求解器，也不能代替网格质量、收敛、守恒和物理有效性验收。实际验证证据与限制见 [验证范围](docs/VALIDATION.md)。

## 打包与发布

```text
python tools/package_workflows.py --output dist/release-vX.Y.Z
python tools/package_workflows.py --output dist/cae-tools --workflow fluent-cae --workflow pointwise-cae --workflow tecplot-cae
```

输出目录必须尚不存在。可重复传入 `--workflow <名称>` 只打包所选技能。生成的技能 ZIP 和 SHA256 文件通过 GitHub Release 发布；标签采用 `vMAJOR.MINOR.PATCH`。下载统计口径见 [下载统计说明](docs/DOWNLOAD_STATS.md)，版本、分支和发布步骤见 [维护指南](docs/MAINTENANCE.md)。

## 贡献

所有变更通过分支和 Pull Request 提交，不直接推送 `main`。新增或修改技能前阅读 [贡献指南](CONTRIBUTING.md)；不要提交凭据、个人路径、客户数据、厂商程序或未经授权的第三方内容。

## 许可证

本仓库自编代码和文档采用 [MIT License](LICENSE)。第三方软件、格式、商标和用户提供的数据仍遵守各自许可与授权条件；MIT 许可证不授予商业软件或客户资料的再分发权。

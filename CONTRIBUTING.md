# 案例技能包贡献指南

欢迎把使用本仓库技能完成的 CAE 案例整理为独立技能包，再通过 Pull Request 贡献到 [cae-workflows](https://github.com/liuss1234/cae-workflows)。优先提炼可重复的方法、脚本、参数和验收依据，让其他用户与 AI 智能体能在新模型上复用。

## 一个可交付技能包应包含什么

以下以 `example-case-cfd` 为目录名示例，实际名称应能说明用途：

```text
skills/example-case-cfd/
  SKILL.md
  scripts/
  assets/
  references/
    validation.md
  agents/
    openai.yaml
```

`SKILL.md` 必须有 YAML 头部，`name` 与目录名一致，`description` 说明适用问题、触发条件及限制；正文给出依赖、输入、步骤、输出与失败恢复方式。`agents/openai.yaml` 为可选的智能体展示信息。其他目录按实际需要提供，不创建无内容的占位文件。

| 内容 | 交付要求 |
|---|---|
| 参数与脚本 | 参数集中、输入可替换，说明单位、软件版本与 API 约束；使用新目录保护源件，失败返回明确错误 |
| 示例输入 | 仅包含有权公开的最小示例；客户或保密产品可替换为公开/合成几何，并明确来源 |
| 工程方法 | 记录几何取舍、区域/边界、网格策略、物理模型和适用范围，避免写死个人机器路径或旧模型面号 |
| 验证记录 | 记录日期、环境、操作、结果、可核验依据及未验证项；区分语法/安装自检、软件回读和完整求解 |
| 结果与限制 | 按实际证据报告收敛、守恒、监测、y+、网格研究等；未开展的项明确说明，不编造误差或实测数据 |
| 许可与来源 | 写明自编内容、第三方来源及允许分发的依据；无法公开的内容不提交 |

技能中的历史算例数值应标明特定工况及证据来源，不能自动填入新案例报告。技能目录需要保留可迁移的说明和工具；大型结果文件可以单独作为交付附件。

## 提交前处理数据和环境信息

移除个人姓名/邮箱、用户名目录、主机/IP、SSH 配置、会话记录、密码/Token、私钥、许可证及厂商程序/DLL。示例环境配置使用空字段或占位符；客户数据或内部数据须确认允许公开。Git 提交的作者姓名和邮箱也可能公开，应事先检查 Git 身份设置。

打包器的后缀限制与哈希校验不能代替人工隐私和授权检查；CAD/工程文件内部属性、日志和图片也需要审核。AI 智能体可以协助整理和本地验证，向公开 GitHub 上传或向维护者提交 PR 前，应取得其所代表用户的授权；文档本身不构成替用户公开项目的许可。

## 贡献步骤

1. Fork 仓库并在自己的分支新增 `skills/<新技能名>/`；通用修复优先修改现有技能，避免仅更换案例名称就复制整套工作流。
2. 补充 `references/validation.md`，记录本次真实完成范围和复现操作。为脚本提供可在缺少商业软件时查看的 `--help`，合成自检不得伪装成产品性能验证。
3. 更新 README 的模块表及 `tools/check_repository.py`、`tools/package_workflows.py` 中的 `WORKFLOWS`；有 CLI 时加入 `CLI_ENTRIES`，有必要的独立自检时接入仓库检查。新增资源类型需要在打包器中明确支持。
4. 安装 `requirements-dev.txt` 后运行 `python tools/check_repository.py`。涉及几何、接口、单位或求解设置时，另按目标原生软件验证并保存证据；仓库检查通过不代替 CFD 验收。
5. 提交源文件和验证说明，发起 Pull Request。说明解决的问题、依赖、公开数据来源、验证结果、限制及交付附件。不要提交自动生成的本机配置或整套计算目录。
6. 维护者审核合并后，将通过校验的技能 ZIP 和必要的交付结果作为版本化 Release 附件发布，并在发布说明关联 PR、版本、复现步骤和校验值。附件下载计数见 [统计说明](docs/DOWNLOAD_STATS.md)。

当前仓库忽略 `cases/`、`dist/`、ZIP、QFX/DAT 和网格/场文件；GitHub 单个 Git 文件限制为 100 MiB，单个 Release 附件必须小于 2 GiB，实际以 [GitHub 大文件说明](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)和 [Releases 说明](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)为准。大结果优先精简为复现所需文件或拆分附件，不通过强制添加绕过仓库忽略规则。

## 独立技能打包示例

新技能接入统一清单后，可用 `python tools/package_workflows.py --output dist/release-vX.Y.Z` 为仓库中的所有技能打包。若需单独交付一个新技能，可在其根目录准备显式 `delivery.json`，只列实际存在且审核过的文件，例如：

```json
{
  "files": [
    "SKILL.md",
    "references/validation.md"
  ]
}
```

实际技能还应将必要脚本、模板、示例和依赖说明逐项列入；此最小清单只用于展示格式。从仓库根目录执行：

```text
python skills/cfd-case-workflow/scripts/package_artifacts.py create --root skills/example-case-cfd --manifest delivery.json --prefix example-case-cfd --output dist/example-case-cfd.zip
python skills/cfd-case-workflow/scripts/package_artifacts.py verify dist/example-case-cfd.zip
```

上述命令使用 Python 标准库；输出 ZIP 及哈希文件必须尚不存在。ZIP 内包含技能顶层目录、逐文件大小和 SHA256 清单，创建后自动回读 CRC 与内容哈希，并生成旁置 `.zip.sha256`。发布前再在独立目录解压，确认文档相对链接、必要资源及目标环境中的入口可用。

本仓库目前尚未声明统一开源许可证。贡献 PR 时明确自身内容的分发许可与第三方限制；公开可下载不代表任意内容都允许转授权或商用。

# 维护指南

## 分支策略

- `main` 只接收经过审查且检查通过的 Pull Request。
- 日常维护在短期分支完成；`codex/maintenance` 用于自动化维护准备，不作为长期发布分支。
- 禁止直接推送、强制推送和删除 `main`。紧急修复也通过最小 PR 完成，并保留验证记录。
- 开始修改前从 `origin/main` 同步；合并后删除已完成的短期远端分支。

打包器默认生成全部技能；为单独软件栏目交付时，可重复传入 `--workflow <名称>` 仅生成指定 ZIP。

## 变更来源

根目录 `workflows.json` 是技能目录、README 表格、CLI 检查和打包清单的唯一登记来源。修改清单后运行：

```text
python tools/update_readme.py
python -m pytest
python tools/check_repository.py
```

技能自己的操作说明仍由 `SKILL.md` 和 `references/` 维护。不要把案例细节复制回根 README。

## 版本规则

仓库使用 Semantic Versioning，标签格式为 `vMAJOR.MINOR.PATCH`：

- `PATCH`：文档澄清、兼容修复和不改变既有输入输出的脚本修复。
- `MINOR`：新增技能、CLI、支持格式或向后兼容的工作流能力。
- `MAJOR`：删除技能、改变公开参数/目录、破坏交付格式或需要人工迁移的变更。

尚未发布的变化记录在 `CHANGELOG.md` 的 `Unreleased`。发布时将条目移动到带日期的版本标题，创建同名 Git 标签和 GitHub Release。不要只在单个验证文档中声明新版本。

## 发布流程

1. 从干净的发布分支运行 lint、单元测试和完整仓库检查。
2. 完成涉及商业软件或超算的必要验证，并更新验证范围及未验证项。
3. 更新 `CHANGELOG.md`，确认版本号和发布日期。
4. 运行 `python tools/package_workflows.py --output dist/release-vX.Y.Z`。
5. 抽查 ZIP 内容、SHA256、技能入口和必要资产。
6. 合并 PR 后在 `main` 创建签名或受保护标签，并发布对应 ZIP 与校验文件。
7. 核对 Release 页面、下载链接和 Actions 状态，不从维护分支创建正式版本。

## 审查责任

`CODEOWNERS` 指定默认审查者，但不替代领域验证。涉及 CFD 物理、商业 API、客户授权或超算配置时，应由具备对应上下文的人复核。维护者不把自动检查通过解释为工程结果有效。

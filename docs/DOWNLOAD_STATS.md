# 技能下载统计说明

## 推荐口径：Release 技能附件下载次数

为每个技能发布独立 ZIP，例如 `fan-cfd.zip`，通过 Release 标签区分版本。维护者在仓库根目录运行：

```text
python tools/package_workflows.py --output dist/release-vX.Y.Z
```

将生成的 ZIP 和对应 `.zip.sha256` 文件上传为 [GitHub Release](https://github.com/liuss1234/cae-workflows/releases) 附件。将所需技能的附件链接写入发布说明，方便用户和 AI 智能体按版本下载。GitHub 自动生成的 Source code 压缩包不等于手动上传的技能附件。

每个附件由 GitHub 提供 `download_count`。同一技能跨版本的历史累计，需要汇总所有对应 ZIP 附件的计数；哈希文件的下载次数应单独排除。该值是 GitHub 报告的附件下载次数，不证明成功安装、实际运行、独立用户或案例完成数量，也无法可靠判断下载者是否为 AI。

## 查询与长期留存

GitHub REST API 的请求形式如下，`page` 从 1 开始，逐页查询直到返回空列表：

```text
GET https://api.github.com/repos/liuss1234/cae-workflows/releases?per_page=100&page=1
```

从每个 Release 读取 `tag_name`，从 `assets` 读取 `id`、`name`、`download_count`、`browser_download_url`。维护者可定期导出以下聚合字段为 CSV：

```text
snapshot_utc,release_tag,asset_id,asset_name,download_count
```

建议按月保存一份快照，并保留旧版本附件。删除后重新上传同名附件会产生新附件 ID，不应当作原计数的连续延伸。按附件 ID 关联快照；仅在同一附件持续存在时计算计数增量。仓库搬迁、附件删除或统计口径变化应在报表中注明。

公开仓库可尝试匿名查询，但受 API 速率限制；需要认证时使用维护者自己的凭据管理方式，不把 Token 写进文档、技能或统计文件。接口字段及权限以 [GitHub Releases API 文档](https://docs.github.com/en/rest/releases/releases#list-releases)为准。本次文档更新不自动创建 Release、定时采集任务或历史报表。

## 克隆和其他渠道

仓库维护者可在 Insights → Traffic 查看最近 14 天的克隆次数、独立克隆者及访问数据；需要长期克隆趋势时，应在窗口过期前定期保存。独立克隆者是 GitHub 定义的指标，不等于独立人类用户。详见 [GitHub 仓库流量说明](https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/viewing-traffic-to-a-repository)。

Raw 文件读取、网页访问、自动生成的源码压缩包、镜像下载和第三方技能市场不具有统一的 GitHub 技能下载计数。可以并列展示不同渠道的指标，不将它们简单相加为“总用户数”。Stars 和 Forks 也不代表下载次数。

## 面向其他 AI 智能体的约定

- 有技能 Release 附件时优先下载该附件，记录标签和校验值；按实际需要获取，不为增加统计重复请求。
- 没有附件时，可按 [README](../README.md) 中的仓库方式获取；不能声称这次获取已经计入 Release 下载量。
- 下载和使用无需回传本机用户名、IP、路径、项目文件或会话信息；技能中不增加自动回传请求。
- 使用者可自愿通过 PR 贡献可公开案例技能包。贡献数量与附件下载量分别记录，贡献不作为下载或使用的前置条件。

# QFlux MCP 安装与使用

## 适用范围

本流程面向 Codex 通过本机 QFlux MCP 控制本机 TF-QFLUX。实际安装可能随版本或许可包不同；不要从技能包安装/复制 QFLUX、`qflux-mcp.exe`、许可证或厂商 DLL。若安装目录没有 MCP 组件，应向软件供应方获取受支持版本。

本机已验证的链路为：Codex MCP 客户端（stdio JSON-RPC）→ QFlux 提供的 `qflux-mcp.exe` → `qflux.exe --lc` 原生 GUI 宿主 → `qfxPyApi`。其中：

- `qflux-mcp.exe` 是 MCP 服务端程序，负责向客户端公布工具。
- `qflux.exe --lc` 是供 MCP 连接的 QFlux 原生宿主，不是 MCP 配置项里的服务端命令。
- `run_qfx_python` 在所选原生宿主中执行 Python；这不同于 `qflux_case.py` 启动的独立 API 进程，也不等价于 GUI 鼠标操作。

本机 Windows QFlux V2026 集成实测使用服务端位于安装目录下 `qflux-mcp\qflux-mcp.exe`。先在目标电脑确认实际文件和厂商支持的启动方式，路径不可照抄到其他电脑。

## 注册到 Codex

使用安装目录内 MCP 服务端路径注册 stdio 服务。PowerShell 示例：

```powershell
$QfluxRoot = Read-Host '输入本机 QFLUX 安装目录'
codex mcp add qflux-mcp -- "$QfluxRoot\qflux-mcp\qflux-mcp.exe"
codex mcp get qflux-mcp
```

若服务器已登记，先查看当前配置并按本机 CLI 支持的方法更新该条目；不要重复添加同名服务器，也不要覆盖整个 Codex 配置。等效配置形态如下，路径应替换为本机实际位置：

```toml
[mcp_servers.qflux-mcp]
command = '<本机QFLUX安装目录>\qflux-mcp\qflux-mcp.exe'
```

注册成功只证明持久配置存在。MCP 工具是否已加载还需在 Codex 重载连接或新会话后检查当前工具清单。远程 SSH 上的 QFlux 不会因为注册了本机 MCP 而自动可控；远程主机需要独立支持并配置可达的 MCP 连接方式。

## 启动宿主并确认工具

先确认目标 QFlux 版本支持本机 MCP 宿主模式。Windows PowerShell 示例：

```powershell
& "$QfluxRoot\qflux.exe" --lc
```

若目标宿主已运行，复用它并先确认其中当前加载的案例；不要为了“重连”再启动多个宿主或覆盖当前工程。之后在 Codex 中依次完成：

1. 确认当前会话的工具清单中出现 QFlux MCP 工具；若没有，检查 MCP 配置状态并重载连接/新开本地会话。
2. 调用 `list_qflux_hosts`，区分 GUI 与 Python Console 宿主；调用 `select_qflux_host` 选择目标 `host_id`。
3. 调用 `get_qflux_host_info`，确认进程、当前模型/案例摘要和宿主状态。宿主 ID 可能随进程变化，不要硬编码到跨机器配置。
4. 编写脚本前调用 `get_qfx_automation_guide`，使用 `list_qfx_api_modules`、`search_qfx_api`、`get_qfx_api_symbol` 或 `read_qfx_api_stub` 查阅本机实际 API 声明。不要从函数名猜参数或枚举值。
5. 通过 `qfxPyApi.qxmod.runtime.getActiveModel()` 只读检查活动模型，再用 `run_qfx_python(code=...)` 执行已审阅的小步操作。GUI 宿主已初始化时通常不应再次调用 `qxapp.initialize()`；独立 CLI API 运行方式按 `qflux.md` 处理。

已验证版本在 2026-11-03 暴露了 11 个工具：宿主发现/选择/查询、自动化指南、Python 执行/上下文重置、API 模块列表/搜索/符号与 stub 读取。其他版本可能增删或更名，应以当前 MCP 的实际 `tools/list` 为准。

## 操作与结果核验

- 首先只读检查活动工程、区/边界、工况和结果文件来源；对已有案例保存到新名称/新目录，不覆盖源 QFX 或完整结果 DAT。进行写入前确认当前所选宿主确实是目标案例。
- 分离阶段执行导入、设置、保存、求解、导出；每阶段核查返回信息和落盘文件，再进行下一阶段。API 调用返回成功不等于设置已持久化；保存后重新回读并核对网格区、边界、物性、模型和监测设置。
- 长调用超时不代表宿主未执行。先用短状态调用、宿主日志和预期输出检查其是否完成；确认结果前不要重复提交求解、保存或导出操作。
- 导出场后核对 QFX/DAT 哈希、迭代号、有效字段、面位置和积分方向；将原生监测与场重构积分分别记录。MCP 调用链成功不代表求解收敛或物理结果有效，仍须遵循 [验收与交付](validation-delivery.md)。
- 脚本异常时先读取 traceback 和宿主状态。`reset_qfx_python_context` 仅清理所选宿主的 Python 全局执行上下文，不是重启宿主或恢复工程的命令。

## 已验证边界

本机集成证据覆盖 MCP initialize/tools-list、GUI 宿主发现与选择、Python 脚本执行、已完成真实 QFX/DAT 的读取、工况回读、检测面字段导出与积分。核对所用的 QFX/DAT 源哈希未改变；MCP 面场重构流量与已验收同一最终场的重构值差为 0，和求解器监测值差约 −0.0416%，来自积分口径差别。

该验证没有通过 MCP 启动新一轮求解，也没有证明所有网格导入、多物理场设置、高级接口或其他 QFlux 版本均可用。每台电脑、每个版本仍须先做小规模只读连接与 API 回读测试；高级操作必须按目标案例单独验收。

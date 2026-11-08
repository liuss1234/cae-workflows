---
name: fluent-cae
description: 基于公开 Fluent 经验，处理局部区域统计、边界条件复用和跨网格初场插值；适用于 Fluent 设置排查与后处理工作流，不替代版本匹配、网格质量和收敛验收。
---

# Fluent CAE 经验工作流

把公开经验整理成可审查的 Fluent 操作路径。先确认 Fluent 版本、求解器类型、网格尺度、区域/边界名称和目标物理量，再选择对应参考资料。涉及商业软件安装、许可证、破解或未授权文件时停止并改用官方安装与授权路径。

## 按任务读取

| 任务 | 资料 |
|---|---|
| 局部区域监测与统计 | [local-region-reports.md](references/local-region-reports.md) |
| 复用已有边界条件 | [boundary-condition-reuse.md](references/boundary-condition-reuse.md) |
| 跨网格迁移已有流场 | [field-interpolation.md](references/field-interpolation.md) |
| 来源、范围和版本边界 | [sources.md](references/sources.md) |

## 工作顺序

1. 保存原始 case/data，并把新操作放入独立工作目录。
2. 核对单位、网格尺度、区域连通性、边界名称、材料、模型、操作压强和参考值。
3. 执行局部区域分离、边界条件读取或场插值中的一个明确动作。
4. 回读设置和显示结果，检查变量、边界匹配、守恒和监测定义。
5. 将“设置导入成功”“初场已写入”“数值收敛”和“物理结果有效”分开记录。

## 关键约束

- Cell Register 只是标记集合；需要独立监测或统计时，才继续 Separate Cells 生成独立 Cell Zone。
- `write-bc/read-bc` 依赖区域名称匹配，且不会替代新网格的 Scale 检查；读取后重新核对边界、材料、模型和 Reference Values。
- `.ip` 插值文件只能作为新网格的初始场来源。插值完成不证明新工况收敛，也不替代网格无关性和守恒检查。
- 所有菜单路径、TUI 命令和字段名称都可能随 Fluent 版本变化；执行前以目标版本界面和官方文档为准。

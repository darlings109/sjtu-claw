---
name: course-report
description: 生成课程报告（课程小论文、学习总结、实验报告）的 Markdown 草稿，并通过 workspace update tool 保存。
---

# Course Report Skill

## 适用场景
- 课程小论文
- 课程学习总结
- 课程实验报告
- 读书报告

## 工作流程

1. 收集用户要求：课程名称、主题、字数要求、参考材料
2. 读取 workspace 中的参考材料（如果有）
3. 生成结构化 Markdown 报告草稿
4. 通过 workspace update tool + approval 流程保存到指定路径

## 报告结构

```markdown
# 标题

**课程名称：** [课程名]
**学生姓名：** [预留]
**日期：** [日期]

## 摘要
[200-300 字摘要]

## 正文

### 1. 引言
[背景介绍、问题提出]

### 2. 主体分析
[核心论述，分 2-3 个小节]

### 3. 总结与思考
[主要结论、个人思考]

## 参考文献
[参考材料列表]
```

## 输出要求
- 语言：中文
- 结构完整、逻辑清晰
- 按要求字数生成
- 使用该 Markdown 模板，保留字段占位符

## 注意事项
- 不使用外部 API 获取参考材料
- 材料内容完全基于用户提供的参考材料或 workspace 文件
- 最终通过 workspace update tool 保存，必须经过 approval

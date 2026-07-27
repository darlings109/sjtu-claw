# S09：Skill System

## 概述

为 claw 引入 Skill System（技能系统）。Skill 是面向某类任务的可复用能力包，保存稳定的工作方法和指令。与 system prompt 和 memory 不同，skill 只在任务需要时才加入上下文。

## 对应 TASK.md 要求

- [x] Skill Registry：扫描 `skills/` 目录，维护可用 skill 列表
- [x] 两级设计：catalog（~100 tokens/skill）注入 system prompt + `load_skill` tool 按需加载完整内容
- [x] 两种调用方式：显式 `/skill <name> <task>` 和模型自主选择
- [x] 至少 3 个 skill：`course-report`、`material-summary`、`presentation-outline`
- [x] Skill CRUD API（Web UI 中可创建/编辑/删除 skill）
- [x] Skill 内容注入 + workspace update tool + approval 保存结果
- [x] Skill 使用记录保存到 session

## 关键文件

| 文件 | 职责 |
|:-----|:-----|
| [skill_registry.py](../src/skill_registry.py) | 扫描/加载/索引 + catalog 生成 + CRUD |
| [context_builder.py](../src/context_builder.py) | 自动将 skill catalog 注入 system prompt |
| [tool_registry.py](../src/tool_registry.py) (`handle_load_skill`) | `load_skill` tool — 按需加载完整内容 |
| [main.py](../src/main.py) (`handle_skill_command`) | CLI `/skill list/show/<name>` 命令 |
| [web/server.py](../src/web/server.py) | Skill API：创建/编辑/删除/运行 |
| [skills/](../skills/) | 包含 4 个 skill 目录 |

## 架构设计 / 实现路径

### 两级加载（参考 LCC s07）

```
第一级：catalog（启动时注入 system prompt）
    skills/ 目录 → 每个 skill 的 name + description
    → 格式简短（~100 tokens/skill）
    → 模型看到 catalog，知道哪些技能可用

第二级：load_skill tool（按需加载）
    模型：我需要 course-report 的详细内容
    → 调用 load_skill("course-report")
    → runtime 返回完整 SKILL.md 内容
    → 模型根据指令执行任务
```

### Skill 目录结构

```
skills/
├── course-report/
│   └── SKILL.md           # YAML frontmatter + instructions
├── material-summary/
│   └── SKILL.md
├── presentation-outline/
│   └── SKILL.md
└── my-helper/
    └── SKILL.md
```

### SKILL.md 格式

```markdown
---
name: course-report
description: 用于生成课程报告类 Markdown 草稿，适合课程小论文、学习总结、实验报告等场景
---

# Course Report Skill

## 能力
根据用户给出的课程要求、主题、字数、参考材料和保存路径...

## 工作流程
1. 了解课程要求和主题...
```

### Skill 调用流程

```
显式调用（/skill）：
    用户：/skill course-report 帮我写一份读书报告...
    → main.py 识别 /skill 命令
    → load_skill("course-report")
    → 构造 enhanced_content = "[Using skill: course-report]\n\n" + skill_content + "\n\n---\n\nUser task: ..."
    → process_and_compact() 处理
    → 模型通过 update tool + approval 保存结果到 workspace

模型自主选择：
    用户：帮我写一份 2000 字读书报告...
    → context_builder.build_context() 时注入 skill catalog
    → 模型在 system prompt 中看到可用技能列表
    → 模型调用 load_skill("course-report") 获取完整内容
    → 根据 skill 指令执行任务
    → 需向用户发送 approval 告知"将使用 skill X"
```

### Catalog 注入

```python
def get_skill_catalog() -> str:
    """生成简短技能目录，注入 system prompt"""
    lines = ["Available skills:"]
    for info in _SKILLS_CACHE.values():
        lines.append(f"- {info['name']}: {info['description']}")
    lines.append("Use load_skill to get full details when needed.")
    return "\n".join(lines)
```

`context_builder.py` 中：

```python
def build_context(session):
    full_prompt = assemble_prompt()
    skill_catalog = get_skill_catalog()     # ← 注入技能目录
    if skill_catalog:
        full_prompt += "\n\n" + skill_catalog
    messages.append({"role": "system", "content": full_prompt})
    ...
```

## 核心代码解析

### Skill Registry 扫描

```python
def _scan_and_cache():
    """扫描 skills/ 目录，解析 SKILL.md 的 YAML frontmatter"""
    for d in SKILLS_DIR.iterdir():
        if not d.is_dir(): continue
        manifest = d / "SKILL.md"
        if not manifest.exists(): continue

        raw = manifest.read_text()
        meta, body = _parse_frontmatter(raw)    # 解析 --- frontmatter ---
        name = meta.get("name", d.name)
        desc = meta.get("description", body.split('\n')[0])

        _SKILLS_CACHE[name] = {
            "name": name,
            "description": desc,
            "content": raw,
            "path": str(d),
        }
```

### load_skill tool

```python
# 在 tool_registry.py 中注册
r.register(
    name="load_skill",
    description="加载指定技能的完整内容...",
    input_schema={"type": "object", "properties": {"name": {...}}, "required": ["name"]},
    handler=handle_load_skill,
)

def handle_load_skill(name):
    """返回完整 SKILL.md 内容"""
    from src.skill_registry import load_skill_content
    return load_skill_content(name)
```

### CLI 命令

```python
/skill list              → scan_skills() 打印列表
/skill show course-report → load_skill("course-report") 打印内容
/skill course-report <task> → 加载 skill + 注入 + agent loop
```

## 已实现的 Skill

| Skill | 功能 | SKILL.md |
|:------|:-----|:---------|
| `course-report` | 生成课程报告 Markdown 草稿 | [skills/course-report/SKILL.md](../skills/course-report/SKILL.md) |
| `material-summary` | 汇总 workspace 中的学习材料、课堂笔记 | [skills/material-summary/SKILL.md](../skills/material-summary/SKILL.md) |
| `presentation-outline` | 根据主题和材料生成课堂展示大纲 | [skills/presentation-outline/SKILL.md](../skills/presentation-outline/SKILL.md) |
| `my-helper` | 自定义助手 skill | [skills/my-helper/SKILL.md](../skills/my-helper/SKILL.md) |

## 优化方向

1. **Skill 依赖管理**：某些 skill 需要其他 skill 的输出作为输入，可支持 chain 调用
2. **Skill 模板渲染**：SKILL.md 中可包含模板变量，注入用户参数后渲染
3. **Skill 版本管理**：当前直接覆写 SKILL.md，可保留版本历史
4. **Skill 资源引用**：`assets/`、`references/` 子目录虽在设计中但当前未使用
5. **模型自主选择的审批**：当前隐式使用 skill 时告知用户，但用户不可拒绝

## 可能的问题

- **Catalog 过长**：如果 skills 数量多（>20 个），注入 system prompt 的 catalog 可能占大量 token。当前每个 skill 的 catalog 约 100 tokens
- **Skill 冲突**：不同 skill 可能有矛盾的指令。当前按加载顺序覆盖
- **load_skill 调用开销**：模型每次判断需要加载 skill 时，多一次 tool_call 往返，增加响应时间
- **SKILL.md 格式松散**：frontmatter 中 description 如果写得太模糊，模型可能无法准确判断何时该使用该 skill

## 关联文档

- TASK.md §Step 9（含 §9.6 实现要点）
- [产品验收报告 — Step 9 评分 (5/5)](/learn-sjtu-claw/assets/REVIEW.md)
- [REPORT.md — 技能组件清单](/learn-sjtu-claw/assets/REPORT.md)

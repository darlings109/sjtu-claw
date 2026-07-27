# SJTUClaw — 学习总结

> **项目名称：** 最小 AI Agent Runtime
> **项目周期：** 2026年6月 — 2026年7月
> **代码行数：** 14 个 Python 模块（~3300 行）+ 1 个前端页面（~600 行 JS+CSS）

---

## 项目全景

SJTUClaw 是一个从零构建的最小 AI Agent Runtime，基于 Python + OpenAI 兼容 API，支持 CLI 和 Web UI 两种交互入口。

### 核心架构

```
用户（CLI / Web UI）
    │
    ▼
┌─────────────────────────────────────────────────┐
│  main.py / server.py (Gateway)                   │
│  入口调度：CLI loop / HTTP API                   │
└──────────┬──────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────┐
│  agent.py (Agent Loop)                           │
│  process_message → LLM ↔ tool → final reply     │
│  process_and_compact → process + auto-compact    │
└──────────┬──────────────────────────────────────┘
           │
    ┌──────┴──────────┬──────────┬──────────┐
    ▼                 ▼          ▼          ▼
┌──────────┐ ┌────────────┐ ┌────────┐ ┌──────────┐
│ context  │ │ tool_regis │ │compactor│ │scheduler │
│_builder  │ │ try        │ │(L1-L3)  │ │(后台线程) │
│ prompt   │ │ 10 tools   │ │snip→mi │ │task CRUD │
│_loader   │ │ read/write │ │cro→LLM  │ │到期执行  │
└──────────┘ └────────────┘ └────────┘ └──────────┘
    │              │
    ▼              ▼
┌──────────┐ ┌────────────┐
│ session  │ │ workspace  │
│_store    │ │(路径安全)   │
│ memory   │ │ shell管理   │
│_store    │ │ approval    │
│ skill    │ │ download    │
│_registry │ │             │
└──────────┘ └────────────┘
```

### 两条入口，同一套引擎

| 入口 | 启动方式 | 用途 |
|------|---------|------|
| CLI | `python -m src.main` | 终端交互，调试 |
| Gateway | `python -m src.main gateway` | HTTP API + Web UI |

### 模块清单

| 模块 | 职责 | 关键暴露 |
|------|------|---------|
| [config.py](../src/config.py) | 从 `.env` 加载 API Key/Base URL/Model | `load_config()` |
| [llm_client.py](../src/llm_client.py) | Chat Completions API 封装（非流式+流式） | `chat_completion()`, `chat_completion_stream()` |
| [session_store.py](../src/session_store.py) | Session 数据模型 + JSON 持久化 + 线程安全 + 备份恢复 | `Session`, `create_session()`, `load_session()` |
| [agent.py](../src/agent.py) | Agent Loop 引擎 | `process_message()`, `process_and_compact()` |
| [context_builder.py](../src/context_builder.py) | 组装最终发给 LLM 的 messages | `build_context()` |
| [prompt_loader.py](../src/prompt_loader.py) | 分段 system prompt 组装 | `assemble_prompt()` |
| [memory_store.py](../src/memory_store.py) | 长时记忆 CRUD + 自动提取 + 合并整理 | `add_memory()`, `extract_memories()` |
| [compactor.py](../src/compactor.py) | 三级压缩管线 + transcript 备份 | `run_pipeline()`, `compact_history()` |
| [tool_registry.py](../src/tool_registry.py) | Tool 定义注册 + handler 执行 | `ToolRegistry`, `get_registry()` |
| [workspace.py](../src/workspace.py) | 工作区管理 + 路径安全 + shell + approval + download | `set_workspace()`, `create_approval()` |
| [scheduler.py](../src/scheduler.py) | 定时任务引擎（后台线程轮询） | `SchedulerEngine` |
| [skill_registry.py](../src/skill_registry.py) | 技能扫描 + frontmatter 解析 + 两级加载 | `scan_skills()`, `load_skill()` |
| [web/server.py](../src/web/server.py) | HTTP Gateway + REST API + SSE + 静态文件 | `GatewayHandler` |

---

## Step 索引

| Step | 功能 | 状态 | 核心代码 |
|:----:|:-----|:----:|:---------|
| [S00](s00-env-prep) | 环境准备与 LLM API 接入 | ✅ | `config.py`, `llm_client.py` |
| [S01](s01-multi-turn-loop) | 多轮对话 Loop | ✅ | `agent.py`, `main.py` |
| [S02](s02-multi-session) | 多 Session 管理与持久化 | ✅ | `session_store.py` |
| [S03](s03-context-management) | System Prompt / Memory / Soul | ✅ | `prompt_loader.py`, `memory_store.py`, `context_builder.py` |
| [S04](s04-compaction) | 上下文压缩 Compaction | ✅ | `compactor.py`, `agent.py` |
| [S05](s05-tool-agent-loop) | 只读 Tool 与 Agent Loop | ✅ | `tool_registry.py`, `agent.py` |
| [S06](s06-gateway-webui) | Gateway 与图形化入口 | ✅ | `web/server.py`, `web/static/index.html` |
| [S07](s07-scheduler) | Scheduler 与定时任务 | ✅ | `scheduler.py` |
| [S08](s08-workspace-approval) | Workspace / Advanced Tool / Approval | ✅ | `workspace.py`, `tool_registry.py` |
| [S09](s09-skill-system) | Skill System | ✅ | `skill_registry.py`, `context_builder.py` |

---

## 相关文档

| 文档 | 链接 |
|:-----|:-----|
| 产品验收报告 | [REVIEW.md](assets/REVIEW.md) |
| 产品体验评审（PM 视角） | [UX_REVIEW.md](assets/UX_REVIEW.md) |
| 中期报告 | [REPORT.md](assets/REPORT.md) |
| 下一阶段优化 SPEC | [SPEC.md](assets/SPEC.md) |
| 工程总览与任务分膛 | [NEXT.md](assets/NEXT.md) |
| 功能要求（TASK.md） | [TASK.md](../TASK.md) |

---

*SJTUClaw — commit `c33bd49`，14 个 Python 模块 + 4 个技能组件*

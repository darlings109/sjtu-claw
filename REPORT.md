# SJTUClaw — 中期报告

> **项目名称：** 最小 AI Agent Runtime
> **提交日期：** 2026-07-19

---

## 一、已实现功能

| Step | 功能 | 状态 |
|:----|:-----|:----:|
| 0-1 | 基础 LLM 调用（OpenAI 兼容 API）、多轮对话 Loop、SSE 流式/非流式 | ✅ |
| 2 | `/session` CRUD、JSON 持久化、线程安全锁、文件损坏自动备份恢复 | ✅ |
| 3 | system prompt + soul 加载、`/memory` 长时记忆、LLM 自动提取与整理 | ✅ |
| 4 | 三级压缩管线（snipping + micro-compact + LLM 摘要）、transcript 备份 | ✅ |
| 5 | 10 个 tool 注册（只读+写操作）、Agent loop（上限 10 轮）、写操作需 approval | ✅ |
| 6 | HTTP Gateway（端口 5000）+ REST API + SSE 端点 + Web UI（session管理/暗色模式/附件上传） | ✅ |
| 7 | 定时任务（一次性+周期性）、相对/绝对时间、后台线程轮询 | ✅ |
| 8 | Workspace 设置/路径安全检查、CLI 审批流程 | ✅ |
| 9 | Skill 目录系统、frontmatter 解析、技能 index 注入 system prompt | ✅ |

---

## 二、模块划分与核心数据结构

### 模块划分

| 模块 | 职责 |
|:-----|:-----|
| `main.py` | CLI 入口、命令分发、多轮对话 Loop |
| `agent.py` | Agent Loop 引擎、消息处理 + compaction 编排 |
| `llm_client.py` | LLM API 调用封装（非流式 + 流式） |
| `config.py` | `.env` 配置加载，`LLMConfig` dataclass |
| `session_store.py` | Session 数据模型 + JSON 持久化（线程安全） |
| `memory_store.py` | 长时记忆 CRUD + LLM 自动提取与整理 |
| `compactor.py` | 三级上下文压缩管线 + transcript 备份 |
| `context_builder.py` | 组装最终发送给 LLM 的 messages 列表 |
| `prompt_loader.py` | 分段 system prompt 组装（identity + soul + memory） |
| `tool_registry.py` | Tool 定义注册、handler 注册与执行 |
| `workspace.py` | 工作区管理、路径安全检查、shell 管理与审批 |
| `scheduler.py` | 定时任务引擎（后台线程轮询） |
| `skill_registry.py` | 技能扫描、frontmatter 解析、加载 |
| `web/*` | HTTP Gateway + 静态 Web UI |

### 核心数据结构

**Session：**
```
session_id: str      # "session_001"
title: str           # 会话标题
messages: List[Dict] # {"role": "user"|"assistant"|"tool", "content": str}
summary: str         # LLM 压缩后的摘要
created_at: str      # ISO 时间戳
updated_at: str
```

**Memory：**
```
memory_id: str       # "mem_001"
content: str         # 记忆内容文本
source: str          # "manual" | "auto"
created_at: str
```

**Tool Definition：**
```
name: str            # 工具名
description: str     # 描述
input_schema: dict   # JSON Schema 参数定义
handler: Callable    # 执行函数
```

**Task（Scheduler）：**
```
task_id: str         # "task_001"
content: str         # 任务内容
session_id: str      # 所属会话
trigger_at: str      # ISO 时间戳
repeat_rule: str     # "30m" / "1h" / ""（一次性）
status: str          # "pending" | "running" | "completed" | "cancelled" | "failed"
history: List[Dict]  # 执行记录
```

---

## 三、未完成部分与后续计划

### 已知问题

| # | 问题 | 优先级 |
|:-:|:-----|:-----:|
| 1 | 附件内容未真正读取——后端只传文件名未读文件内容 | **高** |
| 2 | API 响应格式不统一（CLI 带颜色前缀 vs Gateway JSON） | **中** |
| 3 | 附件用 UUID 命名不直观 | 低 |
| 4 | Web UI 会话搜索后切换 session 会重置筛选条件 | 低 |
| 5 | Web UI 界面视觉粗糙，无 Markdown 渲染 | 低 |

### 后续计划

```
Phase 1：体验修复（5-7 天）
├── 附件功能完善
│   ├── 后端 /messages 收到 attachments 后从 ATTACHMENTS_DIR 读取文件内容
│   ├── 将文件内容拼入 user message 前缀，使模型真正读到文件
│   └── 附件上传后保留原始文件名，替代 UUID 命名
├── 统一错误处理
│   ├── CLI 侧统一 [ERROR] / [WARN] / [INFO] 前缀打印
│   └── Gateway 侧统一 {ok: false, error: {code, message}} 格式
├── Web UI 会话搜索保持
│   └── load() 中 filter 逻辑改为全局变量存储，切换 session 后不丢失
│
Phase 2：Web UI 体验升级（5-7 天）
├── 界面美化
│   ├── 整体 CSS 重构（配色、间距、圆角、过渡动画）
│   ├── 消息气泡样式统一（user / assistant / tool 三态区分）
│   ├── 输入框选中态高亮、Send 按钮 hover 动效
│   └── 响应式布局适配移动端
├── Markdown 渲染 + 代码高亮
│   ├── 引入 marked.js（CDN 稳定版）
│   ├── assistant 消息渲染 Markdown，user 消息保持纯文本
│   └── 代码块添加语法高亮（highlight.js）
├── 审批弹窗
│   ├── 前端轮询 /api/approvals
│   └── 弹出审批卡片（tool 名称 + 参数预览 + 批准/拒绝按钮）
│
Phase 3：体验增强（3-5 天）
├── SSE 流式输出前端接入
│   ├── 前端用 EventSource 消费 /messages/stream 端点
│   ├── 逐 token 展示回复
│   └── tool_call 展示内联卡片（名称+参数+结果）
├── 键盘快捷键
│   ├── Ctrl+N 新建会话
│   ├── Ctrl+R 重命名当前会话
│   ├── Ctrl+D 删除当前会话
│   └── Ctrl+Shift+D 暗色模式切换
├── Session 搜索框
│   └── 侧边栏顶部添加搜索输入框，实时过滤列表
├── 消息操作栏
│   └── 每条消息 hover 出现复制按钮
│
Phase 4：深度开发（可选，2-3 天）
├── Agent 行为防死循环
│   ├── 工具调用轮次超限后的自动退出逻辑
│   ├── 等待用户回复时不再反复输出占位文本
│   └── 引入"耐心阈值"机制
├── Tool 执行沙箱
│   ├── shell 命令执行超时与资源限制
│   └── 路径访问白名单
└── Session 导出功能
    └── 单条/全部消息导出为 Markdown 或 JSON
```

---

## 四、总体进度评估

| 维度 | 状态 |
|:-----|:----:|
| Step 0-5（答辩基础功能） | 全部完成 ✅ |
| Step 6-9（答辩高阶功能） | 全部完成 ✅ |
| Web UI 体验 | 功能就绪，界面待美化 ⏳ |
| 代码质量 | 模块清晰，有单元测试，有文档 ✅ |
| 当前阶段 | 全部功能可运行，进入体验优化阶段 🎯 |

---

*SJTUClaw — commit `5c6450e`，14 个 Python 模块 + 3 个技能组件 + 6 个单元测试*

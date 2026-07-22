# SJTUClaw — 工程总览与任务分膛

## 项目现状（2026-07-22）

| 指标 | 值 |
|:-----|:----|
| Python 代码 | 14 个模块，~3300 行 |
| 前端代码 | 1 个 index.html，~600 行 JS+CSS |
| Git 提交 | 46+ commits |
| LLM API | DeepSeek 官方 API（直连） |

## 已完成

```
Phase A0 — Skill 系统完善 ────── ✅ 全部完成
├── ✅ Skill 智能调用（catalog 注入 system prompt + load_skill tool）
├── ✅ Scheduler 端到端验证 + Task API 补全
│   ├── Gateway 使用 process_and_compact
│   ├── GET /api/tasks/<id> 单个任务详情
│   ├── DELETE /api/tasks/<id> 取消任务
│   └── tests/test_scheduler.py 验证脚本
├── ✅ Skill 编辑/删除 UI（Overlay 弹窗）
├── ✅ Session 重命名/删除 Overlay 弹窗化
└── ✅ API 换为 DeepSeek 官方
```

## 后端 API 总览

### 已有 API（后端已实现）

| 端点 | 方法 | 已有前端 | 备注 |
|:-----|:----:|:--------:|:-----|
| `/api/health` | GET | ✅ | |
| `/api/sessions` | GET/POST | ✅ | |
| `/api/sessions/<id>` | GET/DELETE | ✅ | |
| `/api/sessions/<id>/rename` | POST | ✅ | |
| `/api/sessions/<id>/messages` | POST | ✅ | 发消息 |
| `/api/sessions/<id>/messages/stream` | POST | ❌ SSE | 流式输出 |
| `/api/sessions/<id>/attachments` | POST | ✅ | 上传文件 |
| `/api/sessions/<id>/attachments/<file>` | DELETE | ✅ | |
| `/api/skills` | GET/POST | ✅ | 列表/创建 |
| `/api/skills/<name>/content` | GET | ✅ | |
| `/api/skills/<name>/run` | POST | ✅ | |
| `/api/skills/<name>/edit` | POST | ✅ | |
| `/api/skills/<name>` | DELETE | ✅ | |
| `/api/tasks` | GET/POST | ❌ 无前端 | 定时任务 |
| `/api/tasks/<id>` | GET/DELETE | ❌ 无前端 | |
| `/api/approvals` | GET | ❌ 无前端 | |
| `/api/approvals/<id>/approve\|reject` | POST | ❌ 无前端 | |
| `/api/workspace` | GET/POST/DELETE | ❌ 无前端 | |
| `/api/downloads/<id>` | GET | ❌ 无前端 | |
| `/api/sessions/<id>/attachments` | GET | ❌ 无前端 | 附件列表 |

## 待办分膛（更新版）

### 膛 1：前端功能补全（已有后端但无前端）

| # | 任务 | 工作量 | 说明 |
|:-:|:-----|:------:|:------|
| 1 | **Task（定时任务）面板** | 1-2d | 创建/列表/取消/历史展示，点击创建 + 相对时间输入 |
| 2 | **Approval（审批）面板** | 1d | 进入 waiting 状态时展示弹窗，显示审批列表 + approve/reject 按钮 |
| 3 | **Workspace 管理** | 0.5d | 在设置区展示/设置/清除工作区路径 |
| 4 | **SSE 流式输出** | 1d | 前端 EventSource 消费 stream 端点，逐 token 显示 |

### 膛 2：界面补全（2 项）

| # | 任务 | 工作量 |
|:-:|:-----|:------:|
| 5 | 响应式布局 | 1d |
| 6 | 消息复制按钮 | 0.5d |

### 膛 3：体验增强（5 项）

| # | 任务 | 工作量 |
|:-:|:-----|:------:|
| 7 | 附件预览（文本内联展示） | 1d |
| 8 | 会话导出 Markdown | 0.5d |
| 9 | 键盘快捷键 | 1d |
| 10 | Session 搜索框 | 0.5d |
| 11 | 首次使用引导 | 0.5d |

### 膛 4：深度功能（4 项）

| # | 任务 | 工作量 |
|:-:|:-----|:------:|
| 12 | 桌面宠 | 3d |
| 13 | HTTPS 支持 | 1d |
| 14 | 统一错误处理 | 1d |
| 15 | SSE 后端极致优化 | 2d |

## 建议路线

```
Phase 1 — 前端功能补全（已有后端，缺前端）
  ├── Task 面板（最大缺口）
  ├── Approval 弹窗
  └── Workspace 设置

Phase 2 — 界面补全
  ├── 响应式布局
  └── 复制按钮

Phase 3 — 体验增强
  └── 附件预览 / 快捷键 / 搜索 / 导出 / 引导

Phase 4 — 深度功能
  └── 桌宠 / HTTPS / 错误处理 / SSE
```

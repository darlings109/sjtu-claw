# SJTUClaw — 后续工作规划 SPEC

## 一、优先级 P0：Web UI 核心交互修复

### 目标
网页端稳定可用：查看 session、切换 session、新建 session、发送消息。

### 任务清单
- [ ] 确认 session 列表点击切换功能（当前用 addEventListener 方案）
- [ ] 确认 +New Session 按钮创建并自动切换到新会话
- [ ] 确认 send 消息调用 API 并正确展示回复
- [ ] 确认发送中按钮 disabled 状态，防止重复提交
- [ ] 确认错误提示（API 失败时在聊天区显示）

### 验收标准
```
1. 打开 http://localhost:5000 看到左侧 session 列表
2. 点击任意 session，右侧加载对应消息历史
3. 在输入框输入文字，点击 Send 或回车发送
4. 消息显示在对话区，assistant 回复追加显示
5. +New Session 创建新会话并自动切换到新会话
```

---

## 二、优先级 P1：Web UI 增强功能

### 2.1 重命名 Session

#### 后端（server.py）
- `POST /api/sessions/<id>/rename` ✅ 已有
  - Body: `{"title": "新名称"}`
  - Response: `{"status": "renamed", "title": "新名称"}`

#### 前端（index.html）
- [ ] session 条目悬浮时显示重命名按钮（✏️）
- [ ] 点击弹出 prompt 输入新名称
- [ ] 确认后调 API 重命名，刷新列表

### 2.2 删除 Session

#### 后端（server.py）
- `DELETE /api/sessions/<id>` ✅ 已有
  - Response: `{"status": "deleted"}`

#### 前端（index.html）
- [ ] session 条目悬浮时显示删除按钮（✖）
- [ ] 点击弹出 confirm 确认
- [ ] 确认后调 API 删除，刷新列表
- [ ] 如果删除的是当前 session，自动跳回首页

### 2.3 会话 Header 显示
- [ ] 当前会话名称和 ID 显示在聊天区顶部
- [ ] 消息数量显示

---

## 三、优先级 P1：功能端到端验证与修复

### 3.1 Scheduler 定时任务（Step 7）
| 任务 | 说明 |
|------|------|
| 启动时自动启动 scheduler 线程 | 修改 main.py，gateway 启动时开启后台线程 |
| `/task new` 命令验证 | CLI 创建一次性任务和周期性任务 |
| 到期自动执行验证 | 等待任务到期，确认调用 agent loop 并写回 session |

### 3.2 Workspace + Approval（Step 8）
| 任务 | 说明 |
|------|------|
| `/workspace set <path>` 验证 | 设置工作目录 |
| `/workspace` 查看当前目录 | 确认路径安全解析 |
| `/approve <id>` / `/reject <id>` 验证 | 确认 approval 流程 |
| create_file / overwrite_file / edit_file 验证 | 确认文件操作受 workspace 边界保护 |
| new_shell / run_command 验证 | 确认 shell 命令执行和 approval |
| create_download 验证 | 确认下载入口创建 |

### 3.3 Skill System（Step 9）
| 任务 | 说明 |
|------|------|
| `/skill list` 验证 | 展示 3 个 skill |
| `/skill course-report <task>` 验证 | 显式调用，确认 skill 内容注入上下文 |
| 轻量索引注入 context builder 验证 | 确认普通对话中模型能看到 skill 索引 |

---

## 四、优先级 P2：优化与增强

### 4.1 API 错误友好提示
- Gateway 消息 API 在 LLM 调用失败时返回友好错误而非 500
- 前端展示 `[API Error]` 而非白屏

### 4.2 启动优化
- gateway 支持 `--port` 参数自定义端口
- 启动时自动清理过期任务

### 4.3 Tool 优化（参照 learn-claude-code 的 s02）
- 工具定义与 handler 分离已有的验证
- 并发安全判断 + 批量执行（当前按顺序执行）

---

## 五、Web UI 状态总览

```
┌─────────────────────────────────────────────┐
│  Sidebar (260px)           │  Main          │
│  ┌──────────────────────┐  │  ┌─────────────┐│
│  │ SJTUClaw             │  │  │ Messages    ││
│  │ [+ New Session]      │  │  │ Area        ││
│  │──────────────────────│  │  │             ││
│  │ session_001  5 msgs  │  │  │             ││
│  │ session_002  2 msgs  │  │  │             ││
│  │ session_003  0 msgs  │  │  ├─────────────┤│
│  │                      │  │  │ Input + Send││
│  └──────────────────────┘  │  └─────────────┘│
└─────────────────────────────────────────────┘
```

## 六、CLI vs Web 命令对照

| 功能 | CLI 命令 | Web UI |
|------|---------|--------|
| 新建 session | `/session new` | +New Session 按钮 |
| 切换 session | `/session switch <id>` | 点击列表项 |
| 重命名 session | `/session rename [id] <title>` | 悬浮✏️ → 弹窗 |
| 删除 session | `/session delete <id>` | 悬浮✖ → 确认 |
| 查看 session 列表 | `/session list` | 侧边栏自动展示 |
| 发送消息 | 直接输入 | 输入框 + Send |
| 添加记忆 | `/memory add <content>` | （暂不实现） |
| 定时任务 | `/task new <content> <time>` | （暂不实现） |
| 设置 workspace | `/workspace set <path>` | （暂不实现） |
| 技能调用 | `/skill <name> <task>` | （暂不实现） |

## 七、技术债务

- [ ] `.env` 中包含真实 API KEY → 下次提交前清理
- [ ] `Flask` 空文件应删除
- [ ] 统一错误处理：CLI 和 Gateway 的错误消息格式一致
- [ ] session_store 中 summary 字段写入兼容性检查
- [ ] Web UI 当前使用 `http.server`（零依赖），保持这一选择

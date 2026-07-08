# SJTUClaw — 优化与修复计划 SPEC

> 基于 2026-07-08 产品验收报告（REVIEW.md），按优先级制定改进计划。

---

## 一、优先级 P0：运行时 Bug 修复

### P0-1：Workspace 缺少 `create_download` 实现

**问题：** `tool_registry.py` 第 244 行 `from src.workspace import create_download as ws_dl`，但 `workspace.py` 中没有定义此函数。所有涉及 `create_download` 的 tool call 都会抛出 `ImportError`，导致 agent loop 中断。

**修复方案：**

```python
# workspace.py 新增

_downloads: Dict[str, Path] = {}
_downloads_lock = threading.Lock()

def create_download(path: str) -> str:
    """为 workspace 内文件创建临时下载入口"""
    r = safe_resolve(path)
    if r is None:
        return "Error: path outside workspace or workspace not set"
    if not r.exists():
        return f"Error: file not found: {path}"
    if not r.is_file():
        return f"Error: not a file: {path}"
    
    import uuid
    download_id = f"dl_{uuid.uuid4().hex[:12]}"
    with _downloads_lock:
        _downloads[download_id] = r
    return f"Download created: /api/downloads/{download_id}  (file: {path}, {r.stat().st_size} bytes)"
```

```python
# server.py 新增路由（在 do_GET 中）

if path.startswith('/api/downloads/'):
    dl_id = path.split('/api/downloads/')[1].split('/')[0]
    from src.workspace import get_download_path
    file_path = get_download_path(dl_id)
    if file_path is None:
        return self._json({"error": "download not found"}, 404)
    # 返回文件内容
    try:
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Disposition', f'attachment; filename="{file_path.name}"')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    except Exception as e:
        return self._json({"error": str(e)}, 500)
```

**涉及文件：** `src/workspace.py`、`src/web/server.py`

**验收标准：**
```
1. 设置 workspace
2. 模型调用 create_download tool
3. 返回 downloadId
4. 通过 GET /api/downloads/<id> 可下载文件
5. 不存在的 downloadId 返回 404
```

---

### P0-2：Workspace 缺少 `copy_attachment_to_workspace` 实现

**问题：** TASK.md Step 8.1 明确要求实现 `copy_attachment_to_workspace` tool，但该工具完全未实现。用户通过 Gateway 上传的附件无法传输到 workspace 供 agent 操作。

**修复方案：**

```python
# workspace.py 新增

def copy_attachment_to_workspace(attachment_id: str, dest_path: str) -> str:
    """将 session 绑定的附件复制到 workspace 内指定路径"""
    ws = get_workspace()
    if ws is None:
        return "Error: workspace not set"
    
    # 查找附件文件
    from src.config import ROOT_DIR
    attachments_dir = ROOT_DIR / "data" / "attachments"
    # 附件按 session 隔离存储，需要 session_id 参数
    # 需确认函数签名是否包含 session_id
    ...
```

> ⚠️ 注意：需要先确认 Attachment 的存储结构和 session 绑定方式（当前 `data/attachments/` 为空目录，附件上传功能可能也未完全实现）。

**前置依赖：** 确认 Gateway 附件上传 API 是否已实现（POST/GET `/api/sessions/<id>/attachments`）。

**涉及文件：** `src/workspace.py`、`src/web/server.py`、`src/tool_registry.py`

---

## 二、优先级 P1：功能补齐

### P1-1：Advanced Tool Approval 全面修复与 Web UI 支持

**现状：**
- `wait_approval(timeout=120)` API 不匹配问题 → 已修复
- 但 Web UI 没有任何审批交互能力
- 审批状态通知依赖 CLI print，用户可能看不到

**修复方案：**

```
1. Gateway 新增审批 API：
   - GET  /api/approvals           — 列出待审批项
   - POST /api/approvals/<id>/approve — 批准（可选 body: {reason: "..."}）
   - POST /api/approvals/<id>/reject  — 拒绝（可选 body: {reason: "..."}）

2. Web UI 新增审批弹窗：
   - model 发起高级 tool 调用时，前端弹出审批卡片
   - 展示 tool 名称、参数预览
   - "批准" / "拒绝" 按钮 + 可输入理由
   - 审批完成后自动继续对话

3. Approval 持久化：
   - 当前 approval 存在内存中（模块级全局变量），Gateway 多线程下不可见
   - 改为存储在 data/approvals/ 或由 Gateway 统一管理
```

**涉及文件：** `src/web/server.py`、`src/web/static/index.html`、`src/workspace.py`

**验收标准：**
```
1. 模型请求 create_file → Web UI 弹出审批卡片
2. 点击批准 → 文件写入 → assistant 回复确认
3. 点击拒绝 → 不写入 → assistant 回复拒绝原因
4. CLI /approve <id> 和 /reject <id> 继续可用
```

---

### P1-2：修复 `micro_compact` 压缩管线 L2 死代码

**问题：** `compactor.py` 第 29-31 行 `_is_tool_result_message` 检查 `msg.get("role") != "user"`，但实际 tool result 消息的 role 是 `"tool"`（由 `agent.py` 第 70 行 `"role": "tool"` 写入）。因此该函数永远不会返回 True，L2 micro_compact 实际上从未生效。

**修复方案：**

```python
# compactor.py 第 29-31 行 修改
def _is_tool_result_message(msg: Dict) -> bool:
    if msg.get("role") != "tool":  # 改为 "tool"
        return False
    content = msg.get("content")
    if not isinstance(content, str):
        return False
    return True
```

> ⚠️ 注意：当前 tool result 以 role=`"tool"` + `content`（字符串）格式存储（参考 `agent.py:69-73`），而 `micro_compact` 中的 `collect_tool_results` 函数（第 82-90 行）检测的是 `role == "user"` 且 `content` 是 `list` 类型，这也不匹配。需要统一 tool result 的数据结构判断逻辑。

**涉及文件：** `src/compactor.py`

---

### P1-3：Web UI 增加 Skill / Task / Workspace 管理入口

**现状：** Web UI 只支持基础聊天和 session 管理，无法操作 skill、task、workspace。

**方案：**

```
1. 侧边栏增加功能标签页切换（Chat / Skills / Tasks）
2. Skills 页：展示 skill 列表、描述、点选调用
3. Tasks 页：展示任务列表、状态、可创建/取消
4. Workspace：输入框设置路径，当前状态显示
5. 聊天输入框支持 / 命令自动补全提示

API 新增：
   GET  /api/skills           — 列出 skill
   GET  /api/skills/<name>    — 获取 skill 详情
   POST /api/skills/<name>/run — 调用 skill + 输入任务
   
   GET  /api/tasks            — 列出任务
   POST /api/tasks            — 创建任务
   POST /api/tasks/<id>/cancel — 取消任务
   
   GET  /api/workspace        — 获取当前 workspace
   POST /api/workspace        — 设置 workspace
   DELETE /api/workspace      — 清除 workspace
```

**涉及文件：** `src/web/server.py`、`src/web/static/index.html`

---

## 三、用户体验优化（UX Enhancement）⭐ 新增

> 以下优化参考了 **ChatGPT、Claude Code、Cursor、GitHub Copilot** 等产品的交互设计，
> 从用户真实使用场景出发，提升 SJTUClaw 的易用性和愉悦感。

### UX-1：流式输出（Streaming Response）— P1

**参考产品：** ChatGPT、Claude Code、Cursor

**现状：** 用户发送消息后，整个页面卡住等待完整 LLM 响应，数秒后才一次性显示。没有任何中间反馈。

**问题：**
- 超过 5 秒的无反馈等待，用户会怀疑程序是否卡死
- 无法感知模型正在生成、正在调用工具等中间状态
- 长回复要等全部生成完毕才能看到开头

**方案：**

```
1. Gateway 支持 SSE (Server-Sent Events) 流式输出
   - POST /api/sessions/<id>/messages/stream
   - 事件类型：
     event: token      — 文本 token（实时显示 assistant 回复）
     event: tool_call  — 模型请求调用工具（展示 tool 卡片）
     event: tool_result— 工具执行完毕（展示结果摘要）
     event: done       — 回复完成
     event: error      — 错误发生

2. Web UI 流式渲染
   - 消息气泡实时追加 token
   - tool_call 显示为可折叠的灰色卡片（名称 + 参数预览）
   - tool_result 显示为绿色卡片（成功）或红色（失败）
   - 所有 tool 交互在对话流中可见，不阻塞对话
```

**Claude Code 参考：** tool call 显示为 `[tool_call] name {"arg": "val"}` 灰色前缀，tool result 缩进展示，用户可以展开查看完整结果。

**验收标准：**
```
1. 发送消息后 1 秒内看到 placeholder "Claw is thinking..."
2. assistant 回复内容逐字出现
3. tool call 以卡片形式内联展示
4. 对话流完整连贯，无卡顿
```

---

### UX-2：Markdown 渲染 + 代码高亮 — P1

**参考产品：** ChatGPT、Cursor、GitHub Copilot Chat

**现状：** Web UI 使用 `textContent` 渲染消息，所有 Markdown 标记（`# 标题`、`` `代码` ``、```代码块```）以纯文本显示，完全不可读。

**问题：**
- assistant 回复包含大量结构化 Markdown（报告草稿、代码、列表），纯文本根本无法阅读
- 验收测试中模型生成的 350 字读书报告全是纯文本，标题、列表、代码块全部混在一起
- 一个"写作助手"不能展示格式化文本，是核心体验缺陷

**方案：**

```html
<!-- 引入 Marked.js 轻量 Markdown 渲染（CDN，零构建） -->
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<!-- 引入 highlight.js 代码高亮 -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/highlight.js@11/styles/github.min.css">
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/highlight.min.js"></script>

<script>
// 渲染消息时
function renderMessage(role, content) {
  if (role === 'assistant') {
    var html = marked.parse(content);
    var div = document.createElement('div');
    div.innerHTML = html;
    div.querySelectorAll('pre code').forEach(function(block) {
      hljs.highlightElement(block);
    });
    return div;
  }
  // user 消息保持纯文本（安全）
  return document.createTextNode(content);
}
</script>
```

**注意：** 只对 assistant 消息做 Markdown 渲染，user 消息保持纯文本（XSS 安全）。

**验收标准：**
```
1. "## 标题" 显示为二级标题
2. 代码块有背景色和语法高亮
3. 列表有正确缩进和符号
4. 表格正确渲染
5. 连接可点击
```

---

### UX-3：回复等待状态指示 — P1

**参考产品：** ChatGPT 的闪烁光标、Cursor 的 "thinking..." 动画

**现状：** 点击 Send 后，输入框无任何反馈。网络慢时用户反复点击发送，导致重复提交。

**方案：**

```javascript
// Web UI 改进
function send() {
  var btn = document.getElementById('btnSend');
  var input = document.getElementById('input');
  
  btn.disabled = true;
  input.disabled = true;
  btn.textContent = '...';
  
  // 添加 "Claw 正在思考..." 占位气泡
  addPlaceholderBubble('assistant', [
    { text: '🧠 思考中', dots: true },
  ]);
  
  api('/api/sessions/' + cur + '/messages', {method:'POST', ...})
    .then(function(r){
      removePlaceholder();
      addMessage('assistant', r.reply);
    })
    .catch(function(e){
      removePlaceholder();
      addMessage('assistant', '❌ ' + e.message);
    })
    .finally(function(){
      btn.disabled = false;
      input.disabled = false;
      btn.textContent = 'Send';
      input.focus();
    });
}
```

**交互流程：**
1. 用户点击 Send → 按钮变为 `...` 禁用状态
2. 对话区出现灰色占位气泡 `🧠 Claw 正在思考...`
3. 回复到达 → 占位气泡替换为实际回复
4. 恢复输入框、按钮状态

---

### UX-4：Tool Call 可视化卡片 — P1

**参考产品：** Claude Code（灰色 tool call 行）、ChatGPT 的 code interpreter 展示

**现状：** Tool call 和 tool result 只在 CLI 用彩色 ANSI 打印，Web UI 完全不显示任何 tool 执行过程。用户不知道模型在做什么。

**方案：**

```html
<!-- Tool Call 卡片样式 -->
<style>
.tool-card {
  background: #f5f5f5;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 10px 14px;
  margin: 8px 0;
  font-size: 13px;
  align-self: flex-start;
  max-width: 85%;
}
.tool-card .tool-name {
  font-weight: 600;
  color: #1976d2;
}
.tool-card .tool-args {
  font-family: monospace;
  color: #666;
  margin-top: 4px;
  white-space: pre-wrap;
  word-break: break-all;
}
.tool-card .tool-result {
  margin-top: 6px;
  padding: 8px;
  background: #f0faf0;
  border-radius: 4px;
  color: #2e7d32;
  white-space: pre-wrap;
  max-height: 200px;
  overflow-y: auto;
}
.tool-card .tool-error {
  background: #fef0f0;
  color: #c62828;
}
</style>
```

**展示效果：**
```
┌──────────────────────────────────┐
│ 🔧 current_time                  │  ← tool name
│ {}                               │  ← args（可折叠）
│ ─────────────────────────────── │
│ 2026-07-08 18:30:00              │  ← result（绿色背景）
└──────────────────────────────────┘
```

---

### UX-5：Session 搜索与过滤 — P2

**参考产品：** ChatGPT（搜索所有对话）

**现状：** 验收时已有 22 个 session，侧边栏滚动列表难以找到特定会话，没有搜索功能。

**方案：**

```html
<!-- 侧边栏增加搜索框 -->
<div style="padding: 8px; border-bottom: 1px solid #eee;">
  <input id="session-search" type="text" 
         placeholder="🔍 搜索 session..." 
         style="width:100%;padding:8px;border:1px solid #ddd;border-radius:8px;">
</div>

<script>
document.getElementById('session-search').addEventListener('input', function(e) {
  var q = e.target.value.toLowerCase();
  document.querySelectorAll('.si').forEach(function(el) {
    var title = el.querySelector('.title').textContent.toLowerCase();
    var id = el.getAttribute('data-id').toLowerCase();
    el.style.display = (title.includes(q) || id.includes(q)) ? 'block' : 'none';
  });
});
</script>
```

---

### UX-6：工具调用差异对比视图（Diff View）— P2

**参考产品：** Cursor 的 diff 编辑器、GitHub Copilot 的建议预览

**场景：** 当模型使用 `edit_file` 修改文件时，用户需要看到具体改了哪些内容。

**方案：**

```
在 approval 卡片中增加 Diff 对比：
┌──────────────────────────────────────┐
│  ✏️ 编辑文件: src/main.py           │
│                                      │
│  ┌─ 旧内容 ──┐  ┌─ 新内容 ──┐       │
│  │ print(x)  │  │ print(f"x={x}") │  │
│  └───────────┘  └────────────┘       │
│                                      │
│  [✅ 批准]  [❌ 拒绝]  说明: ______  │
└──────────────────────────────────────┘
```

后端可以生成统一 diff：
```python
import difflib

def make_diff(old_text: str, new_text: str) -> str:
    return '\n'.join(difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(),
        lineterm='', n=3,
    ))
```

---

### UX-7：键盘快捷键体系 — P2

**参考产品：** Claude Code（`/` 命令体系）、Cursor（`Cmd+K`、`Cmd+L`）

**现状：** 所有操作依赖鼠标点击或输入完整命令。

**方案：**

| 快捷键 | 功能 |
|:-------|:-----|
| `Enter` | 发送消息 |
| `Shift+Enter` | 换行 |
| `Ctrl+N` | 新建 session |
| `Ctrl+Shift+,` | 上一个 session |
| `Ctrl+Shift+.` | 下一个 session |
| `Ctrl+Delete` | 删除当前 session |
| `Ctrl+R` | 重命名当前 session |
| `Escape` | 取消/关闭弹窗 |
| `Ctrl+K` | 打开命令面板（搜索所有功能） |

命令面板（Command Palette）是 Cursor 最受欢迎的功能之一——按 `Ctrl+K` 弹出搜索框，可以搜索所有可用操作。

---

### UX-8：暗色模式 — P2

**参考产品：** 几乎所有现代开发工具

**现状：** Web UI 只有亮色主题，在终端/IDE 环境中夜间使用刺眼。

**方案：**

```css
/* CSS 变量 + 媒体查询 */
:root {
  --bg: #ffffff;
  --text: #333333;
  --sidebar-bg: #ffffff;
  --bubble-user: #1976d2;
  --bubble-assistant: #ffffff;
  --border: #e0e0e0;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1a1a2e;
    --text: #e0e0e0;
    --sidebar-bg: #16213e;
    --bubble-user: #0d47a1;
    --bubble-assistant: #1e1e3f;
    --border: #2a2a4a;
  }
}

body {
  background: var(--bg);
  color: var(--text);
}
```

额外提供手动切换按钮（🌙/☀️），记忆用户偏好到 localStorage。

---

### UX-9：消息编辑与重发 — P2

**参考产品：** ChatGPT（消息上的编辑按钮）、Claude（编辑并重新发送）

**现状：** 发错消息或想微调提问，只能重新输入全部内容。

**方案：**

```html
<!-- 用户消息悬浮时显示编辑按钮 -->
<div class="msg user" data-msg-id="...">
  <div class="msg-content">原始消息</div>
  <div class="msg-actions" style="display:none;">
    <button class="btn-edit">✏️ 编辑</button>
    <button class="btn-retry">🔄 重新生成</button>
  </div>
</div>
```

编辑流程：
1. 点击 ✏️ → 消息变为可编辑文本框
2. 修改后按 Enter → 删除该消息之后的所有历史
3. 重新发送新消息 → 模型基于新输入重新回答

---

### UX-10：会话上下文可视化和 Token 计数 — P2

**参考产品：** Claude Code（上下文窗口可视化）、ChatGPT（模型信息栏）

**现状：** 用户完全不知道当前 session 占用了多少上下文、何时会被压缩。

**方案：**

```
侧边栏底部或 header 增加上下文仪表盘：

  [████████████░░░░░░░░░░] 42% used
  当前: ~8,500 tokens / 窗口: 128K
  
  session summary: ✅ 已压缩 (3轮前)
  memory: 2 条活跃
  tool calls: 12 次
```

这能让用户直观理解上下文管理，并在需要时手动触发 `/compact`。

---

### UX-11：定时任务完成通知 — P2

**参考产品：** macOS 通知中心、系统 toast

**现状：** Scheduler 执行任务后只在 CLI print 日志，Web UI 用户完全不知道任务已完成。

**方案：**

```javascript
// Web UI 轮询或 SSE 监听任务状态
function pollTasks() {
  setInterval(function() {
    api('/api/tasks').then(function(tasks) {
      tasks.forEach(function(t) {
        if (t.status === 'completed' && !notified(t.task_id)) {
          showToast('✅ 任务完成: ' + t.content.slice(0, 40));
          markNotified(t.task_id);
        }
      });
    });
  }, 5000);
}

function showToast(msg) {
  var toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(function() { toast.remove(); }, 4000);
}
```

**适用场景：**
- 定时任务执行完成 → Toast 提示
- 需要用户审批 → Toast + 侧边栏小红点
- 压缩事件发生 → 小字提示
- 任务执行失败 → 红色 Toast 警示

---

### UX-12：首次使用引导（Onboarding）— P2

**参考产品：** Cursor（首次启动的欢迎页）、Claude Code（/help）

**现状：** 新用户打开 Web UI 看到空白页面，不知道能做什么。

**方案：**

首次启动时（session 列表为空），展示欢迎卡片：

```html
<div class="welcome">
  <h2>👋 欢迎使用 SJTUClaw！</h2>
  <p>SJTUClaw 是一个 AI Agent Runtime，可以帮你：</p>
  <div class="quick-actions">
    <button onclick="newSession()">💬 开始对话</button>
    <button onclick="loadExample()">📖 查看示例</button>
    <button onclick="showHelp()">📚 查看命令手册</button>
  </div>
  <div class="tips">
    <h3>💡 快速上手</h3>
    <ul>
      <li><code>/skill list</code> — 查看可用技能</li>
      <li><code>/workspace set &lt;path&gt;</code> — 设置工作目录</li>
      <li><code>/task new "提醒我" +30m</code> — 创建定时任务</li>
    </ul>
  </div>
</div>
```

---

### UX-13：消息气泡内交互元素 — P1

**参考产品：** Claude Code 的确认按钮、ChatGPT 的复制/引用

**现状：** 用户无法对消息做任何操作（复制、引用、评价）。

**方案：**

每条 assistant 消息悬浮时显示操作工具栏：

```html
<div class="msg-toolbar">
  <button title="复制">📋</button>
  <button title="重新生成">🔄</button>
  <button title="有用">👍</button>
  <button title="无用">👎</button>
  <button title="引用回复">💬</button>
</div>
```

其中"引用回复"功能允许用户选中某条 assistant 回复的一部分，作为上下文继续提问——这是 ChatGPT 非常受欢迎的功能。

---

### UX-14：会话快照与导出 — P2

**参考产品：** ChatGPT（分享链接）、Claude（公开链接）

**现状：** 用户无法导出、分享或保存对话内容。

**方案：**

```javascript
// 导出当前 session 为 Markdown
function exportSession(sessionId) {
  api('/api/sessions/' + sessionId).then(function(s) {
    var md = '# ' + s.title + '\n\n';
    s.messages.forEach(function(m) {
      var role = m.role === 'user' ? '**你**' : '**Claw**';
      md += '### ' + role + '\n' + m.content + '\n\n';
    });
    downloadFile(md, sessionId + '.md', 'text/markdown');
  });
}
```

**导出格式支持：**
| 格式 | 用途 |
|:-----|:------|
| Markdown | 可读、易分享、可直接提交为课程报告 |
| JSON | 完整数据（含 tool call 细节），可用于调试 |
| 纯文本 | 轻量复制粘贴 |

---

### UX-15：命令菜单 / 斜杠命令联想 — P1

**参考产品：** Claude Code（斜杠命令体系）、Cursor（Cmd+K 命令面板）

**现状：** 用户需要记忆 `/session`、`/memory`、`/skill`、`/task`、`/workspace`、`/approve`、`/compact` 等全部命令，输入错误时只显示"未知命令"。

**方案：**

```javascript
// 输入框输入 / 时弹出命令联想菜单
var COMMANDS = [
  { cmd: '/session new', desc: '创建新会话' },
  { cmd: '/session list', desc: '列出所有会话' },
  { cmd: '/session switch', desc: '切换会话' },
  { cmd: '/session rename', desc: '重命名会话' },
  { cmd: '/session delete', desc: '删除会话' },
  { cmd: '/memory add', desc: '添加长期记忆' },
  { cmd: '/memory list', desc: '查看记忆列表' },
  { cmd: '/memory delete', desc: '删除记忆' },
  { cmd: '/skill list', desc: '查看可用技能' },
  { cmd: '/skill', desc: '调用技能' },
  { cmd: '/task new', desc: '创建定时任务' },
  { cmd: '/task list', desc: '查看任务列表' },
  { cmd: '/task cancel', desc: '取消任务' },
  { cmd: '/workspace set', desc: '设置工作目录' },
  { cmd: '/compact', desc: '手动压缩上下文' },
  { cmd: '/exit', desc: '退出程序' },
];

document.getElementById('input').addEventListener('input', function(e) {
  var val = e.target.value;
  if (val.startsWith('/')) {
    showCommandMenu(val);
  } else {
    hideCommandMenu();
  }
});
```

**交互效果：**
```
> /s                   ┌──────────────────────┐
  [📁 /session new    创建新会话           ]  ← 上下选择
  [📁 /session list   列出所有会话          ]
  [📁 /session switch 切换会话              ]
  [📁 /session rename 重命名会话            ]
  [📁 /session delete 删除会话              ]
  [📋 /skill list     查看可用技能          ]
  [📋 /skill          调用技能              ]
                       └──────────────────────┘
```

---

### UX 优化总结

| 编号 | 优化项 | 参考产品 | 优先级 | 工作量 |
|:----:|:-------|:---------|:------:|:-----:|
| UX-1 | 流式输出（SSE） | ChatGPT, Claude Code | P1 | 3d |
| UX-2 | Markdown 渲染 + 代码高亮 | ChatGPT, Cursor | P1 | 0.5d |
| UX-3 | 等待状态指示 | ChatGPT, Cursor | P1 | 0.5d |
| UX-4 | Tool Call 可视化卡片 | Claude Code | P1 | 1d |
| UX-13 | 消息气泡交互（复制/重新生成） | ChatGPT, Claude | P1 | 1d |
| UX-15 | 命令菜单/斜杠联想 | Claude Code, Cursor | P1 | 1d |
| UX-5 | Session 搜索过滤 | ChatGPT | P2 | 0.5d |
| UX-6 | Diff 对比视图 | Cursor | P2 | 2d |
| UX-7 | 键盘快捷键 | Claude Code, Cursor | P2 | 1d |
| UX-8 | 暗色模式 | 所有现代工具 | P2 | 0.5d |
| UX-9 | 消息编辑与重发 | ChatGPT, Claude | P2 | 1d |
| UX-10 | 上下文可视化 + Token 计数 | Claude Code | P2 | 1d |
| UX-11 | 任务完成通知 | macOS/Web 通知 | P2 | 0.5d |
| UX-12 | 首次使用引导 | Cursor, Claude Code | P2 | 0.5d |
| UX-14 | 会话导出 | ChatGPT, Claude | P2 | 0.5d |

**快速 wins（1 天内可完成）：**
- UX-2 Markdown 渲染 ← 只需加一个 CDN 脚本
- UX-3 等待状态指示 ← 纯前端改动
- UX-8 暗色模式 ← CSS 变量 + 媒体查询
- UX-12 首次使用引导 ← 纯 HTML 模板

---

## 四、优先级 P2：增强优化

### P2-1：添加单元测试

**现状：** `tests/` 目录完全为空。

**建议测试覆盖：**

| 测试文件 | 测试内容 |
|:---------|:---------|
| `tests/test_session_store.py` | create/load/save/delete session、文件损坏恢复、并发安全 |
| `tests/test_compactor.py` | snip_compact 裁切逻辑、micro_compact 占位符替换、compact_history LLM 摘要 |
| `tests/test_tool_registry.py` | tool 注册/查找/执行、未知 tool 错误、参数校验 |
| `tests/test_agent.py` | process_message loop、tool_call 循环、max_tool_rounds 上限 |
| `tests/test_memory_store.py` | add/list/delete memory、自动提取、去重 |
| `tests/test_workspace.py` | safe_resolve 路径逃逸防护、文件 CRUD、approval 流程 |

```python
# tests/test_session_store.py 示例

import pytest
from src.session_store import create_session, load_session, delete_session, list_sessions

def test_create_and_load():
    s = create_session("test")
    assert s.session_id.startswith("session_")
    assert s.title == "test"
    
    loaded = load_session(s.session_id)
    assert loaded is not None
    assert loaded.session_id == s.session_id
    
    delete_session(s.session_id)
    assert load_session(s.session_id) is None

def test_corrupted_file_handling():
    """损坏的 JSON 文件不应导致程序崩溃"""
    sessions = list_sessions()
    # 不应抛出异常
    assert isinstance(sessions, list)
```

---

### P2-2：统一错误处理

**现状：**
- CLI：`print(f"[错误] ...", file=sys.stderr)`
- Gateway：`self._json({"error": "..."}, 4xx)`
- Agent loop：`print(f"  \033[33m[tool_call] ...\033[0m")`
- 格式不统一，Gateway 错误有时包含 `[API Error]` 前缀有时没有

**方案：**

```python
# src/exceptions.py 新增

class ClawError(Exception):
    """所有 claw 异常的基类"""
    code: int = 500
    message: str = ""
    
class ConfigError(ClawError): ...
class ApiKeyMissingError(ConfigError): ...
class NetworkError(ClawError): ...
class SessionError(ClawError): ...
class ToolExecutionError(ClawError): ...
class WorkspaceError(ClawError): ...
class ApprovalTimeoutError(ClawError): ...
```

Gateway 统一响应格式：
```json
{"ok": false, "error": {"code": 401, "message": "API KEY 认证失败", "detail": "..."}}
```

CLI 统一前缀：
```
[ERROR]   — 不可恢复错误
[WARN]    — 可恢复警告
[INFO]    — 普通信息
[TOOL]    — tool 调用
[SYSTEM]  — 系统事件（压缩、调度等）
```

---

### P2-3：Session 数据损坏自动恢复

**现状：** session JSON 文件损坏时只打印警告，session 不可用。

**方案：**

```python
# session_store.py 新增

MAX_BACKUP_COPIES = 3

def _backup_session(path: Path) -> None:
    """保存 session 文件的历史备份"""
    backup_dir = SESSIONS_DIR / ".backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, backup_dir / f"{path.stem}_{timestamp}.json")
    # 清理旧备份
    backups = sorted(backup_dir.glob(f"{path.stem}_*.json"))
    for old in backups[:-MAX_BACKUP_COPIES]:
        old.unlink()

def recover_session(session_id: str):
    """尝试从备份恢复损坏的 session"""
    backup_dir = SESSIONS_DIR / ".backups"
    backups = sorted(backup_dir.glob(f"{session_id}_*.json"))
    if not backups:
        return None
    latest = backups[-1]
    try:
        data = json.loads(latest.read_text())
        return Session.from_dict(data)
    except:
        return None
```

---

### P2-4：安全清理

| 项目 | 操作 |
|:-----|:-----|
| `.env` 中的真实 API KEY | 替换为 `sk-your-key-here`，确保 `.gitignore` 包含 `.env` |
| `data/locks/` 中的过时锁文件 | 清理 `session_005.lock` 等遗留文件 |
| `data/sessions/` 中的测试 session | 保留或归档 20+ 个 session |
| `.transcripts/` 压缩备份 | 增补 `.gitignore` 规则 |

---

## 五、Web UI 状态总览（目标态）

```
┌──────────────────────────────────────────────────────────┐
│  Sidebar (280px)              │  Main Area               │
│  ┌──────────────────────┐     │  ┌────────────────────┐  │
│  │  [Chat] [Skills] [Tasks] │  │  │  Messages Area     │  │
│  │──────────────────────────│  │  │                    │  │
│  │  session_001  5 msgs     │  │  │  [user] 你好...    │  │
│  │  session_002  2 msgs  ✎✖ │  │  │  [assistant] 喵～  │  │
│  │  session_003  0 msgs  ✎✖ │  │  │  [tool_call] ...  │  │
│  │                          │  │  │  [approval] 批准？ │  │
│  │  [+ New Session]         │  │  │  [✅/❌]          │  │
│  └──────────────────────┘     │  ├────────────────────┤  │
│  Workspace: /home/...        │  │  Input + Send       │  │
│  [Change] [Clear]            │  │  [/skill ... ] hint │  │
└──────────────────────────────────────────────────────────┘
```

## 六、CLI vs Web 命令对照（目标态）

| 功能 | CLI 命令 | Web UI | 当前状态 |
|:-----|:---------|:-------|:--------:|
| 新建 session | `/session new` | +New Session 按钮 | ✅ 已有 |
| 切换 session | `/session switch <id>` | 点击列表项 | ✅ 已有 |
| 重命名 session | `/session rename [id] <title>` | 悬浮✏️ → 弹窗 | ✅ 已有 |
| 删除 session | `/session delete <id>` | 悬浮✖ → 确认 | ✅ 已有 |
| 发送消息 | 直接输入 | 输入框 + Send | ✅ 已有 |
| 添加记忆 | `/memory add <content>` | （暂不实现） | ❌ 未规划 |
| 定时任务 | `/task new <content> <time>` | Tasks 标签页创建 | ⏳ P1-3 |
| 设置 workspace | `/workspace set <path>` | 侧边栏底部输入 | ⏳ P1-3 |
| 技能调用 | `/skill <name> <task>` | Skills 标签页选择 | ⏳ P1-3 |
| 审批操作 | `/approve /reject <id>` | 审批弹窗卡片 | ⏳ P1-1 |
| 文件下载 | — | 下载按钮/链接 | ⏳ P0-1 |

## 七、实施路线图

| 阶段 | 内容 | 预估工作量 | 优先级 |
|:-----|:------|:----------:|:------:|
| **Phase 1** | P0-1 create_download + P0-2 copy_attachment | 2 天 | 🔴 最高 |
| **Phase 2** | P1-1 Approval Web UI + P1-2 micro_compact 修复 | 2 天 | 🟠 高 |
| **Phase 3** | P1-3 Web UI Skill/Task/Workspace + UX-1/2/3/4/13/15 | 5 天 | 🟡 中 |
| **Phase 4** | P2-1 单元测试 + UX-5/7/8/11/12/14 | 3 天 | 🟢 低 |
| **Phase 5** | P2-2/3 统一错误处理/自动恢复 + UX-6/9/10 | 3 天 | 🟢 低 |

**UX 快速 wins（可穿插在任何阶段，建议 Phase 3 前排期）：**
| 项 | 时间 | 理由 |
|:---|:----|:------|
| UX-2 Markdown 渲染 | 0.5d | 大幅提升可读性，一行 CDN 脚本 |
| UX-3 等待状态指示 | 0.5d | 消除等待焦虑，防重复提交 |
| UX-8 暗色模式 | 0.5d | CSS 变量 + 媒体查询 |
| UX-12 首次引导 | 0.5d | 降低新用户门槛 |

---

## 八、技术债务

- [x] `.env` 中包含真实 API KEY → 替换为占位值（已确认 `.gitignore` 包含 `.env`）
- [ ] `Flask` 空文件应删除（`assets/` 目录下的遗留文件）
- [ ] Gateway 当前使用 `http.server`（零依赖），保持这一选择
- [ ] `tool_registry.py` 中 tool handler 参数统一校验（当前直接 `handler(**arguments)`，没有 JSON Schema 校验）
- [ ] Scheduler Engine 没有停止钩子，程序退出时后台线程可能无法正常清理
- [ ] session 列表返回按 mtime 排序，但 `list_sessions` 默认降序（最新在前），需确认这是期望行为

---

*计划制定日期：2026-07-08 · 基于 REVIEW.md 验收报告*

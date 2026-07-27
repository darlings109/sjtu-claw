# S06：Gateway 与图形化操作入口

## 概述

引入 Gateway（HTTP 服务层），使 CLI 之外的用户可以通过**网页浏览器**与 claw 交互。Gateway 接收 HTTP 请求、路由 session、调用已有 agent runtime，返回结果。所有对话逻辑、上下文管理、tool 调用、compaction 都复用同一套引擎。

## 对应 TASK.md 要求

- [x] Gateway Server（基于 Python 内置 `http.server`）
- [x] REST API（健康检查、session CRUD、消息发送、附件上传）
- [x] SSE 流式输出端点
- [x] Web UI（单页应用，原生 JS + CSS）
- [x] Session 管理（列表/创建/切换/重命名/删除）
- [x] 附件上传与 session 隔离
- [x] Agent runtime 完整复用（不绕过 context builder / session store / tool registry）

## 关键文件

| 文件 | 职责 |
|:-----|:-----|
| [web/server.py](../src/web/server.py) | HTTP Gateway + REST API + SSE 端点 + 静态文件服务 |
| [web/static/index.html](../src/web/static/index.html) | 单页 Web UI（~600 行 JS+CSS，纯原生） |
| [main.py](../src/main.py) (最后几行) | `gateway` 参数解析，启动 Gateway |
| [agent.py](../src/agent.py) (`_run_agent_stream`, `process_and_compact`) | 流式和非流式 agent loop |

## 架构设计 / 实现路径

### Gateway 架构

```
浏览器 (Web UI)
    │  HTTP/SSE
    ▼
┌──────────────────────────┐
│  Gateway (http.server)    │
│  ┌────────────────────┐   │
│  │  GatewayHandler     │   │
│  │  ┌──────────────┐   │   │
│  │  │ GET /api/*   │   │   │
│  │  │ POST /api/*  │   │   │
│  │  │ DELETE /api/*│   │   │
│  │  │ SSE streams  │   │   │
│  │  └──────┬───────┘   │   │
│  └─────────┼───────────┘   │
└────────────┼──────────────┘
             │
             ▼
      ┌──────────────┐
      │  agent.py     │
      │  process_and  │
      │  _compact()   │  ← 与 CLI 完全同一套
      └──────────────┘
```

### REST API 总览

| 端点 | 方法 | 功能 |
|:-----|:----:|:-----|
| `/api/health` | GET | 健康检查 |
| `/api/sessions` | GET | 列出 session |
| `/api/sessions` | POST | 创建 session |
| `/api/sessions/<id>` | GET | 获取 session 详情 + 历史 |
| `/api/sessions/<id>` | DELETE | 删除 session |
| `/api/sessions/<id>/rename` | POST | 重命名 session |
| `/api/sessions/<id>/messages` | POST | 发送消息（非流式） |
| `/api/sessions/<id>/messages/stream` | POST | SSE 流式输出 |
| `/api/sessions/<id>/attachments` | POST/GET | 上传/列出附件 |
| `/api/sessions/<id>/attachments/<file>` | DELETE | 删除附件 |
| `/api/skills` | GET/POST/DELETE | 技能管理 |
| `/api/skills/<name>/content` | GET | 技能详情 |
| `/api/skills/<name>/run` | POST | 调用技能 |
| `/api/tasks` | GET/POST | 定时任务 |
| `/api/tasks/<id>` | GET/DELETE | 任务详情/取消 |
| `/api/approvals` | GET | 待审批列表 |
| `/api/approvals/<id>/approve\|reject` | POST | 审批操作 |
| `/api/workspace` | GET/POST/DELETE | 工作区管理 |
| `/api/downloads/<id>` | GET | 文件下载 |

### 技术选型

**为什么不使用 Flask/FastAPI？**
- 课程要求零依赖（纯 Python 标准库）
- `http.server.SimpleHTTPRequestHandler` + `ThreadingHTTPServer` 足以满足需求
- 静态文件服务、路由匹配、JSON 解析全部手写，保持代码轻量

**前端为什么使用原生 JS + CSS？**
- 零框架依赖，单文件部署
- 打包在 `index.html` 中，随 Gateway 一起启动
- 600 行代码覆盖全部功能：暗色模式、Markdown 渲染、SSE 流式、技能管理面板

### 附件上传与 Session 隔离

```
data/
└── attachments/
    └── <session_id>/
        └── <filename_uuid8.ext>   # 保留原始文件名 + UUID 防重
```

- 每个 session 拥有独立的附件目录
- API 侧：上传时绑定 session_id，列出时只返回当前 session 的附件
- 前端侧：切换 session 时附件列表自动切换

### 流式输出 SSE

Gateway 支持 SSE（Server-Sent Events）流式输出，前端逐 token 渲染：

```
POST /api/sessions/<id>/messages/stream
→ response: text/event-stream

事件流：
data: {"type": "token", "content": "正"}
data: {"type": "token", "content": "在"}
data: {"type": "token", "content": "思"}
data: {"type": "token", "content": "考"}
data: {"type": "tool_call", "name": "read_file", "arguments": {...}}
data: {"type": "tool_result", "name": "read_file", "result": "..."}
data: {"type": "text_done", "content": "最终回复"}
data: {"type": "done"}
```

```javascript
// 前端消费 SSE
const xhr = new XMLHttpRequest();
xhr.onprogress = () => {
    const lines = xhr.responseText.split('\n');
    for (const line of lines) {
        if (line.startsWith('data: ')) {
            const event = JSON.parse(line.slice(6));
            switch (event.type) {
                case 'token': appendText(event.content); break;
                case 'tool_call': showToolCall(event.name, event.arguments); break;
                case 'done': finalize(); break;
            }
        }
    }
};
```

## 核心代码解析

### GatewayHandler — 路由分发

```python
class GatewayHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/health':       return self._json({"status": "ok"})
        if path == '/api/sessions':     return self._json(sessions_list)
        if path.startswith('/api/sessions/'): ...
        if path == '/':                 path = '/index.html'
        return super().do_GET()         # fallback：静态文件

    def do_POST(self):
        ...
        if '/messages/stream' in path:
            # SSE 流式
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            for event in _run_agent_stream(_config, session, content):
                self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
            return

        if '/messages' in path:
            reply = process_and_compact(_config, session, content)
            return self._json({"reply": reply})
```

### 附件内容传递到 LLM

```python
# POST /api/sessions/<id>/messages 中
if attachments:
    for fname in attachments:
        fcontent = _read_attachment_content(sid, fname)
        file_bodies.append(f"--- {fname} ---\n{fcontent}")
    # 拼入 user message 前缀
    content = prefix + "\n\n" + content_text
reply = process_and_compact(_config, session, content)
```

## 优化方向

1. **前端代码拆分**：当前 `index.html` 单文件 600 行已显臃肿，可拆为 JS/CSS 独立文件
2. **SSE 重连机制**：网络中断时前端自动重连
3. **移动端适配**：当前响应式布局基础，可进一步优化触摸交互
4. **WebSocket**：SSE 仅服务端→客户端，如需双向实时通信可升级为 WebSocket
5. **文件预览**：当前文本文件可内联预览，图片/PDF 可增加预览支持

## 可能的问题

- `http.server` 是开发级服务器，不适合高并发生产环境。当前使用 `ThreadingHTTPServer` 每个请求一个线程，可应对少量并发
- SSE 端点长时间连接时，如果 agent loop 卡住或超时，前端可能一直等待。`chat_completion_stream()` 中有 timeout 控制
- 前端 `XMLHttpRequest` 处理 SSE 时，`onprogress` 可能触发频繁，已做 10ms 节流
- API Key 安全：前端不保存 API Key，所有请求通过 Gateway 代理，符合安全要求

## 关联文档

- TASK.md §Step 6（含 §6.6 实现要点）
- [产品验收报告 — Step 6 评分 (5/5)](/learn-sjtu-claw/assets/REVIEW.md)
- [SPEC.md — 方向一：文件传输系统优化 > 方向二：界面美化 > 方向三：HTTPS 支持 > 方向四：桌宠](/learn-sjtu-claw/assets/SPEC.md)

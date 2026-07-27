# S08：Workspace / Advanced Tool / Approval

## 概述

让 claw 从"只能观察环境"升级为"可以在用户指定的项目中执行真实操作"。引入三个核心概念：

- **Workspace**：agent 可以操作的项目目录，作为所有文件操作的边界
- **Advanced Tool**：写文件、执行 shell、创建下载入口等高级能力
- **Approval**：执行改动环境的操作前先让用户显式确认

## 对应 TASK.md 要求

- [x] Workspace 设置/查看/清除（`/workspace set/clear`）
- [x] 路径安全解析 `safe_resolve()` — 禁止 `../` 或绝对路径逃逸
- [x] Update Tool：`create_file`、`overwrite_file`、`edit_file`
- [x] Shell Tool：`new_shell`、`run_command`
- [x] Download Tool：`create_download` — 创建临时下载入口
- [x] `copy_attachment_to_workspace` — 附件拷贝到 workspace
- [x] Approval 机制：执行前创建 approval，等待用户 `/approve` / `/reject`
- [x] Approval 超时（120 秒）自动视为拒绝
- [x] Tool result 和 approval result 都进入 session 历史

## 关键文件

| 文件 | 职责 |
|:-----|:-----|
| [workspace.py](../src/workspace.py) | Workspace 管理 + `safe_resolve` + shell + approval + download |
| [tool_registry.py](../src/tool_registry.py) (advanced handlers) | 6 个 advanced tool 注册与 handler |
| [main.py](../src/main.py) (`handle_workspace_command`) | CLI `/workspace` `/approve` `/reject` 命令 |
| [web/server.py](../src/web/server.py) | Approval/Workspace/Download API 路由 |

## 架构设计 / 实现路径

### 三层 Tool 体系

| 层级 | Tool | 需审批 | 说明 |
|:-----|:-----|:------:|:-----|
| 只读 (Step 5) | `current_time`, `list_dir`, `read_file`, `glob` | ❌ | 无环境改动 |
| Update (Step 8) | `create_file`, `overwrite_file`, `edit_file` | ✅ | 写文件 |
| Shell (Step 8) | `new_shell`, `run_command` | ✅ | 执行命令 |
| Download (Step 8) | `create_download`, `copy_attachment_to_workspace` | ❌ | 文件传输 |

### Workspace 工作机制

```python
_workspace: Optional[Path] = None  # 全局 workspace（进程中唯一）

def set_workspace(s):
    p = Path(s).resolve()
    p.mkdir(parents=True, exist_ok=True)
    _workspace = p

def safe_resolve(s: str) -> Optional[Path]:
    """路径安全解析：确保目标路径在 workspace 内"""
    ws = get_workspace()
    if ws is None: return None
    p = (ws / s).resolve()        # 拼接 + 解析
    try:
        p.relative_to(ws)         # 必须在 workspace 内
        return p
    except ValueError:
        return None               # 逃逸 → 返回 None
```

所有文件操作（读写、shell、download）都经过 `safe_resolve()`，如果路径在 workspace 外则拒绝执行。

### Approval 机制

```
模型请求 update tool 或 shell tool
    │
    ▼
create_approval(tool_name, args)
  → 生成 app_xxxxxxxx 的 approval ID
  → 创建 threading.Event
  → 打印 [approval] 通知用户
    │
    ▼
wait_approval(aid, timeout=120)
  │                          ← 用户输入 /approve app_xxx 或 /reject app_xxx
  │                             (Gateway 上通过 POST /api/approvals/xxx/approve)
  │
  ├── 批准 → execute tool → tool result → session
  │
  └── 拒绝 → "Operation rejected" → session
      │
      └── 超时 → 自动视为拒绝
```

### Approval 数据流（Gateway + CLI）

```
CLI 交互：
    用户输入 → main.py handle_workspace_command()
    ├── /approve app_xxx → 设置 Event → 继续
    └── /reject app_xxx → 设置 Event → 跳过执行

Gateway Web UI 交互：
    前端轮询 /api/approvals → 展示审批卡片
    用户点击"批准" → POST /api/approvals/app_xxx/approve
    用户点击"拒绝" → POST /api/approvals/app_xxx/reject
```

### Shell 管理

```python
_shell: Optional[subprocess.Popen] = None  # 单 shell 实例

def new_shell():
    """启动新 shell（旧 shell 自动终止）"""
    if _shell: _shell.terminate()
    _shell = subprocess.Popen(["bash"], stdin=PIPE, stdout=PIPE, stderr=PIPE, cwd=workspace)

def run_command(cmd: str) -> str:
    """在已有 shell 中执行命令"""
    _shell.stdin.write(cmd + "\n")
    out, err = _shell.communicate(timeout=30)
    return (out + err).strip()[:50000]
```

### Download Tool

```python
_downloads: Dict[str, Path] = {}

def create_download(path: str) -> str:
    download_id = f"dl_{uuid.uuid4().hex[:12]}"
    _downloads[download_id] = safe_resolve(path)  # 注册为可下载
    return f"Download created: /api/downloads/{download_id}"
```

Gateway 上：

```python
if path.startswith('/api/downloads/'):
    file_path = get_download_path(dl_id)
    # 读取文件 → 传输给用户
```

## 核心代码解析

### Advanced Tool Handler 统一模式

```python
def handle_create_file(path, content):
    ws = get_workspace()
    if ws is None: return "Error: Workspace not set."

    aid = create_approval("create_file", {"path": path, "content_length": len(content)})
    print(f"[approval] {aid}: create file {path}?")

    if wait_approval(aid, 120):   # 用户批准
        cleanup_approval(aid)
        return create_file(path, content)  # 🔴 真实写文件
    else:                          # 拒绝或超时
        cleanup_approval(aid)
        return "Operation rejected by user."
```

### Tool Registry 中的注册

```python
r.register(
    name="create_file",
    description="在 workspace 内创建新文件。需要 approval。",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对 workspace）"},
            "content": {"type": "string", "description": "文件内容"},
        },
        "required": ["path", "content"],
    },
    handler=handle_create_file,  # ← 不走 approval 的 handler
)
```

## 优化方向

1. **Approval 前预览 diff**：edit_file 操作批准前向用户展示 diff 预览，帮助决策
2. **Workspace 路径自动补全**：CLI 中 `set` 命令支持 Tab 补全
3. **Shell 工作目录追踪**：当前 shell 初始 cwd 为 workspace，但后续 `cd` 可能离开 workspace。当前做法是每次执行后检查 cwd。可进一步限制 cd 范围
4. **Sandbox 加强**：当前路径保护基于 `safe_resolve`，可加白名单/黑名单模式
5. **Approval 历史**：当前 approval 清理后丢失，可保留审批日志供审计

## 可能的问题

- **Approval 与流式输出的冲突**：SSE 端点中 tool call 到 approval 时，前端需要暂停流式渲染，等待用户操作。当前 Web UI 的 SSE 端点中 approval 以工具调用的方式展示
- **Shell 竞争条件**：`_shell` 是全局单例。如果两轮 tool call 之间用户在其他地方手动关闭了 shell，`run_command` 会返回错误
- **Shell 超时**：`communicate(timeout=30)` 30 秒超时，长命令可能被截断。超时后 `_shell` 被设为 None，后续命令需要重新 `new_shell`
- **Download 入口的生命周期**：当前 `_downloads` 字典无过期时间，临时下载入口会一直存在

## 关联文档

- TASK.md §Step 8（含 §8.7 实现要点）
- [产品验收报告 — Step 8 评分 (2/5, 部分实现)](/learn-sjtu-claw/assets/REVIEW.md)

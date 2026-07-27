# S02：多 Session 管理与持久化

## 概述

从 Step 1 的单会话（内存）升级为**多会话 + 持久化**系统。支持创建/列出/切换/重命名/删除 session，每个 session 拥有独立的历史消息，程序重启后可以恢复。

## 对应 TASK.md 要求

- [x] 多个 session，独立历史
- [x] 创建 `(/session new)`、列出 `(/session list)`、切换 `(/session switch <id>)`、重命名 `(/session rename)`、删除 `(/session delete)`
- [x] Session 持久化到本地 JSON 文件
- [x] 引入 Context Builder 雏形，负责将 session 数据组装为 LLM 输入

## 关键文件

| 文件 | 职责 |
|:-----|:-----|
| [session_store.py](../src/session_store.py) | Session 数据模型 + JSON 持久化 + 线程安全 + 自动备份恢复 |
| [context_builder.py](../src/context_builder.py) | 组装发送给 LLM 的 messages |
| [main.py](../src/main.py) (handle_session_command) | CLI `/session` 命令处理 |

## 架构设计 / 实现路径

### Session 数据模型

```python
class Session:
    session_id: str      # "session_001"
    title: str           # "新会话"
    messages: List[Dict] # [{"role": "user", "content": "..."}, ...]
    summary: str         # compaction 摘要（Step 4 加入）
    created_at: str      # ISO 时间戳
    updated_at: str      # ISO 时间戳
```

### 持久化策略

```
session 存储：
  data/sessions/
  ├── session_001.json   # 每个 session 一个 JSON 文件
  ├── session_002.json
  └── .backups/          # 自动备份目录
      ├── session_001_20260720_120000.json
      └── session_001_20260720_130000.json
```

- 每个 session 一个独立 JSON 文件，而非所有 session 写进一个大文件
- 文件结构 = Session 类 `to_dict()` 序列化
- 备份保留最近 3 份，文件损坏时自动从备份恢复

### 线程安全

```python
_sess_locks: Dict[str, threading.RLock] = {}  # 每个 session 独立锁

def _get_sess_lock(session_id) -> threading.RLock:
    """获取 session 级锁，支持可重入"""
```

- 每个 session 使用独立的 `RLock`（可重入锁），而非全局锁
- 允许 Gateway 的并发请求对不同 session 同时读写
- `append_message()` 实现为原子操作：加锁 → 读取 → 修改 → 写入 → 释放

### Context Builder 雏形

```python
def build_context(session):
    messages = []
    messages.append({"role": "system", "content": full_prompt})  # system prompt
    if session.summary:                                           # 摘要
        messages.append({"role": "system", "content": session.summary})
    messages.extend(session.messages)                            # 历史消息
    return messages
```

职责边界：Session 负责保存历史，Context Builder 负责把历史组织成 LLM 输入。存储结构（含 `title`, `created_at`）≠ 模型输入结构（只发 messages）。

## 核心代码解析

### Session CRUD 实现

```python
def create_session(title=""):
    # 从已有 session 中取最大编号 → +1
    existing = list_sessions()
    next_num = max(...) + 1 if ids else 1
    session_id = f"session_{next_num:03d}"
    session = Session(session_id=session_id, title=title or "新会话")
    save_session(session)
    return session
```

### 文件损坏自动恢复

```python
def load_session(session_id):
    try:
        data = json.loads(open(path).read())
        return Session.from_dict(data)
    except (json.JSONDecodeError, KeyError):
        # 文件损坏 → 尝试从备份恢复
        return recover_session(session_id)

def recover_session(session_id):
    backups = sorted(BACKUP_DIR.glob(f"{session_id}_*.json"))
    for backup in reversed(backups):  # 最新的备份优先
        try: return Session.from_dict(json.loads(backup.read_text()))
        except: continue
    return None  # 所有备份都损坏
```

### CLI 命令处理

```python
User> /session new               → create_session(), 自动切换到新 session
User> /session list              → list_sessions(), 打印表格（* 标记当前）
User> /session switch session_02 → load_session("session_02"), 切换上下文
User> /session rename 新标题      → 重命名当前 session
User> /session delete session_03 → delete_session("session_03"), 不能删除当前
```

## 优化方向

1. **Session 分页**：当 session 数量超过几十个时，list 命令输出过长，可加入分页
2. **搜索过滤**：按 title 或日期范围搜索 session（Web UI 已实现搜索框）
3. **批量操作**：批量删除过期 session
4. **消息级别的持久化增量**：当前每次请求都完整写入整个 JSON，数据量大时效率低

## 可能的问题

- `list_sessions()` 遍历目录时，非 `.json` 文件或目录会导致异常，已做过滤
- 大量并发请求场景下（多个 Gateway worker），文件级锁可能成为瓶颈。当前单进程 + 线程锁足够
- 备份文件本身没有备份，备份损坏时只能恢复最后一次正常保存

## 关联文档

- TASK.md §Step 2
- [中期报告 — 模块划分](../learn-sjtu-claw/assets/REPORT.md)

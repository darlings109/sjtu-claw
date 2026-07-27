# S07：Scheduler 与定时任务

## 概述

引入 Scheduler（定时任务引擎），使 claw 能够在未来某个时间点（一次性）或按固定间隔（周期性）自动执行任务。Scheduler 不是新的 agent，它只负责"什么时候触发"，真正的工作仍由已有 agent loop 完成。

## 对应 TASK.md 要求

- [x] Scheduler 后台引擎（线程循环，每 10 秒检查一次）
- [x] 一次性任务 + 周期性任务
- [x] 时间解析：绝对时间（`22:00`）、相对时间（`+30m`）、间隔（`1h`、`1d`）
- [x] 任务 CRUD：创建 `(/task new)`、列表、取消 `(/task cancel)`、详情 `(/task show)`
- [x] 任务持久化到 `data/tasks/`，重启不丢
- [x] 执行历史记录（每次执行的结果或错误）
- [x] 通过已有 `process_and_compact` 执行，复用完整 runtime
- [x] 任务结果写回对应 session
- [x] 程序关闭期间的错过的触发不补执行
- [x] 周期性任务执行完成后自动计算下一次触发时间

## 关键文件

| 文件 | 职责 |
|:-----|:-----|
| [scheduler.py](../src/scheduler.py) | 任务 CRUD + `SchedulerEngine` 后台线程 |
| [main.py](../src/main.py) (`handle_task_command`, `SchedulerEngine.start()`) | CLI `/task` 命令 + 启动 scheduler |
| [agent.py](../src/agent.py) | `process_and_compact()` 由 scheduler 调用 |
| [web/server.py](../src/web/server.py) | 任务 API 路由：`/api/tasks` GET/POST/DELETE |

## 架构设计 / 实现路径

### Scheduler 架构

```
┌──────────────────────────────────────┐
│           SchedulerEngine            │
│                                      │
│  _run_loop()  ← daemon thread        │
│  │                                   │
│  ├── 每 10 秒 _check_tasks()         │
│  │                                   │
│  │  对于每个 pending 任务：            │
│  │  ├── trigger_at ≤ now?            │
│  │  │   → _execute_task()            │
│  │  │       ├── 标记 running          │
│  │  │       ├── load_session(sid)    │
│  │  │       ├── agent_func(config,   │
│  │  │       │    session, content)   │
│  │  │       ├── 记录 history          │
│  │  │       ├── 计算 next trigger    │
│  │  │       └── 更新 status          │
│  │  └── 未到期 → 跳过                │
│  └───────────────────────────────────│
└──────────────────────────────────────┘
```

### 定时任务数据模型

```json
{
    "task_id": "task_001",
    "content": "提醒我写实验报告",
    "session_id": "session_002",
    "trigger_at": "2026-07-20T14:00:00+00:00",       // UTC 存储
    "trigger_at_local": "2026-07-20T22:00:00+08:00",  // 原始时间（带时区）
    "timezone": "Asia/Shanghai",
    "repeat_rule": "1d",                    // 空=一次性，"30m"/"1h"/"1d"=周期
    "status": "pending",                     // pending | running | completed | cancelled | failed
    "repeat_count": 0,
    "history": [
        {"time": "2026-07-20T14:00:00", "content": "...", "reply": "已完成..."},
        {"time": "2026-07-21T14:00:00", "content": "...", "reply": "..."}
    ],
    "created_at": "...",
    "updated_at": "..."
}
```

### 时区设计

所有任务时间使用 **UTC** 存储，展示时转换到本地时区（Asia/Shanghai）：

```python
UTC_TZ = timezone.utc
LOCAL_TZ = timezone(timedelta(hours=8))

def _now_utc():    → datetime.now(UTC_TZ).isoformat()
def _to_utc(dt):  → 本地时间 → UTC
def _to_local(dt):→ UTC 时间 → 本地
```

用户输入视为本地时间，存储时转 UTC，检查时统一用 UTC 比较。

### 时间解析

```python
"+30m"  → 当前本地时间 + 30 分钟
"1h"    → 当前本地时间 + 1 小时
"22:00" → 当天 22:00（若已过则次日）
"2026-07-20 10:00" → 指定日期时间
```

### 周期性任务执行流程

```
1. 任务到期 → 标记 running
2. 调用 agent_func(config, session, content)
3. 记录执行结果到 history
4. 如果 repeat_rule 非空：
   a. 计算下一触发时间：当前时间 + 间隔
   b. 更新 trigger_at → 标记 pending（继续等待）
   c. 如果计算失败 → 标记 completed
5. 如果一次性 → 标记 completed
```

## 核心代码解析

### SchedulerEngine — 后台循环

```python
class SchedulerEngine:
    def start(self):
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        while self._running:
            self._check_tasks()
            time.sleep(10)  # 每 10 秒检查

    def _check_tasks(self):
        now_utc = datetime.now(UTC_TZ)
        for task in list_tasks():
            if task["status"] != "pending": continue
            trigger = datetime.fromisoformat(task["trigger_at"])
            if trigger > now_utc: continue
            self._execute_task(task)  # 到期执行
```

### 任务内容 → agent loop

```python
def _execute_task(self, task):
    session = load_session(task["session_id"])
    reply = self._agent_func(self._config, session, task["content"])
    #   ^^ 这里调用的是 process_and_compact，复用全部能力
    task["history"].append({"time": _now(), "content": task["content"], "reply": reply[:500]})

    if task.get("repeat_rule"):
        next_time = _next_trigger(...)  # 计算下一触发时间
        task["trigger_at"] = next_time
        task["status"] = "pending"      # 等待下次触发
    else:
        task["status"] = "completed"
```

## 优化方向

1. **Cron 表达式支持**：当前只支持固定间隔（`30m`、`1h`、`1d`），可扩展为完整 cron
2. **错过触发补执行**：当前程序关闭期间错过的触发不补执行，可增加补执行策略
3. **任务执行超时**：当前无 timeout 控制，长时间卡住的任务会阻塞 scheduler 线程
4. **任务依赖**：可支持任务链（任务 A 完成后触发任务 B）
5. **Web UI 整合**：后端 API 已实现但前端任务面板尚在开发中

## 可能的问题

- **时区锚定**：所有时间存储为 UTC 但时区信息固定在代码中（`Asia/Shanghai`），未从 `.env` 读取。如果用户在其他时区，需要修改代码
- **执行时间过长**：如果任务执行时间超过检查间隔（10s），可能造成多个重复触发（`_execute_task` 会将状态改为 `running`，后续检查会跳过）
- **线程安全**：`SchedulerEngine` 的后台线程与 Gateway 线程共享 session store，依赖 session 级的 `RLock` 保证线程安全。任务执行中如果用户同时操作同一 session，可能看到不一致的中间状态

## 关联文档

- TASK.md §Step 7（含 §7.6 实现要点）
- [产品验收报告 — Step 7 评分 (5/5)](/learn-sjtu-claw/assets/REVIEW.md)

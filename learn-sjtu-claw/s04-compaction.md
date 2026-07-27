# S04：上下文压缩 Compaction

## 概述

随着对话轮数增长，session messages 不断累积，可能导致请求超长、变慢甚至超过模型上下文限制。Compaction 实现了**三级压缩管线**：便宜的（零 API）先跑，贵的（LLM 摘要）后跑，确保上下文可控。

## 对应 TASK.md 要求

- [x] L1: `snip_compact()` — 消息数 > 50 时裁中间（0 API）
- [x] L2: `micro_compact()` — 旧 tool_result 替换为占位符（0 API）
- [x] L3: `compact_history()` — LLM 全量摘要（1 API）
- [x] 压缩前备份 transcript（JSONL 格式到 `.transcripts/`）
- [x] 应急压缩 `reactive_compact()` — L3 失败时的 fallback
- [x] 保护边界：不拆开 tool_use/tool_result 对
- [x] 失败安全：LLM 压缩失败不删除原始消息
- [x] 手动触发：`/compact` 命令
- [x] 自动触发：字符数 > 80KB 时自动运行 L3

## 关键文件

| 文件 | 职责 |
|:-----|:-----|
| [compactor.py](../src/compactor.py) | 三级管线 + transcript + reactive fallback |
| [agent.py](../src/agent.py) (`process_and_compact`, `compact_now`) | 自动/手动压缩编排 |
| [main.py](../src/main.py) (`/compact`) | CLI `/compact` 命令 |
| [.transcripts/](../.transcripts/) | 压缩前完整对话备份（JSONL） |

## 架构设计 / 实现路径

### 三级压缩管线

```
L1: snip_compact          # 零 API，快速裁剪冗余对话
    条件：消息数 > 50
    策略：保留头 3 条 + 尾 47 条，中间裁掉
    保护：不拆开 tool_use→tool_result 的配对

L2: micro_compact         # 零 API，压缩工具结果
    条件：tool_result 条数 > 3
    策略：只保留最近 3 条完整 tool_result，更早的替换为占位符

L3: compact_history       # 1 次 API，LLM 摘要
    条件：字符数 > 80KB（should_compact 判断）
    策略：旧消息 → LLM 生成摘要 → 保留最近 4 轮原始消息
    备份：压缩前先写 transcript
```

管线执行顺序：**L1 → L2 → potential L3**。L1 和 L2 保证 0 API 成本清理大部分冗余，只在极端长对话时才跑 L3。

### 压缩流程图

```
消息进入 → run_pipeline(messages)
    │
    ├── snip_compact()       # 消息数 > 50？裁中间
    │
    ├── micro_compact()      # tool_result > 3？旧的变占位符
    │
    └── should_compact()     # > 80KB？触发 LLM 摘要
         │
         ├── 成功 → summary 更新，保留最近 4 轮
         │
         └── 失败 → reactive_compact()（保留最近 5 条）
                      │
                      └── 再次失败 → 保留原始消息，不丢失
```

### Session 结构扩展

```python
class Session:
    ...
    summary: str = ""  # ← 新增：压缩生成的摘要
```

压缩后的上下文变为：

```
发送给 LLM 的 messages 结构：
1. system prompt（稳定）
2. soul（稳定）
3. memory（稳定）
4. session summary（压缩摘要，如果有）
5. recent session messages（最近 4 轮原始消息）
```

### 保护边界

压缩时最重要的规则：**不能把 `assistant(tool_use)` 和后面的 `user(tool_result)` 拆到不同区域**

```python
# snip_compact 中的保护逻辑
if _message_has_tool_use(messages[head_end - 1]):
    # 头部的最后一条是 tool_use → 把 tool_result 一起保留
    while _is_tool_result_message(messages[head_end]):
        head_end += 1

if _is_tool_result_message(messages[tail_start]):
    # 尾部的第一条是 tool_result → 把 tool_use 一起保留
    tail_start -= 1
```

### 压缩前备份 Transcript

```python
def write_transcript(messages):
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    path = TRANSCRIPT_DIR / f"transcript_{timestamp}.jsonl"
    with path.open("w") as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    return str(path)
```

## 核心代码解析

### `run_pipeline()` — 管线编排

```python
def run_pipeline(messages):
    messages = snip_compact(messages)    # L1
    messages = micro_compact(messages)   # L2
    return messages                      # L3 在外部由 should_compact 决定
```

### `process_and_compact()` — 自动压缩编排

```python
def process_and_compact(config, session, user_content):
    reply = process_message(config, session, user_content)  # 先正常对话

    # 管线预处理（L1 + L2）
    session.messages = run_pipeline(session.messages)

    # L3：达到阈值 → LLM 摘要
    if should_compact(session.messages):  # > 80KB
        try:
            new_summary, old_count, recent_count = compact_history(
                config, session.messages, existing_summary=session.summary)
            session.summary = new_summary
            session.messages = _collect_recent(session.messages, KEEP_RECENT_ROUNDS)
            save_session(session)
        except Exception:
            # Fallback: reactive_compact（更激进：保留最后 5 条）
            try:
                reactive_compact(...)
            except Exception:
                # 双重失败 → 保留原始消息，只报错不删除
                print("[警告] 压缩失败，原始消息已保留")
    return reply
```

## 优化方向

1. **Token 感知压缩**：当前使用字符数（80KB）作为阈值，改用 token 计数更精确
2. **预算层（Budget Layer）**：参考 LCC s08，tool_result 超过阈值时落盘到 `.task_outputs/`，只留预览。当前未实现
3. **增量摘要**：当前全量摘要，可以改为增量式——只对新消息做摘要，合并已有 summary
4. **用户可配置阈值**：将 `COMPACT_THRESHOLD_CHARS`、`KEEP_RECENT_ROUNDS` 等常数暴露为配置项
5. **多轮对话中 summary 质量**：多次 compact 后 summary 可能丢失细节，可加入用户反馈机制

## 可能的问题

- **摘要内容丢失**：多次压缩后，早期对话的细节完全丢失。transcript 备份提供了回溯能力，但不自动恢复
- **L3 失败不阻塞**：压缩失败时保留原始消息，但不会自动重试。需用户手动 `/compact` 或等下次对话触发
- **小模型压缩质量**：使用 qwen2.5-7b 等小模型时，摘要质量可能不如大模型，导致压缩后丢失关键上下文
- **内存占用**：`.transcripts/` 目录会持续增长，需要定期清理策略

## 关联文档

- TASK.md §Step 4（含 §4.10 多层压缩管线、§4.11 transcript + reactive compact、§4.12 system prompt 分段化）
- [产品验收报告 — Step 4 评分 (9/10)](/learn-sjtu-claw/assets/REVIEW.md)

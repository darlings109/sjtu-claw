# S01：多轮对话 Loop

## 概述

在 Step 0 的最小 LLM 调用基础上，实现一个持续运行的 CLI 对话循环（loop），使程序能够记住当前运行期间的多轮对话历史，并将完整上下文发送给 LLM。

## 对应 TASK.md 要求

- [x] 持续读取用户输入，进入对话 loop
- [x] 每轮携带当前 session 的所有历史消息
- [x] 将 user 和 assistant 消息追加到 session
- [x] 核心对话逻辑从 CLI 中拆出
- [x] 支持 `/exit` 退出

## 关键文件

| 文件 | 职责 |
|:-----|:-----|
| [main.py](../src/main.py) (main 函数) | CLI 入口、命令分发、`while True` 对话 loop |
| [agent.py](../src/agent.py) | `process_message()` 封装核心对话逻辑 |
| [llm_client.py](../src/llm_client.py) | Chat Completions API 调用 |
| [session_store.py](../src/session_store.py) | Session 数据结构（内存版） |

## 架构设计 / 实现路径

### CLI Loop 与 Agent Loop 的分离

```
main.py (CLI loop)
    │
    ├── 交互层：input() → 命令识别 → 分发
    │   ├── /exit /session /memory /workspace /skill /task /compact
    │   └── 普通消息 → 交给 agent
    │
    └── agent.py (agent loop)
        │
        └── process_message()
            ├── 追加 user message → session
            ├── build_context(session)
            ├── chat_completion(config, messages)
            ├── 追加 assistant reply → session
            ├── tool call 循环（Step 5 加入）
            └── save_session(session)
```

关键设计决策：
- **CLI 只负责输入输出**：`main.py` 的 `input()`/`print()` 不关心模型调用的细节
- **Agent 只负责对话逻辑**：`agent.py` 不关心用户是在终端还是网页输入的
- **分隔就是为后续 Gateway 复用做准备**：后续 Step 6 的 Gateway 只需调用 `process_message()` 或 `process_and_compact()` 即可复用全部能力

### 核心对话流程（Step 1 时）

```
1. 用户输入 → agent.process_message(config, session, user_input)
2. 追加 user message → session.messages
3. build_context(session) → 构造 messages 列表
4. chat_completion(config, messages) → 调用 LLM
5. 追加 assistant reply → session.messages
6. save_session(session)
7. 返回 reply 给 CLI 打印
```

## 核心代码解析

### `main()` 的对话 Loop

```python
while True:
    user_input = input(f"{session.session_id}> ").strip()
    # 退出
    if user_input == "/exit": break
    # 命令分发（session / memory / workspace / task / skill / compact）
    if re.match(r"^/sess", user_input): ...
    if re.match(r"^/mem", user_input): ...
    # 普通消息 → agent loop
    reply = process_and_compact(config, session, user_input)
    print(f"Assistant> {reply}")
```

### `process_message()` 的单轮处理

```python
def process_message(config, session, user_content):
    session.messages.append({"role": "user", "content": user_content})
    messages = build_context(session)
    content, raw, tool_calls = chat_completion(config, messages)
    session.messages.append({"role": "assistant", "content": content})
    save_session(session)
    return content
```

## 优化方向

1. **流式输出**：当前 CLI 等完整 response 才打印，长回复体验差。可以改为逐 token 输出（后续 Step 已实现 SSE 流式）
2. **消息格式化**：用户输入的多行文本、代码块等可在终端中更好展示
3. **命令补全**：输入 `/` 后 Tab 补全或提示可用命令（Web UI 已实现斜杠命令联想）

## 可能的问题

- `input()` 在 stdin 关闭（如管道输入）时抛出 `EOFError`，已用 try/except 处理
- 单条消息过长时 LLM 请求可能超时（后续 compaction 会缓解）
- CLI 中中文输入在 WSL 终端中可能显示异常

## 关联文档

- TASK.md §Step 1

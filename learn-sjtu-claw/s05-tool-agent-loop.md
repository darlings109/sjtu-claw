# S05：只读 Tool 与 Agent Loop

## 概述

为 claw 加入只读 tool，使其能够主动读取外部环境（当前时间、目录内容、文件内容），并将 tool 执行结果反馈回 agent loop。claw 从"只能聊天的模型调用程序"升级为**能够观察外部环境的最小 agent**。

## 对应 TASK.md 要求

- [x] 统一 Tool 数据结构（tool definition + tool handler）
- [x] Tool Registry 全局注册表（注册、查找、执行）
- [x] 至少 3 个只读 tool：`current_time`、`list_dir`、`read_file`
- [x] 模型通过原生 function calling 协议发起 tool call
- [x] Agent loop 改造：LLM → tool → LLM → tool → ... → final
- [x] Tool result 加入 session messages，作为模型继续推理的上下文
- [x] 最多 10 轮 tool call，防止死循环
- [x] 额外的只读 tool：`glob`（glob 模式匹配文件）

## 关键文件

| 文件 | 职责 |
|:-----|:-----|
| [tool_registry.py](../src/tool_registry.py) | `ToolRegistry` 单例 + 10 个 tool 定义 + handler |
| [agent.py](../src/agent.py) (`process_message`) | Agent loop：LLM ↔ tool 循环 |
| [llm_client.py](../src/llm_client.py) | Function calling 支持（tool_calls 解析） |
| [context_builder.py](../src/context_builder.py) | 加入 tool definitions 到 API 调用 |

## 架构设计 / 实现路径

### Tool 数据结构

```python
# OpenAI 原生 function calling 格式
{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "读取文本文件的内容。...",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "..."},
                "limit": {"type": "integer", "description": "..."}
            },
            "required": ["path"]
        }
    }
}
```

### Tool Registry

```python
class ToolRegistry:
    """全局工具注册中心"""
    _tools: Dict[str, ToolDef]      # tool definition（给 API 用）
    _handlers: Dict[str, Callable]  # tool handler（真正执行）

    def register(name, description, input_schema, handler):
        """注册一个 tool"""

    def get_definitions() -> List[ToolDef]:
        """获取所有 tool definition（发 API 用）"""

    def execute(name, arguments) -> str:
        """执行指定 tool，返回文本结果"""
```

### 只读 Tool 清单

| Tool | Handler | 功能 | 参数 |
|:-----|:--------|:-----|:-----|
| `current_time` | `current_time()` | 获取当前日期和时间 | 无参 |
| `list_dir` | `list_dir(path)` | 列出目录内容 | `path`（可选，默认 `.`） |
| `read_file` | `read_file(path, limit)` | 读取文本文件 | `path`（必填），`limit`（可选） |
| `glob` | `glob_files(pattern)` | 按模式匹配文件路径 | `pattern`（必填，支持 `**`） |

### Agent Loop 改造

```
改造前（Step 1-4）：
    用户输入 → buildContext → callLLM → 保存 assistant 回复 → 返回

改造后（Step 5+）：
    用户输入 → buildContext → callLLM
        ├── 模型返回 final（无 tool_call）→ 保存回复 → 返回
        └── 模型返回 tool_call(s) → 执行 tool(s) → 结果追加到 session
            → 再次 buildContext → 再次 callLLM
            → 重复直到 final 或 max_tool_rounds(10)
```

### `chat_completion()` 的 tool_calls 解析

```python
def chat_completion(config, messages, tools=None):
    ...
    tool_calls = []
    for tc in raw_tool_calls:
        tool_calls.append({
            "id": tc["id"],
            "name": tc["function"]["name"],
            "arguments": json.loads(tc["function"]["arguments"]),
        })
    return content, data, tool_calls  # 三元组
```

## 核心代码解析

### Agent Loop 核心循环

```python
def process_message(config, session, user_content):
    session.messages.append({"role": "user", "content": user_content})

    max_tool_rounds = 10
    tool_rounds = 0

    while tool_rounds < max_tool_rounds:
        tool_rounds += 1
        messages = build_context(session)
        tools_defs = get_registry().get_definitions()

        content, raw, tool_calls = chat_completion(
            config, messages, tools=tools_defs if tools_defs else None)

        session.messages.append({"role": "assistant", "content": content})

        if not tool_calls:  # 没有 tool_call → 最终回复
            return content

        # 执行 tool call(s)
        for tc in tool_calls:
            result = get_registry().execute(tc["name"], tc["arguments"])
            session.messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

    # 超出最大轮次 → 强制返回最后的回复
    return final_reply
```

### Tool Handler 示例

```python
def current_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def list_dir(path=".") -> str:
    items = os.listdir(path)
    lines = []
    for name in sorted(items):
        full = os.path.join(path, name)
        if os.path.isdir(full):
            lines.append(f"{name}/")
        else:
            lines.append(f"{name}  ({os.path.getsize(full)} bytes)")
    return "\n".join(lines)

def read_file(path, limit=None) -> str:
    text = Path(path).read_text(encoding="utf-8")
    if limit and len(text) > limit:
        text = text[:limit] + f"\n... (truncated, {len(text)} total chars)"
    return text
```

## 优化方向

1. **tool result 超长截断**：大文件读取结果可能撑爆上下文，已实现 `limit` 参数，可进一步做自动截断
2. **并行 tool 执行**：模型一次请求中可能含多个 tool_call，当前串行执行，可改为并行
3. **Tool 调用统计**：记录每个 tool 被调用的次数、时长、失败率，用于调试
4. **Tool 参数校验**：当前参数校验依赖 handler 内部 try/except，可以使用 JSON Schema 校验库

## 可能的问题

- **Tool call 死循环**：某些模型可能反复调用同一个 tool 不输出 final。10 轮上限是硬保护，但达到上限时最后回复可能为空
- **Tool 返回的假阳性**：模型有时即使读了文件内容，仍可能"幻觉"出不存在的信息
- **安全风险**：`read_file` 和 `list_dir` 没有路径沙箱，可读取任意路径（Step 8 通过 workspace 机制解决）

## 关联文档

- TASK.md §Step 5（含 §5.12 实现要点）
- [产品验收报告 — Step 5 评分 (10/10)](/learn-sjtu-claw/assets/REVIEW.md)

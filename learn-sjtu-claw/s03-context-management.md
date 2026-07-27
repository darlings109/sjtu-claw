# S03：System Prompt / Memory / Soul

## 概述

引入三类稳定上下文，将其与普通对话历史分离：**System Prompt**（运行规则）、**Soul**（身份风格）、**Memory**（长期记忆）。三者均为稳定上下文（stable context），不随 session 切换而变化，不受 compaction 影响。

## 对应 TASK.md 要求

- [x] system prompt 从代码中拆出，改为独立配置文件加载
- [x] soul 独立配置，描述稳定身份和交互风格
- [x] Memory Store：跨 session 持久化，支持 `/memory add / list / delete`
- [x] 稳定上下文与对话上下文的边界划分
- [x] 自动记忆提取（每轮对话后 LLM 判断提取）
- [x] 记忆整理合并（≥10 条时自动合并）

## 关键文件

| 文件 | 职责 |
|:-----|:-----|
| [configs/system_prompt.txt](../configs/system_prompt.txt) | 系统规则（从代码中独立） |
| [configs/soul.txt](../configs/soul.txt) | 身份风格（如"永雏塔菲"风格） |
| [prompt_loader.py](../src/prompt_loader.py) | 分段加载 + `assemble_prompt()` 组装 |
| [memory_store.py](../src/memory_store.py) | 记忆 CRUD + 自动提取 `extract_memories()` + 整理 `consolidate_memories()` |
| [context_builder.py](../src/context_builder.py) | 将所有 stable context 加入 system message |
| [main.py](../src/main.py) (handle_memory_command) | CLI `/memory` 命令处理 |

## 架构设计 / 实现路径

### 三种上下文的职责边界

| 类型 | 生命周期 | 更新方式 | 用途 |
|:-----|:---------|:---------|:-----|
| **System Prompt** | 永久（文件决定） | 编辑文件 | 系统规则、行为边界、安全约束 |
| **Soul** | 永久（文件决定） | 编辑文件 | 身份风格、语气、交互方式 |
| **Memory** | 跨 session | `/memory add` / 自动提取 | 用户偏好、长期事实、项目背景 |
| **Session Messages** | 当前 session | 对话追加 | 临时对话历史和任务进度 |

### Prompt Loader 分段设计

```
assemble_prompt()
    │
    ├── _section_identity()   → 始终加载（system_prompt.txt）
    ├── _section_soul()       → 始终加载（soul.txt）
    └── _section_memory()     → 按需加载（memory 非空时）
```

逐段拼接，每段职责清晰。context_builder 只需调用一次 `assemble_prompt()`，不再关心内部结构。

### Memory Store 架构

```
data/memories/
├── mem_001.json   # {"memory_id":"mem_001","content":"...","source":"manual","created_at":"..."}
├── mem_002.json
└── mem_003.json
```

支持两种写入方式：
1. **手动**：`/memory add <content>` → `source="manual"`
2. **自动**：`extract_memories()` → 每轮对话后自动分析最近 10 条消息 → `source="auto"`

### 自动提取机制

每轮 `process_message()` 执行完毕后自动调用 `extract_memories()`：

```
1. 收集最近 10 条消息的文本
2. 构造 prompt 发给 LLM："从这段对话中提取用户的偏好、约束或项目事实"
3. 与已有记忆对比，避免重复提取
4. 符合条件的自动写入 data/memories/
```

### 整理合并机制

当记忆数量 ≥ 10 条时，`consolidate_memories()` 自动触发：

```
1. 将所有记忆发送给 LLM
2. LLM 合并重复内容、删除过时或矛盾内容
3. 删除所有旧记忆，写入整理后的新记忆
4. 保留用户偏好的优先级最高
```

## 核心代码解析

### `assemble_prompt()` 的三段组装

```python
def _section_identity() -> str:
    """始终加载：基本行为约束"""
    return SYSTEM_PROMPT_FILE.read_text()  # 从文件读取

def _section_soul() -> str:
    """始终加载：身份风格"""
    return SOUL_FILE.read_text()

def _section_memory() -> str:
    """按需加载：仅当有长期记忆时"""
    memories = get_all_memory_texts()
    if not memories: return ""
    items = "\n".join(f"- {m}" for m in memories)
    return f"长期记忆（请尊重）：\n{items}"

def assemble_prompt() -> str:
    segments = []
    if identity := _section_identity(): segments.append(identity)
    if soul := _section_soul():      segments.append(f"[风格] {soul}")
    if memory := _section_memory():  segments.append(memory)
    return "\n\n".join(segments)
```

### `extract_memories()` 的 LLM 自动提取

```python
def extract_memories(config, messages):
    # 1. 收集最近消息文本
    dialogue = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in messages[-10:])

    # 2. LLM 判断（输出 JSON 数组）
    prompt = "从对话中提取用户的偏好、约束或项目事实。返回 JSON 数组..."
    result, _, _ = chat_completion(config, [{"role": "user", "content": prompt}])

    # 3. 解析 LLM 输出的 JSON
    match = re.search(r"\[.*\]", result, re.DOTALL)
    items = json.loads(match.group())

    # 4. 逐条写入
    for item in items:
        add_memory(content.strip(), source="auto")
```

## 优化方向

1. **记忆优先级排序**：当前自动提取和手动添加记忆权重相同，可以给手动添加更高优先级
2. **记忆过期的显式管理**：当前只有合并时被动删除过时内容，可增加超时自动过期
3. **Soul 的动态选择**：可支持用户切换不同 soul（如"工作模式/休闲模式"）
4. **Memory 的 session 关联**：当前 memory 全局可见，可扩展为支持 session 级记忆

## 可能的问题

- `extract_memories()` 调用 LLM 会增加额外 token 消耗，但作为每轮后的异步操作，不影响主流程
- `consolidate_memories()` 调用 LLM 后删除所有旧记忆重写，如果 LLM 输出格式错误会导致记忆丢失（有 try/except 保护，但无备份）
- Memory 文件数量较多时，`list_memories()` 遍历目录的性能会下降

## 关联文档

- TASK.md §Step 3（含 §3.8 自动记忆提取）
- [产品验收报告 — Step 3 评分](/learn-sjtu-claw/assets/REVIEW.md)

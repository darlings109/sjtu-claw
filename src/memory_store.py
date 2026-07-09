"""Memory Store — 跨 session 的长期记忆存储

支持手动管理和 LLM 自动提取。
每个 memory 保存为 data/memories/<memoryId>.json。
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.config import ROOT_DIR, LLMConfig

MEMORIES_DIR = ROOT_DIR / "data" / "memories"

# 自动整理的阈值
CONSOLIDATE_THRESHOLD = 10


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_dir() -> None:
    MEMORIES_DIR.mkdir(parents=True, exist_ok=True)


def _next_id() -> str:
    existing = list_memories()
    ids = []
    for m in existing:
        mid = m.get("memory_id", "")
        if mid.startswith("mem_"):
            try:
                ids.append(int(mid.split("_")[1]))
            except ValueError:
                pass
    next_num = max(ids) + 1 if ids else 1
    return f"mem_{next_num:03d}"


# ============================================================
# CRUD
# ============================================================

def list_memories() -> List[Dict]:
    """列出所有 memory，按创建时间降序"""
    _ensure_dir()
    memories = []
    for f in sorted(MEMORIES_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.suffix == ".json":
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                memories.append(data)
            except (json.JSONDecodeError, OSError):
                pass
    return memories


def add_memory(content: str, source: str = "manual") -> str:
    """添加一条 memory

    Args:
        content: 记忆内容
        source: "manual"（手动）或 "auto"（自动提取）

    Returns:
        memory_id
    """
    _ensure_dir()
    memory_id = _next_id()
    data = {
        "memory_id": memory_id,
        "content": content,
        "source": source,
        "created_at": _now(),
    }
    path = MEMORIES_DIR / f"{memory_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return memory_id


def delete_memory(memory_id: str) -> bool:
    """删除指定 memory"""
    path = MEMORIES_DIR / f"{memory_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


def get_all_memory_texts() -> List[str]:
    """获取所有 memory 的内容文本列表"""
    return [m["content"] for m in list_memories()]


# ============================================================
# 自动提取（s09 风格）
# ============================================================

def extract_memories(config: LLMConfig, messages: List[Dict]) -> int:
    """从最近对话中自动提取新的记忆

    在每轮 agent loop 结束后调用。读取最近几轮对话，
    用 LLM 判断是否有值得长期保留的信息。

    Args:
        config: LLM 配置
        messages: 当前 session 的完整的消息列表

    Returns:
        新增记忆的数量
    """
    # 收集最近的对话文本（取 last 10 条）
    dialogue_parts = []
    for msg in messages[-10:]:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, list):
            texts = []
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    texts.append(b.get("content", ""))
            content = "\n".join(texts)
        if isinstance(content, str) and content.strip():
            dialogue_parts.append(f"{role}: {content[:500]}")
    dialogue = "\n".join(dialogue_parts)

    if not dialogue.strip():
        return 0

    # 获取已有记忆，避免重复提取
    existing = list_memories()
    existing_desc = "\n".join(
        f"- {m['memory_id']}: {m['content'][:80]}"
        for m in existing
    ) if existing else "(无)"

    prompt = (
        "从这段对话中提取用户的偏好、约束或项目相关的重要事实。\n"
        "如果发现值得长期保留的信息，返回 JSON 数组，每项包含 content 字段。\n"
        "如果已有记忆已涵盖，或对话中没有值得长期保留的，返回 []。\n\n"
        "判断标准：\n"
        "- 用户明确表达的个人偏好或习惯\n"
        "- 对项目决策有持续影响的约束或约定\n"
        "- 需要跨 session 保留的长期任务背景\n"
        "- 不要保存寒暄、临时任务或已过期信息\n\n"
        f"已有记忆：\n{existing_desc}\n\n"
        f"对话：\n{dialogue[:4000]}"
    )

    try:
        from src.llm_client import chat_completion
        result, _, _ = chat_completion(config, [{"role": "user", "content": prompt}])
        result = result.strip()
    except Exception:
        return 0

    # 提取 JSON
    match = re.search(r"\[.*\]", result, re.DOTALL)
    if not match:
        return 0

    try:
        items = json.loads(match.group())
    except (json.JSONDecodeError, TypeError):
        return 0

    if not items or not isinstance(items, list):
        return 0

    count = 0
    for item in items:
        content = item.get("content", "") if isinstance(item, dict) else str(item)
        if content and len(content) > 5:
            add_memory(content.strip(), source="auto")
            count += 1

    if count:
        print(f"[memory] 自动提取 {count} 条新记忆")

    return count


def consolidate_memories() -> int:
    """整理合并重复或过时的记忆

    当记忆数量 ≥ CONSOLIDATE_THRESHOLD 时自动触发。
    """
    memories = list_memories()
    if len(memories) < CONSOLIDATE_THRESHOLD:
        return 0

    catalog = "\n\n".join(
        f"## {m['memory_id']}\n{m['content']}"
        for m in memories
    )

    prompt = (
        "以下是当前保存的所有记忆。请检查是否有重复、过时或互相矛盾的内容。\n"
        "要求：\n"
        "1. 合并重复内容\n"
        "2. 删除过时或矛盾的内容\n"
        "3. 保留重要的用户偏好\n"
        "返回 JSON 字符串数组，如 [\"合并后的记忆1\", \"合并后的记忆2\"]\n\n"
        f"{catalog[:12000]}"
    )

    try:
        from src.llm_client import chat_completion
        from src.config import load_config
        cfg = load_config()
        result, _, _ = chat_completion(cfg, [{"role": "user", "content": prompt}])
        result = result.strip()
    except Exception:
        return 0

    match = re.search(r"\[.*\]", result, re.DOTALL)
    if not match:
        return 0

    try:
        items = json.loads(match.group())
    except (json.JSONDecodeError, TypeError):
        return 0

    if not items or not isinstance(items, list):
        return 0

    # 删除全部旧记忆
    for m in memories:
        delete_memory(m["memory_id"])

    # 写入整理后的新记忆
    for item in items:
        content = item if isinstance(item, str) else item.get("content", "")
        if content and len(content) > 5:
            add_memory(content, source="auto")

    old_count = len(memories)
    new_count = len(items)
    print(f"[memory] 整理完毕：{old_count} → {new_count} 条")
    return new_count

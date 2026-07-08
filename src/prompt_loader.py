"""Prompt Loader — 运行时组装 system prompt

参考 s10 设计：分段定义，按需拼接。
"""

from pathlib import Path
from typing import List, Optional

from src.config import ROOT_DIR
from src.memory_store import get_all_memory_texts


SYSTEM_PROMPT_FILE = ROOT_DIR / "configs" / "system_prompt.txt"
SOUL_FILE = ROOT_DIR / "configs" / "soul.txt"


# ============================================================
# 分段定义
# ============================================================

def _section_identity() -> str:
    """始终加载：你是谁、基本行为约束"""
    if SYSTEM_PROMPT_FILE.exists():
        return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    return "基于已有上下文回答用户问题。回答应清晰、直接，并优先帮助用户完成当前任务。"


def _section_soul() -> str:
    """始终加载：身份风格"""
    if SOUL_FILE.exists():
        return SOUL_FILE.read_text(encoding="utf-8").strip()
    return ""


def _section_memory() -> str:
    """按需加载：长期记忆（仅当有记忆时）"""
    memories = get_all_memory_texts()
    if not memories:
        return ""
    items = "\n".join(f"- {m}" for m in memories)
    return f"长期记忆（请尊重）：\n{items}"


# ============================================================
# 组装
# ============================================================

def load_system_prompt() -> str:
    """兼容旧接口：只返回 system prompt 本体"""
    return _section_identity()


def load_soul() -> str:
    """兼容旧接口：只返回 soul"""
    return _section_soul()


def assemble_prompt() -> str:
    """组装完整的 system prompt（不含 session 上下文）

    返回多个 segments 拼接后的字符串。
    """
    segments: List[str] = []

    # 1. Identity — 始终加载
    identity = _section_identity()
    if identity:
        segments.append(identity)

    # 2. Soul — 始终加载
    soul = _section_soul()
    if soul:
        segments.append(f"[风格] {soul}")

    # 3. Memory — 按需加载
    memory = _section_memory()
    if memory:
        segments.append(memory)

    return "\n\n".join(segments)

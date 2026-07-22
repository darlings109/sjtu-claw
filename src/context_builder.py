"""Context Builder — 组装最终发给 LLM 的 messages

职责：从 session、system prompt、memory、soul 等来源构造模型输入。
"""

from typing import Dict, List

from src.prompt_loader import assemble_prompt
from src.session_store import Session
from src.skill_registry import get_skill_catalog


def build_context(session: Session) -> List[Dict[str, str]]:
    """构造发送给 LLM 的 messages

    当前包含：
        1. system prompt + soul + memory（由 assemble_prompt 统一组装）
        2. session summary（压缩摘要，如果有）
        3. session 历史 messages

    Args:
        session: 当前 session

    Returns:
        messages 列表，可直接发送给 LLM
    """
    messages: List[Dict[str, str]] = []

    # 1-3. 使用 assemble_prompt 组装所有 system prompt 段
    full_prompt = assemble_prompt()

    # 技能目录（LCC s07 两级加载的第一级：猫在 system prompt 中的简短索引）
    skill_catalog = get_skill_catalog()
    if skill_catalog:
        full_prompt += "\n\n" + skill_catalog

    messages.append({"role": "system", "content": full_prompt})

    # 4. Session summary（Step 4 的 compaction 会使用）
    if session.summary:
        messages.append({"role": "system", "content": f"会话摘要：{session.summary}"})

    # 5. Session 历史 messages
    messages.extend(session.messages)

    return messages

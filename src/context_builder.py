"""Context Builder — 组装最终发给 LLM 的 messages

职责：从 session、system prompt、memory、soul 等来源构造模型输入。
"""

from typing import Dict, List

from src.prompt_loader import assemble_prompt
from src.session_store import Session
from src.skill_registry import get_skill_catalog


def _drop_orphan_tool_messages(messages: List[Dict]) -> List[Dict]:
    """剔除配对不完整的 tool calling 消息

    API 要求 role=tool 的消息前面必须有带 tool_calls 的 assistant 消息，
    且每个 tool_call 都要有对应响应。压缩管线按轮次截断历史时可能切断这种
    配对，导致后续所有请求都被拒（HTTP 400）。这里做一次兜底清理。
    """
    responded = {
        m.get("tool_call_id") for m in messages if m.get("role") == "tool"
    }
    out: List[Dict] = []
    open_ids = set()

    for m in messages:
        role = m.get("role")

        if role == "assistant" and m.get("tool_calls"):
            kept = [tc for tc in m["tool_calls"] if tc.get("id") in responded]
            m = dict(m)
            if kept:
                m["tool_calls"] = kept
                open_ids.update(tc["id"] for tc in kept)
            else:
                # 没有任何响应留存 → 退化成普通消息，内容为空则整条丢弃
                m.pop("tool_calls", None)
                if not (m.get("content") or "").strip():
                    continue
            out.append(m)

        elif role == "tool":
            if m.get("tool_call_id") in open_ids:
                out.append(m)
            # 否则是孤儿，丢弃

        else:
            out.append(m)

    return out


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
    # 剥掉 ts：那是给前端显示时间用的本地字段，API 只接受它认识的键
    for m in _drop_orphan_tool_messages(session.messages):
        if "ts" in m:
            m = {k: v for k, v in m.items() if k != "ts"}
        messages.append(m)

    return messages

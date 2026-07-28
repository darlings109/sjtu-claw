"""Agent Loop 模块

封装核心对话逻辑：接收用户消息、构造上下文、调用 LLM、处理 tool call。
"""

import json

from src.compactor import KEEP_RECENT_ROUNDS, _collect_recent, compact_history, reactive_compact, should_compact, run_pipeline
from src.config import LLMConfig
from src.context_builder import build_context
from src.llm_client import chat_completion
from src.memory_store import consolidate_memories, extract_memories
from src.session_store import Session, save_session, load_session, _now
from src.tool_registry import get_registry


def _to_api_tool_call(tc: dict) -> dict:
    """把内部 tool_call 结构还原成 OpenAI 请求格式，供回填历史使用"""
    return {
        "id": tc["id"],
        "type": "function",
        "function": {
            "name": tc["name"],
            "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
        },
    }


def process_message(
    config: LLMConfig,
    session: Session,
    user_content: str,
) -> str:
    """处理一条用户消息：单轮 LLM + tool calling 循环"""
    session.messages.append({"role": "user", "content": user_content, "ts": _now()})

    # Agent loop: LLM → tool → LLM → tool → … → final
    # 限制 tool call 轮次，防止模型死循环
    max_tool_rounds = 10
    tool_rounds = 0
    final_reply = ""

    while tool_rounds < max_tool_rounds:
        tool_rounds += 1

        # 构造上下文
        messages = build_context(session)
        tools_defs = get_registry().get_definitions()

        # 调用 LLM
        content, raw, tool_calls = chat_completion(
            config, messages, tools=tools_defs if tools_defs else None,
        )

        # 记录 assistant 回复（带 tool_calls，否则下一轮 tool 消息会成为孤儿）
        assistant_msg = {"role": "assistant", "content": content, "ts": _now()}
        if tool_calls:
            assistant_msg["tool_calls"] = [_to_api_tool_call(tc) for tc in tool_calls]
        session.messages.append(assistant_msg)

        # 没有 tool_call → 最终回复
        if not tool_calls:
            final_reply = content
            break

        # 有 tool_call → 执行并追加结果
        tool_results = []
        for tc in tool_calls:
            name = tc["name"]
            args = tc["arguments"]
            tool_id = tc["id"]
            print(f"  \033[33m[tool_call] {name} {json.dumps(args, ensure_ascii=False)}\033[0m")

            result = get_registry().execute(name, args)
            print(f"  \033[90m[tool_result] {result[:200]}\033[0m")

            tool_results.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": result,
                "ts": _now(),
            })

        session.messages.extend(tool_results)

    # 保存 session
    save_session(session)

    # 自动提取记忆（失败不影响主流程）
    try:
        extract_memories(config, session.messages)
        consolidate_memories()
    except Exception:
        pass

    return final_reply


def _run_agent_stream(config: LLMConfig, session: Session, user_content: str):
    """以流式事件运行 agent loop（供 SSE endpoint 使用）

    Yields:
        events: {type, content/name/arguments…}
    """
    from src.context_builder import build_context
    from src.llm_client import chat_completion_stream
    from src.session_store import append_message, save_session
    from src.tool_registry import get_registry

    # Add user message
    append_message(session.session_id, "user", user_content)

    # 重新加载 session 确保拿到最新数据
    new_session = load_session(session.session_id)
    if new_session:
        session = new_session

    max_tool_rounds = 10
    tool_rounds = 0

    while tool_rounds < max_tool_rounds:
        tool_rounds += 1

        messages = build_context(session)
        tools_defs = get_registry().get_definitions()

        collected_text = ""
        tool_calls = []

        for event in chat_completion_stream(config, messages, tools=tools_defs if tools_defs else None):
            if event["type"] == "text":
                collected_text += event["content"]
                yield {"type": "token", "content": event["content"]}
            elif event["type"] == "tool_call":
                tool_calls.append(event)
                yield {"type": "tool_call", "name": event["name"], "arguments": event["arguments"]}
            elif event["type"] == "done":
                collected_text = event.get("content", collected_text)
            elif event["type"] == "error":
                yield event
                return

        # Save assistant reply
        # 有 tool_calls 时必须落盘（即使没有文本），否则后面的 tool 消息会成为孤儿
        if collected_text or tool_calls:
            extra = {"tool_calls": [_to_api_tool_call(tc) for tc in tool_calls]} if tool_calls else None
            append_message(session.session_id, "assistant", collected_text, extra)
            if collected_text:
                yield {"type": "text_done", "content": collected_text}

        if not tool_calls:
            break

        # Execute tool calls
        for tc in tool_calls:
            name = tc["name"]
            args = tc["arguments"]
            result = get_registry().execute(name, args)
            append_message(session.session_id, "tool", result, {"tool_call_id": tc["id"]})
            yield {"type": "tool_result", "name": name, "result": result[:500]}

        # 重新加载：上面的 append 只写了磁盘，内存里的 session 仍是旧的，
        # 不刷新的话下一轮 build_context 看不到 tool 结果，会重复同一个 tool call
        refreshed = load_session(session.session_id)
        if refreshed:
            session = refreshed

        tool_calls = []

    yield {"type": "done"}


def process_and_compact(
    config: LLMConfig,
    session: Session,
    user_content: str,
) -> str:
    """处理消息并在回复后检查是否需要压缩"""
    reply = process_message(config, session, user_content)

    old_len = len(session.messages)
    session.messages = run_pipeline(session.messages)

    if should_compact(session.messages):
        try:
            new_summary, old_count, recent_count = compact_history(
                config, session.messages,
                existing_summary=session.summary,
            )
            session.summary = new_summary
            session.messages = _collect_recent(session.messages, KEEP_RECENT_ROUNDS)
            save_session(session)
            print(f"[system] compact {session.session_id}: old={old_count}, recent={recent_count}")
        except Exception as e:
            try:
                print("[reactive compact]")
                new_summary, old_count, recent_count = reactive_compact(
                    config, session.messages,
                    existing_summary=session.summary,
                )
                if new_summary:
                    session.summary = new_summary
                    session.messages = _collect_recent(session.messages, KEEP_RECENT_ROUNDS)
                    save_session(session)
                    print(f"[reactive] compact {session.session_id}: old={old_count}, recent={recent_count}")
            except Exception:
                print("[警告] reactive compact 也失败, 原始消息已保留", file=__import__("sys").stderr)

    return reply


def compact_now(config: LLMConfig, session: Session) -> None:
    """手动压缩当前 session（/compact 命令）"""
    if not session.messages:
        print("当前 session 没有消息，无需压缩。")
        return

    try:
        new_summary, old_count, recent_count = compact_history(
            config, session.messages,
            existing_summary=session.summary,
        )
        if not old_count:
            print("当前 session 消息较少，不需要压缩。")
            return

        session.summary = new_summary
        session.messages = _collect_recent(session.messages, KEEP_RECENT_ROUNDS)
        save_session(session)

        print(f"Compacted session {session.session_id}.")
        print(f"Old messages: {old_count}")
        print(f"Recent messages: {recent_count}")
        print(f"Summary:")
        print(new_summary)

    except Exception as e:
        print(f"[错误] 压缩失败：{e} — 原始消息已保留", file=__import__("sys").stderr)

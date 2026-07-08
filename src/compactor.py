import json
import time
from pathlib import Path
from typing import Dict, List, Tuple

from src.config import ROOT_DIR, LLMConfig
from src.llm_client import chat_completion


# Constants
SNIP_MAX_MESSAGES = 50
SNIP_KEEP_HEAD = 3
KEEP_RECENT_TOOL_RESULTS = 3
COMPACT_THRESHOLD_CHARS = 80000
KEEP_RECENT_ROUNDS = 4
MAX_COMPACT_FAILURES = 3

TRANSCRIPT_DIR = ROOT_DIR / ".transcripts"


def _count_rounds(messages: List[Dict]) -> int:
    return sum(1 for m in messages if m.get("role") == "user")


def _estimate_size(messages: List[Dict]) -> int:
    return len(json.dumps(messages, ensure_ascii=False))


def _is_tool_result_message(msg: Dict) -> bool:
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def _message_has_tool_use(msg: Dict) -> bool:
    if msg.get("role") != "assistant":
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)


def _collect_recent(messages: List[Dict], keep_rounds: int) -> List[Dict]:
    user_count = 0
    split = 0
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            user_count += 1
            if user_count == keep_rounds:
                split = i
                break
    return messages[split:]


# L1: snip_compact
def snip_compact(messages: List[Dict]) -> List[Dict]:
    max_messages = SNIP_MAX_MESSAGES
    if len(messages) <= max_messages:
        return messages
    keep_tail = max_messages - SNIP_KEEP_HEAD
    head_end = SNIP_KEEP_HEAD
    tail_start = len(messages) - keep_tail
    if head_end > 0 and _message_has_tool_use(messages[head_end - 1]):
        while head_end < len(messages) and _is_tool_result_message(messages[head_end]):
            head_end += 1
    if (tail_start > 0 and tail_start < len(messages)
            and _is_tool_result_message(messages[tail_start])
            and _message_has_tool_use(messages[tail_start - 1])):
        tail_start -= 1
    if head_end >= tail_start:
        return messages
    snipped = tail_start - head_end
    placeholder = {"role": "user", "content": f"[snipped {snipped} messages from conversation middle]"}
    return messages[:head_end] + [placeholder] + messages[tail_start:]


# L2: micro_compact
def collect_tool_results(messages: List[Dict]) -> List[Tuple[int, int, Dict]]:
    blocks: List[Tuple[int, int, Dict]] = []
    for mi, msg in enumerate(messages):
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            continue
        for bi, block in enumerate(msg["content"]):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                blocks.append((mi, bi, block))
    return blocks


def micro_compact(messages: List[Dict]) -> List[Dict]:
    tool_results = collect_tool_results(messages)
    if len(tool_results) <= KEEP_RECENT_TOOL_RESULTS:
        return messages
    for _, _, block in tool_results[:-KEEP_RECENT_TOOL_RESULTS]:
        if len(str(block.get("content", ""))) > 120:
            block["content"] = "[Earlier tool result compacted. Re-run if needed.]"
    return messages


# Transcript: save full history before compaction
def write_transcript(messages: List[Dict]) -> str:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    path = TRANSCRIPT_DIR / f"transcript_{timestamp}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False, default=str) + "\n")
    return str(path)


# L3: compact_history with transcript
def build_compact_prompt(existing_summary: str, old_messages: List[Dict]) -> str:
    conversation = json.dumps(old_messages, ensure_ascii=False)[:60000]
    prompt = (
        "你正在压缩一段 AI 助手的对话历史。请阅读以下对话，生成一段简洁的摘要。\n\n"
        "摘要需要保留以下信息：\n"
        "1. 当前任务和目标\n"
        "2. 已经完成的内容和关键发现\n"
        "3. 用户明确提出的要求、偏好和约束\n"
        "4. 尚未解决的问题和下一步计划\n"
        "5. 影响继续回答的重要事实\n\n"
        "应删除的内容：\n"
        "- 寒暄和重复表达\n"
        "- 无关细节\n"
        "- 没有继续使用价值的中间过程\n\n"
        "摘要应简洁、可读，适合作为继续对话的上下文。\n"
        "输出只包含摘要本身，不要有多余说明。\n"
    )
    if existing_summary:
        prompt += f"\n已有摘要（请合并本段内容到新摘要中）：\n{existing_summary}\n"
    prompt += f"\n待压缩的对话历史：\n{conversation}\n"
    return prompt


def compact_history(
    config: LLMConfig,
    messages: List[Dict],
    existing_summary: str = "",
    keep_rounds: int = KEEP_RECENT_ROUNDS,
) -> Tuple[str, int, int]:
    if not messages:
        return existing_summary, 0, 0

    transcript_path = write_transcript(messages)
    print(f"[transcript saved: {transcript_path}]")

    recent = _collect_recent(messages, keep_rounds)
    old = messages[:len(messages) - len(recent)]

    if not old:
        return existing_summary, 0, len(messages)

    prompt = build_compact_prompt(existing_summary, old)
    compact_msgs = [{"role": "user", "content": prompt}]
    summary, _ = chat_completion(config, compact_msgs)
    summary = summary.strip()

    if not summary:
        raise ValueError("生成的摘要为空，取消本次压缩")

    return summary, len(old), len(recent)


# Emergency: reactive_compact
def reactive_compact(
    config: LLMConfig,
    messages: List[Dict],
    existing_summary: str = "",
) -> Tuple[str, int, int]:
    if not messages:
        return existing_summary, 0, 0

    transcript_path = write_transcript(messages)
    print(f"[reactive] transcript saved: {transcript_path}")

    tail_start = max(0, len(messages) - 5)
    if (tail_start > 0 and tail_start < len(messages)
            and _is_tool_result_message(messages[tail_start])
            and _message_has_tool_use(messages[tail_start - 1])):
        tail_start -= 1

    old = messages[:tail_start]
    recent = messages[tail_start:]

    if not old:
        return existing_summary, 0, len(messages)

    prompt = build_compact_prompt(existing_summary, old)
    compact_msgs = [{"role": "user", "content": prompt}]
    summary, _ = chat_completion(config, compact_msgs)
    summary = summary.strip()

    if not summary:
        raise ValueError("Reactive compact result is empty")

    return summary, len(old), len(recent)


# Prediction functions
def should_snip(messages: List[Dict]) -> bool:
    return len(messages) > SNIP_MAX_MESSAGES

def should_compact(messages: List[Dict]) -> bool:
    return _estimate_size(messages) > COMPACT_THRESHOLD_CHARS


# Pipeline
def run_pipeline(messages: List[Dict]) -> List[Dict]:
    messages = snip_compact(messages)
    messages = micro_compact(messages)
    return messages

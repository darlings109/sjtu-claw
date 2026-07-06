"""LLM API 调用模块

封装 Chat Completions API 的请求与响应解析。
"""

import json
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.config import LLMConfig


def build_headers(api_key: str) -> Dict[str, str]:
    """构造 API 请求头"""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def build_payload(
    model: str,
    messages: List[Dict[str, str]],
    **kwargs: Any,
) -> Dict[str, Any]:
    """构造请求体"""
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    payload.update(kwargs)
    return payload


def chat_completion(
    config: LLMConfig,
    messages: List[Dict[str, str]],
    **kwargs: Any,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """调用 Chat Completions API

    Args:
        config: LLM 连接配置
        messages: 消息列表，格式为 [{"role": "...", "content": "..."}, ...]
        **kwargs: 额外参数（temperature, max_tokens 等）

    Returns:
        (content, raw_response)
        content: 模型回复文本
        raw_response: 完整响应（用于调试）

    Raises:
        ConnectionError: 网络连接失败
        ValueError: API 返回错误
        requests.Timeout: 请求超时
    """
    url = f"{config.base_url}/chat/completions"
    headers = build_headers(config.api_key)
    payload = build_payload(config.model, messages, **kwargs)

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=config.timeout,
        )
    except requests.exceptions.Timeout:
        raise ConnectionError(
            f"请求超时（{config.timeout}秒）。\n"
            f"请检查网络连接和 base_url：{config.base_url}"
        )
    except requests.exceptions.ConnectionError as e:
        raise ConnectionError(
            f"网络连接失败。\n"
            f"请检查网络连接和 base_url：{config.base_url}\n"
            f"详细错误：{e}"
        )

    if response.status_code == 401:
        raise ValueError(
            "API KEY 认证失败（HTTP 401）。\n"
            "请检查 LLM_API_KEY 是否正确。"
        )
    elif response.status_code == 429:
        raise ValueError(
            "请求频率过高（HTTP 429）。\n"
            "请稍后重试。"
        )
    elif response.status_code >= 400:
        raise ValueError(
            f"API 返回错误（HTTP {response.status_code}）。\n"
            f"响应内容：{response.text[:500]}"
        )

    try:
        data = response.json()
    except json.JSONDecodeError as e:
        raise ValueError(
            "API 响应不是有效的 JSON 格式。\n"
            f"原始响应：{response.text[:500]}"
        )

    # 提取 assistant 回复
    try:
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(
            "API 响应格式异常，无法解析 assistant 回复。\n"
            f"原始响应：{json.dumps(data, ensure_ascii=False)[:500]}"
        )

    # 检查 finish_reason
    finish_reason = choice.get("finish_reason", "unknown")
    if finish_reason == "length":
        print(f"[警告] 回复被截断（finish_reason=length），模型返回可能不完整。")

    return content or "", data

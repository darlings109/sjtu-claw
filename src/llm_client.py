"""LLM API 调用模块

封装 Chat Completions API 的请求与响应解析。
支持原生 tool calling（function calling）。
"""

import json
import warnings
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from urllib3.exceptions import InsecureRequestWarning

from src.config import LLMConfig

warnings.filterwarnings("ignore", category=InsecureRequestWarning)


def build_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def build_payload(
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
    payload.update(kwargs)
    return payload


def chat_completion(
    config: LLMConfig,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any,
) -> Tuple[str, Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """调用 Chat Completions API，支持 function calling

    Returns:
        (content, raw_response, tool_calls)
        content: 模型回复文本（如果没有 tool_calls，这里是最终回复）
        raw_response: 完整响应
        tool_calls: 模型请求的 tool call 列表（每项含 name, arguments, id）
    """
    url = f"{config.base_url}/chat/completions"
    headers = build_headers(config.api_key)
    payload = build_payload(config.model, messages, tools=tools, **kwargs)

    try:
        response = requests.post(
            url, headers=headers, json=payload,
            timeout=config.timeout, verify=False,
        )
    except requests.exceptions.Timeout:
        raise ConnectionError(f"请求超时（{config.timeout}秒）。请检查网络连接和 base_url：{config.base_url}")
    except requests.exceptions.ConnectionError as e:
        raise ConnectionError(f"网络连接失败。请检查网络连接和 base_url：{config.base_url}\n详细错误：{e}")

    if response.status_code == 401:
        raise ValueError("API KEY 认证失败（HTTP 401）。请检查 LLM_API_KEY 是否正确。")
    elif response.status_code == 429:
        raise ValueError("请求频率过高（HTTP 429）。请稍后重试。")
    elif response.status_code >= 400:
        raise ValueError(f"API 返回错误（HTTP {response.status_code}）。响应内容：{response.text[:500]}")

    try:
        data = response.json()
    except json.JSONDecodeError as e:
        raise ValueError(f"API 响应不是有效的 JSON 格式。原始响应：{response.text[:500]}")

    # 提取 choice
    try:
        choice = data["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"API 响应格式异常：{json.dumps(data, ensure_ascii=False)[:500]}")

    content = message.get("content") or ""
    finish_reason = choice.get("finish_reason", "unknown")

    # 解析 tool_calls
    tool_calls: List[Dict[str, Any]] = []
    raw_tool_calls = message.get("tool_calls")
    if raw_tool_calls:
        for tc in raw_tool_calls:
            try:
                args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                args = {}
            tool_calls.append({
                "id": tc["id"],
                "name": tc["function"]["name"],
                "arguments": args,
            })

    if finish_reason == "length":
        print(f"[警告] 回复被截断（finish_reason=length），模型返回可能不完整。")

    return content or "", data, tool_calls

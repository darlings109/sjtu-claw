"""Claw — 最小 Agent Runtime 入口

启动命令：
    python -m src.main
"""

import sys

from src.config import load_config
from src.llm_client import chat_completion


def main() -> None:
    """主入口：读取配置、调用 LLM、打印回复"""
    # Step 1: 读取配置
    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    # 构造一条 user message
    messages = [
        {
            "role": "user",
            "content": "你好，请用一句话介绍你自己。",
        },
    ]

    print(f"正在调用 {config.model} ...")

    # Step 2: 调用 LLM
    try:
        content, raw = chat_completion(config, messages)
    except (ConnectionError, ValueError) as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    # Step 3: 打印回复
    print(f"\nAssistant> {content}")


if __name__ == "__main__":
    main()

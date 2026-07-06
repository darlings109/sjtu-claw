"""配置读取模块

从 .env 或系统环境变量加载 LLM 配置。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


# 项目根目录（src/ 的父目录）
ROOT_DIR = Path(__file__).resolve().parent.parent

# 默认 .env 路径
DOTENV_PATH = ROOT_DIR / ".env"


@dataclass
class LLMConfig:
    """LLM 连接配置"""
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    timeout: int = 60


def load_config(env_path: Optional[Path] = None) -> LLMConfig:
    """加载 LLM 配置

    Args:
        env_path: .env 文件路径，默认使用项目根目录下的 .env

    Returns:
        LLMConfig 对象

    Raises:
        FileNotFoundError: .env 文件不存在
        ValueError: API KEY 未配置
    """
    env_path = env_path or DOTENV_PATH

    # 加载 .env 文件（如果存在）
    if env_path.exists():
        load_dotenv(env_path)
    else:
        raise FileNotFoundError(
            f"配置文件 {env_path} 不存在。\n"
            f"请复制 {ROOT_DIR / '.env.example'} 为 {env_path} 并填入你的 API KEY。"
        )

    api_key = os.getenv("LLM_API_KEY", "").strip()
    base_url = os.getenv("LLM_BASE_URL", "").strip() or "https://api.openai.com/v1"
    model = os.getenv("LLM_MODEL", "").strip() or "gpt-4o-mini"

    if not api_key:
        raise ValueError(
            "LLM_API_KEY 未配置。\n"
            f"请编辑 {env_path}，填入你的 API KEY。"
        )

    return LLMConfig(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        model=model,
    )

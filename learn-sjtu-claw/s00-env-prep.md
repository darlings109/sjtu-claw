# S00：环境准备与 LLM API 接入

## 概述

本 Step 的目标是完成 claw 的最小运行闭环：程序能够从 `.env` 读取配置，向 LLM 发送一条消息，并在终端打印模型回复。对应 TASK.md 的 "Step 0：环境准备与 LLM API 接入"。

## 对应 TASK.md 要求

- [x] 搭建开发环境（WSL + Python + Git）
- [x] 创建基础工程结构
- [x] API KEY 通过 `.env` 配置，不进入 Git
- [x] 实现最小 LLM API 调用
- [x] API KEY 缺失、网络失败、响应异常等场景给出清晰提示

## 关键文件

| 文件 | 职责 |
|:-----|:-----|
| [config.py](../src/config.py) | 从 `.env` 或环境变量加载 `LLMConfig` |
| [llm_client.py](../src/llm_client.py) | Chat Completions API 封装 |
| [main.py](../src/main.py) (入口) | CLI 入口，调用 `load_config()` + 后续逻辑 |
| [.env.example](../.env.example) | 配置模板 |
| [.gitignore](../.gitignore) | 排除 `.env`、`data/`、`logs/`、`__pycache__/` |

## 架构设计 / 实现路径

### 配置加载

`config.py` 提供了一个 `LLMConfig` dataclass 和 `load_config()` 函数：

```
.env / 环境变量
    │
    ▼
load_config()
    ├── 检测 .env 是否存在（不存在→FileNotFoundError）
    ├── 加载 dotenv，读取 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
    └── 验证 API_KEY 是否为空（为空→ValueError）
```

关键设计决策：
- **显式报错而非静默默认**：如果 `.env` 不存在或 API_KEY 为空，直接抛出带指导信息的异常而非使用空默认值，让用户知道该怎么做
- **明确的项目根目录**：`ROOT_DIR` 通过 `Path(__file__).resolve().parent.parent` 计算，不依赖 `os.getcwd()`，保证任何工作目录下都能正确找到 `.env`
- **dataclass 封装**：统一 `LLMConfig` 对象，后续模块只需接收这个对象，不需再关心环境变量

### LLM API 调用

`llm_client.py` 封装了 Chat Completions API：

```
build_headers(api_key)    → 构造 Authorization header
build_payload(model, messages, tools) → 构造请求 body
chat_completion(config, messages, tools) → 发送请求并解析响应
```

关键设计决策：
- **统一返回三元组**：`(content, raw_response, tool_calls)`，为 Step 1（多轮）和 Step 5（tool calling）预留接口
- **丰富的错误分类**：超时→ConnectionError，401→ValueError(认证失败)，429→ValueError(频率限制)，非 JSON→ValueError(格式异常)
- **零依赖 HTTP 客户端**：使用 `requests` 库，简单可靠

### 工程结构

创建时即按职责划分模块边界：

```
SJTU-claw/
├── src/                # 源码
│   ├── __init__.py
│   ├── config.py       # 配置加载
│   ├── llm_client.py   # LLM API 调用
│   └── main.py         # 入口
├── configs/            # 配置文件
├── data/               # 运行数据（gitignored）
├── .env.example        # 配置模板
└── .gitignore
```

## 核心代码解析

### `config.py`

```python
@dataclass
class LLMConfig:
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    timeout: int = 60
```

`load_config()` 的实现循序渐进：
1. 检查 `.env` 文件存在性
2. 读取环境变量（带 fallback 默认值）
3. 验证 API_KEY 不为空
4. 返回 `LLMConfig` 对象

### `llm_client.py`

```python
def chat_completion(config, messages, tools=None):
    headers = {"Authorization": f"Bearer {config.api_key}", ...}
    payload = {"model": config.model, "messages": messages, ...}
    response = requests.post(url, headers=headers, json=payload, timeout=...)
    # 错误分类处理...
    # 解析 tool_calls...
    return content, data, tool_calls
```

## 优化方向

1. **代理支持**：当前未实现 HTTP 代理（如 `HTTP_PROXY` 环境变量），在受限网络环境可能无法直接访问 API
2. **模型选择可视化**：CLI 启动时可提示当前使用的模型，方便调试确认
3. **请求重试**：对 429/503 等可恢复错误没有自动重试机制

## 可能的问题

- `.env` 不在项目根目录时无法加载（`load_config` 默认从 `ROOT_DIR/.env` 读取）
- `timeout` 默认 60s 对大文件读取场景偏短（但 Step 0 只做简单调用，60s 足够）
- API Base URL 尾斜杠处理：`rstrip("/")` 防止 `//chat/completions` 双斜杠

## 关联文档

- TASK.md §Step 0

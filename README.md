# SJTUClaw — 最小 AI Agent Runtime

SJTU 课程项目：从零构建一个最小可用的 AI Agent Runtime。基于 Python，通过 OpenAI 兼容 API 驱动，自带 CLI 与 Web 两种交互方式，内置工具调用、技能系统、上下文压缩等核心机制。

## 运行环境

| 项 | 要求 |
|---|---|
| 操作系统 | Windows / macOS / Linux 均可（本项目在 Windows + WSL 环境下开发并验证） |
| Python | **3.10+**（使用了 `pathlib`、`dataclasses`、`match` 等现代语法） |
| 模型 | 任意 OpenAI 兼容接口（默认配置指向 DeepSeek，可改） |

> Windows 上若命令行直接运行无效，可改用 `python` 所在目录下的 `python.exe`，或将 Python 加入 PATH。

## 安装

```bash
# 1. 安装依赖（仅两个第三方库）
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，填入你的 API Key（默认可直接用 DeepSeek，也可改 BASE_URL 对接其他服务）
```

`.env` 配置项：

| 变量 | 说明 | 默认 |
|---|---|---|
| `LLM_API_KEY` | API Key | — |
| `LLM_BASE_URL` | OpenAI 兼容接口地址 | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 模型名 | `deepseek-v4-flash` |

## 运行

### 方式一：命令行（CLI）

```bash
python -m src.main
```

终端内多轮对话，输入 `/help` 查看可用命令，`/approve` 审批写操作。

### 方式二：Web UI（浏览器）

```bash
python -m src.main gateway
# 或指定端口
python -m src.main gateway 8080
```

打开浏览器访问 `http://localhost:5000`（默认端口），支持多会话、附件、工具审批、技能管理等。

### 方式三：桌面快捷方式（Windows）

```bash
python launcher/start_gateway.py
```

或在 Windows 下运行 `launcher/install_shortcut.ps1` 在桌面创建一键启动快捷方式。

## 功能概览

- **Agent Loop**：多轮对话、上下文管理（`agent.py`）
- **工具调用**：文件读写、命令执行、网络下载、技能加载等 11 个工具，写操作需审批（`tool_registry.py` / `workspace.py`）
- **上下文压缩**：三级管线 —— 消息裁剪 → tool 结果压缩 → LLM 摘要（`compactor.py`）
- **技能系统**：`skills/` 下按目录组织，两级加载（`skill_registry.py`）
- **Web UI**：纯原生 JS + CSS 单页应用，Python 内置 `http.server`，零框架、零额外依赖
- **定时任务**：可配置的周期任务调度（`scheduler.py`）

## 测试

```bash
python tests/test_core.py
python tests/test_scheduler.py
```

## 项目结构

```
src/
  main.py             # 程序入口（CLI / gateway 双模式）
  agent.py            # Agent 主循环
  context_builder.py  # 组装发送给 LLM 的上下文
  llm_client.py       # LLM API 客户端
  tool_registry.py    # 工具注册与调用
  compactor.py        # 上下文三级压缩
  session_store.py    # 会话存储
  memory_store.py     # 长期记忆
  scheduler.py        # 定时任务
  workspace.py        # 工作区与审批
  skill_registry.py   # 技能系统
  config.py           # 配置读取
  prompt_loader.py    # Prompt 组装
  web/server.py       # Web 网关（http.server 实现）
  web/static/         # 前端（纯原生 JS/CSS）
launcher/             # Windows 桌面快捷方式
configs/              # 系统 Prompt / Soul
skills/               # 技能定义
tests/                # 测试
```

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

SJTUClaw — 从零构建最小 AI Agent Runtime。SJTU 课程项目，基于 Python + OpenAI 兼容 API。

## 启动命令

```bash
# 安装依赖
pip install -r requirements.txt

# CLI 模式
python -m src.main

# Web UI 模式（端口 5000）
python -m src.main gateway

# 运行测试
python tests/test_core.py
```

## 核心架构

两条入口共享同一套核心引擎：
- `python -m src.main` → CLI 模式（终端交互）
- `python -m src.main gateway` → Web 模式（浏览器 http://localhost:5000）

数据流：`main.py/server.py` → `agent.py`(Agent Loop) → `context_builder.py` → `llm_client.py`(LLM API) → `tool_registry.py`(tool call 循环) → `compactor.py`(上下文压缩)

## 设计规范

- 所有 tool 注册到全局 `ToolRegistry` 单例（`tool_registry.py`）
- 写操作需通过 `approval` 机制（`workspace.py` → CLI `/approve`）
- 上下文三级压缩管线：snipping → micro-compact → LLM 摘要
- Gateway 使用 Python 内置 `http.server`（零依赖），保持这一选择
- 前端为纯原生 JS + CSS 单页应用（零框架）

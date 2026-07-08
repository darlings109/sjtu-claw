# SJTU-Claw — 最小 Agent Runtime

SJTU 课程项目：从零构建最小 AI Agent Runtime。

## 快速开始

1. 复制配置文件
   cp .env.example .env
   # 编辑 .env，填入你的 API KEY

2. 安装依赖
   pip install -r requirements.txt

3. 运行
   python -m src.main

## 项目结构

src/          # 源代码
  main.py     # 程序入口
  config.py   # 配置读取
  llm_client.py  # LLM API 调用
data/         # 运行数据
tests/        # 测试
logs/         # 日志

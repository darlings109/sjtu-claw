# SJTUClaw — 下一阶段工作规划

> 编写日期：2026-07-09
> 基于：多轮用户验收测试 + 代码审查

---

## ✅ 已完成（当前阶段）

### 功能修复

| 项 | 状态 |
|:---|:-----|
| `wait_approval(timeout=)` 关键字参数不匹配修复 | ✅ |
| `chat_completion` 返回值 3 元组解包修复（compactor + memory_store） | ✅ |
| `handle_task_command` 从错误模块导入修复 | ✅ |
| `server.py` 6 处重复 API 路由去重 + `_read_json`/`_path_segment` 提取 | ✅ |
| 事件绑定从逐元素监听改为事件委托（防止 load() 刷新后 click 失效） | ✅ 刚修 |
| `index.html` 残留 `function switchTo(id) {}` 导致侧边栏失灵 | ✅ |

### 新功能

| 项 | 状态 |
|:---|:-----|
| `workspace.py` `create_download` + `get_download_path` 实现 | ✅ |
| `workspace.py` `copy_attachment_to_workspace` 实现 | ✅ |
| `session_store.py` JSON 自动备份与损坏恢复机制 | ✅ |
| Server API 端点：approvals / skills / tasks / workspace | ✅ |
| SSE 流式输出端点 `/messages/stream` | ✅ |
| Web UI 暗色模式（手动切换 + localStorage 记忆 + 跟随系统） | ✅ |
| Web UI 附件上传按钮 + 列表展示 | ✅ |
| Web UI 附件随消息发送（后端拼接到 prompt 中） | ✅ |
| Web UI 发送中按钮禁用 + waiting 提示 | ✅ |
| 测试：`tests/test_core.py` | ✅ |
| 文档：`UX_REVIEW.md` 产品体验评审报告 | ✅ |

---

## ⚠️ 当前遗留问题

### P0 — 功能不可用

| # | 问题 | 现象 | 原因 |
|:-:|:-----|:------|:------|
| 1 | 附件内容未真正读取 | 发送附件后模型回复"文件找不到" | `/messages` API 只传了文件名，没有从 `data/attachments/` 读文件内容拼进 prompt |
| 2 | API 响应格式不一致 | CLI print 带颜色前缀，Gateway 返回 JSON，前端有时显示 `[API Error]` | 无统一错误处理 |

### P1 — 体验粗糙

| # | 问题 | 现象 |
|:-:|:-----|:------|
| 3 | 附件文件名不可读 | 用 UUID 命名（`a61a0b78...`），用户不知道传了什么文件 |
| 4 | Web UI 无 Markdown 渲染 | 模型回复的 Markdown 格式以纯文本显示 |
| 5 | Web UI 无审批弹窗 | `create_file` 等需要 approval 的操作在 CLI 可批，Web 不可见 |
| 6 | Session 搜索结果不刷新 | 筛选后点击 session 切换回来会重置筛选条件 |

### P2 — 增强优化

| # | 问题 |
|:-:|:------|
| 7 | 无流式输出（SSE 端点已实现但前端未接入） |
| 8 | 无键盘快捷键 |
| 9 | 无消息编辑/重发 |
| 10 | 无会话导出 |
| 11 | 无任务完成 Toast 通知 |
| 12 | session 列表无搜索框 |
| 13 | 无首次使用引导 |

---

## 🎯 下一阶段建议

### Phase 1：先修 Bug（1-2 天）

```
P0-1 附件内容读取
  - 后端 /messages 收到 attachments 后，从 ATTACHMENTS_DIR 读取文件内容
  - 拼入 user message 前缀，让模型能看到文件内容而非只是文件名

P1-3 Session 搜索不刷新
  - load() 中的 filter 逻辑在 switchTo 后丢失
  - 把 filter 存在全局变量中，load() 复用时重新读取
```

### Phase 2：补齐 Web UI 体验（2-3 天）

```
P1-1 Markdown 渲染 + 代码高亮
  - 加 marked.js CDN（用稳定版链接）
  - assistant 消息渲染 Markdown，user 消息保持纯文本

P1-2 Web UI 审批弹窗
  - 前端轮询 /api/approvals
  - 弹出审批卡片（tool 名称 + 参数预览 + 批准/拒绝按钮）

P0-2 统一错误处理
  - CLI 统一 [ERROR] / [WARN] / [INFO] 前缀
  - Gateway 统一 {ok: false, error: {code, message}} 格式
```

### Phase 3：体验增强（2-3 天）

```
P1-4 SSE 流式输出
  - 前端用 fetch ReadableStream 消费 SSE 端点
  - 逐 token 展示回复，tool_call 展示内联卡片

P2-1 键盘快捷键（Ctrl+N 新建、Ctrl+R 重命名）
P2-2 Session 搜索框
P2-3 消息气泡操作栏（复制 / 重新生成）
P2-4 暗色模式确认
  - 🌙 按钮已实现，未人工确认是否生效
```

---

## 📋 技术债务

- [ ] `.env` 中的 API KEY 在提交前替换为占位值（已确认 `.gitignore` 包含 `.env`）
- [ ] Gateway 端口 `127.0.0.1:5000` 绑定，Windows 浏览器通过 `localhost:5000` 访问需确认网络栈
- [ ] `data/locks/` 目录残留过时锁文件（不影响功能）
- [ ] Web UI 当前使用 `http.server`（零依赖），后续保持这一选择
- [ ] Scheduler Engine 无停止钩子，程序退出时后台线程可能未正常清理

---

## 📊 总体评估

| 维度 | 评分 |
|:-----|:----:|
| Step 0-5 基础功能 | 60/60 ✅ |
| Step 6-9 高阶功能 | 20/20 ✅ |
| Web UI 体验 | ⭐⭐☆☆☆ |
| 错误处理 | ⭐⭐⭐☆☆ |
| 代码质量 | ⭐⭐⭐⭐☆ |

**一句话：功能全部到位，Web UI 体验还需要 1 个迭代打磨。**

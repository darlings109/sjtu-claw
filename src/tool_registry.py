"""Tool Registry — 工具注册与管理

统一管理 tool definition、tool handler、tool execution。
"""

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# ============================================================
# Tool 数据结构
# ============================================================

ToolDef = Dict[str, Any]
"""OpenAI-compatible tool definition"""

ToolHandler = Callable[..., str]
"""Tool handler 签名：接受关键字参数，返回文本结果"""


class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self._tools: Dict[str, ToolDef] = {}
        self._handlers: Dict[str, ToolHandler] = {}

    def register(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: ToolHandler,
    ) -> None:
        """注册一个 tool

        Args:
            name: 工具名称（唯一）
            description: 工具描述
            input_schema: JSON Schema 格式的参数定义
            handler: 执行函数
        """
        self._tools[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": input_schema,
            },
        }
        self._handlers[name] = handler

    def get_definitions(self) -> List[ToolDef]:
        """获取所有 tool definition（发 API 用）"""
        return list(self._tools.values())

    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        """执行指定 tool

        Args:
            name: 工具名称
            arguments: 参数字典

        Returns:
            执行结果的文本
        """
        handler = self._handlers.get(name)
        if handler is None:
            return f"Error: 未知 tool '{name}'"
        try:
            return handler(**arguments)
        except Exception as e:
            return f"Error: {e}"

    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys())


# ============================================================
# 全局注册表
# ============================================================

_registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    return _registry


# ============================================================
# 只读 Tool Handlers
# ============================================================

def current_time() -> str:
    """获取当前时间"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def list_dir(path: str = ".") -> str:
    """列出目录内容"""
    try:
        items = os.listdir(path)
        if not items:
            return f"(空目录: {path})"
        lines = []
        for name in sorted(items):
            full = os.path.join(path, name)
            if os.path.isdir(full):
                lines.append(f"{name}/")
            else:
                size = os.path.getsize(full)
                lines.append(f"{name}  ({size} bytes)")
        return "\n".join(lines)
    except FileNotFoundError:
        return f"Error: 目录不存在 '{path}'"
    except PermissionError:
        return f"Error: 没有权限访问 '{path}'"
    except Exception as e:
        return f"Error: {e}"


def read_file(path: str, limit: Optional[int] = None) -> str:
    """读取文本文件内容"""
    try:
        filepath = Path(path)
        if not filepath.exists():
            return f"Error: 文件不存在 '{path}'"
        if not filepath.is_file():
            return f"Error: '{path}' 不是文件"
        text = filepath.read_text(encoding="utf-8")
        if limit and len(text) > limit:
            text = text[:limit] + f"\n... (truncated, {len(text)} total chars)"
        return text
    except Exception as e:
        return f"Error: {e}"



def glob_files(pattern: str) -> str:
    """根据 glob 模式匹配文件路径"""
    import glob as g
    try:
        matches = sorted(g.glob(pattern, recursive=True))
        if not matches:
            return '(no matches: ' + str(pattern) + ')'
        result = []
        for m in matches:
            parts = Path(m).parts
            if any(p.startswith('.') for p in parts):
                continue
            result.append(m)
        return chr(10).join(result) if result else '(no matches)'
    except Exception as e:
        return 'Error: ' + str(e)




# ============================================================
# Advanced Tool Handlers（需审批）
# ============================================================

def handle_create_file(path: str, content: str) -> str:
    from src.workspace import create_file, get_workspace, create_approval, wait_approval, cleanup_approval
    ws = get_workspace()
    if ws is None:
        return "Error: Workspace not set. Use /workspace set <path> first."
    aid = create_approval("create_file", {"path": path, "content_length": len(content)})
    print(f"[approval] {aid}: create file {path}?")
    if wait_approval(aid, 120):
        cleanup_approval(aid)
        return create_file(path, content)
    else:
        cleanup_approval(aid)
        return "Operation rejected by user."


def handle_overwrite_file(path: str, content: str) -> str:
    from src.workspace import overwrite_file, get_workspace, create_approval, wait_approval, cleanup_approval
    ws = get_workspace()
    if ws is None:
        return "Error: Workspace not set."
    aid = create_approval("overwrite_file", {"path": path})
    print(f"[approval] {aid}: overwrite file {path}?")
    if wait_approval(aid, 120):
        cleanup_approval(aid)
        return overwrite_file(path, content)
    else:
        cleanup_approval(aid)
        return "Operation rejected."


def handle_edit_file(path: str, old_text: str, new_text: str) -> str:
    from src.workspace import edit_file, get_workspace, create_approval, wait_approval, cleanup_approval
    ws = get_workspace()
    if ws is None:
        return "Error: Workspace not set."
    aid = create_approval("edit_file", {"path": path})
    print(f"[approval] {aid}: edit file {path}?")
    if wait_approval(aid, 120):
        cleanup_approval(aid)
        return edit_file(path, old_text, new_text)
    else:
        cleanup_approval(aid)
        return "Operation rejected."


def handle_new_shell() -> str:
    from src.workspace import new_shell, get_workspace, create_approval, wait_approval, cleanup_approval
    ws = get_workspace()
    if ws is None:
        return "Error: Workspace not set."
    aid = create_approval("new_shell", {})
    print(f"[approval] {aid}: start shell?")
    if wait_approval(aid, 120):
        cleanup_approval(aid)
        return new_shell()
    else:
        cleanup_approval(aid)
        return "Operation rejected."


def handle_run_command(command: str) -> str:
    from src.workspace import run_command, get_workspace, create_approval, wait_approval, cleanup_approval
    ws = get_workspace()
    if ws is None:
        return "Error: Workspace not set."
    aid = create_approval("run_command", {"command": command[:80]})
    print(f"[approval] {aid}: run command?")
    if wait_approval(aid, 120):
        cleanup_approval(aid)
        return run_command(command)
    else:
        cleanup_approval(aid)
        return "Operation rejected."


def handle_create_download(path: str) -> str:
    from src.workspace import create_download as ws_dl
    return ws_dl(path)


def init_tools() -> None:
    """初始化并注册所有只读 tool"""
    r = _registry

    r.register(
        name="current_time",
        description="获取当前的日期和时间。当你需要知道现在几点或什么日期时使用。",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=current_time,
    )

    r.register(
        name="list_dir",
        description="列出指定目录的内容，包括文件和子目录。参数 path 默认为当前目录。",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要列出的目录路径，默认为当前目录",
                }
            },
            "required": [],
        },
        handler=list_dir,
    )

    r.register(
        name="read_file",
        description="读取文本文件的内容。支持可选参数 limit 限制返回字符数。",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要读取的文件路径",
                },
                "limit": {
                    "type": "integer",
                    "description": "可选，限制返回的最大字符数",
                },
            },
            "required": ["path"],
        },
        handler=read_file,
    )

    r.register(
        name="create_file",
        description="在 workspace 内创建新文件。需要 approval。",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径（相对 workspace）"},
                "content": {"type": "string", "description": "文件内容"},
            },
            "required": ["path", "content"],
        },
        handler=handle_create_file,
    )

    r.register(
        name="overwrite_file",
        description="用新内容覆盖 workspace 内已有文件。需要 approval。",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径（相对 workspace）"},
                "content": {"type": "string", "description": "新文件内容"},
            },
            "required": ["path", "content"],
        },
        handler=handle_overwrite_file,
    )

    r.register(
        name="edit_file",
        description="在 workspace 内替换文件中的指定文本。需要 approval。",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径（相对 workspace）"},
                "old_text": {"type": "string", "description": "要替换的旧文本"},
                "new_text": {"type": "string", "description": "新文本"},
            },
            "required": ["path", "old_text", "new_text"],
        },
        handler=handle_edit_file,
    )

    r.register(
        name="new_shell",
        description="在 workspace 中启动一个新的 shell。需要 approval。",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=handle_new_shell,
    )

    r.register(
        name="run_command",
        description="在当前 shell 中执行命令。需要 approval。",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令"},
            },
            "required": ["command"],
        },
        handler=handle_run_command,
    )

    r.register(
        name="create_download",
        description="为 workspace 内已有文件创建可通过 Gateway 下载的临时入口。不需要 approval。",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径（相对 workspace）"},
            },
            "required": ["path"],
        },
        handler=handle_create_download,
    )

    r.register(
        name="glob",
        description="根据 glob 模式匹配文件路径。例如 *.py 匹配所有 Python 文件，**/*.md 递归匹配所有 Markdown 文件。",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "glob 匹配模式，支持 ** 递归匹配",
                },
            },
            "required": ["pattern"],
        },
        handler=glob_files,
    )


# 自动初始化
init_tools()

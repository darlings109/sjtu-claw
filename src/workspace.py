"""Workspace — 工作区管理，包含 workspace、shell、approval、advanced tools"""
import os, subprocess, uuid, threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_workspace: Optional[Path] = None
_ws_lock = threading.Lock()

def get_workspace() -> Optional[Path]:
    with _ws_lock: return _workspace

def set_workspace(s: str) -> str:
    global _workspace
    with _ws_lock:
        p = Path(s).resolve()
        p.mkdir(parents=True, exist_ok=True)
        _workspace = p
        return f"Workspace set: {_workspace}"

def clear_workspace():
    global _workspace
    with _ws_lock: _workspace = None

def safe_resolve(s: str) -> Optional[Path]:
    ws = get_workspace()
    if ws is None: return None
    p = (ws / s).resolve()
    try: p.relative_to(ws); return p
    except ValueError: return None

# Shell
_shell: Optional[subprocess.Popen] = None
_shell_cwd: Optional[str] = None

def new_shell() -> str:
    global _shell, _shell_cwd
    ws = get_workspace()
    if ws is None: return "Error: workspace not set"
    if _shell:
        try: _shell.terminate(); _shell.wait(timeout=5)
        except: pass
    _shell_cwd = str(ws)
    _shell = subprocess.Popen(["bash"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=_shell_cwd, text=True)
    return f"Shell started at {_shell_cwd}"

def run_command(cmd: str, timeout: int = 30) -> str:
    global _shell, _shell_cwd
    if _shell is None: return "Error: no shell, call new_shell first"
    try:
        import select
        _shell.stdin.write(cmd + "\n")
        _shell.stdin.flush()
        out, err = _shell.communicate(timeout=timeout)
        return (out + err).strip()[:50000] or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: timeout"
    except Exception as e:
        _shell = None
        return f"Error: {e}"

def close_shell() -> str:
    global _shell, _shell_cwd
    if _shell:
        try: _shell.terminate(); _shell.wait(timeout=5)
        except: pass
        _shell = None
    _shell_cwd = None
    return "Shell closed"

# Approval
_apps: Dict[str, Dict] = {}
_app_events: Dict[str, threading.Event] = {}

def create_approval(tool: str, args: Dict) -> str:
    aid = f"app_{uuid.uuid4().hex[:8]}"
    _apps[aid] = {"approval_id": aid, "tool": tool, "args": args}
    _app_events[aid] = threading.Event()
    return aid

def list_approvals() -> List[Dict]:
    return [v for k, v in _apps.items() if k in _app_events and not _app_events[k].is_set()]

def approve(aid: str) -> bool:
    if aid not in _apps: return False
    _app_events[aid].set()
    return True

def reject(aid: str) -> bool:
    if aid not in _apps: return False
    _app_events[aid].set()
    return True

def wait_approval(aid: str, t: int = 300) -> bool:
    ev = _app_events.get(aid)
    if ev is None: return False
    return ev.wait(timeout=t)

def cleanup_approval(aid: str):
    _apps.pop(aid, None); _app_events.pop(aid, None)

# File tools
def create_file(path: str, content: str) -> str:
    r = safe_resolve(path)
    if r is None:
        return "Error: path outside workspace or workspace not set"
    try: r.parent.mkdir(parents=True, exist_ok=True); r.write_text(content); return f"Created {path} ({len(content)} bytes)"
    except Exception as e: return f"Error: {e}"

def overwrite_file(path: str, content: str) -> str:
    r = safe_resolve(path)
    if r is None: return "Error: path outside workspace or workspace not set"
    if not r.exists(): return f"Error: file not found {path}"
    try: r.write_text(content); return f"Overwritten {path} ({len(content)} bytes)"
    except Exception as e: return f"Error: {e}"

def edit_file(path: str, old_text: str, new_text: str) -> str:
    r = safe_resolve(path)
    if r is None: return "Error: path outside workspace or workspace not set"
    if not r.exists(): return f"Error: file not found {path}"
    try:
        t = r.read_text()
        if old_text not in t: return f"Error: text not found in {path}"
        r.write_text(t.replace(old_text, new_text, 1)); return f"Edited {path}"
    except Exception as e: return f"Error: {e}"



# Attachment copy
def copy_attachment_to_workspace(attachment_path: str, dest_path: str) -> str:
    """将 Gateway 上传的附件拷贝到 workspace"""
    from src.web.server import ATTACHMENTS_DIR

    ws = get_workspace()
    if ws is None:
        return "Error: Workspace not set"

    # attachment_path: "<session_id>/<filename>"
    parts = attachment_path.split("/")
    if len(parts) != 2:
        return "Error: attachment path format should be <session_id>/<filename>"

    session_id, filename = parts
    src = ATTACHMENTS_DIR / session_id / filename
    if not src.exists():
        return f"Error: attachment not found: {attachment_path}"

    resolved = safe_resolve(dest_path)
    if resolved is None:
        return f"Error: destination path outside workspace: {dest_path}"

    try:
        import shutil
        resolved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(resolved))
        return f"Copied attachment {attachment_path} to {dest_path} ({src.stat().st_size} bytes)"
    except Exception as e:
        return f"Error: {e}"

# Download registry
_downloads: Dict[str, Path] = {}
_downloads_lock = threading.Lock()

def create_download(path: str) -> str:
    """为 workspace 内文件创建临时下载入口"""
    r = safe_resolve(path)
    if r is None:
        return "Error: path outside workspace or workspace not set"
    if not r.exists():
        return f"Error: file not found: {path}"
    if not r.is_file():
        return f"Error: not a file: {path}"

    import uuid
    download_id = f"dl_{uuid.uuid4().hex[:12]}"
    with _downloads_lock:
        _downloads[download_id] = r
    return f"Download created: /api/downloads/{download_id}  (file: {path}, {r.stat().st_size} bytes)"


def get_download_path(download_id: str) -> Optional[Path]:
    """获取下载文件的实际路径"""
    with _downloads_lock:
        return _downloads.get(download_id)

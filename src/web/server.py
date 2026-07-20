"""
SJTUClaw Gateway — HTTP Server

使用 python 内置 http.server，提供 API + 静态文件服务。
"""

import json
import mimetypes
import os
import re
import sys
import threading
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import process_and_compact
from src.config import load_config
from src.session_store import list_sessions, load_session, create_session, delete_session, save_session

_config = None
STATIC_DIR = Path(__file__).resolve().parent / "static"
ATTACHMENTS_DIR = Path("data") / "attachments"


def _parse_multipart(body: bytes, content_type: str):
    """解析 multipart/form-data，提取文件名和文件内容

    Returns:
        (filename, data) 或 (None, None) 如果解析失败
    """
    match = re.search(r'boundary=(.+)', content_type)
    if not match:
        return None, None
    boundary = match.group(1).strip().strip('"')

    # 按 boundary 分割
    delimiter = b'--' + boundary.encode()
    parts = body.split(delimiter)

    for part in parts:
        if b'Content-Disposition' not in part:
            continue
        # 提取文件名
        name_match = re.search(r'filename="([^"]*)"', part.decode('utf-8', errors='replace'))
        if not name_match:
            continue
        filename = name_match.group(1)
        if not filename:
            continue
        # 提取文件内容（找到两个换行之后的数据）
        header_end = part.find(b'\r\n\r\n')
        if header_end == -1:
            continue
        file_data = part[header_end + 4:]
        # 去掉末尾的换行
        file_data = file_data.rstrip(b'\r\n')
        return filename, file_data
    return None, None


def _read_attachment_content(session_id: str, filename_key: str, max_chars: int = 60000) -> str:
    """读取附件内容为文本

    Args:
        session_id: 会话 ID
        filename_key: 文件名（含 uuid 后缀的存储名）
        max_chars: 最大读取字符数

    Returns:
        文件内容文本，二进制文件返回提示
    """
    file_path = ATTACHMENTS_DIR / session_id / filename_key
    if not file_path.exists():
        return f"(file not found: {filename_key})"

    # 判断是否为文本文件
    text_exts = {'.txt', '.md', '.json', '.py', '.js', '.html', '.css', '.xml', '.yaml', '.yml',
                 '.csv', '.ini', '.cfg', '.conf', '.log', '.sh', '.bat', '.ps1', '.env',
                 '.toml', '.sql', '.java', '.ts', '.tsx', '.jsx', '.c', '.cpp', '.h', '.hpp'}
    ext = file_path.suffix.lower()

    if ext not in text_exts and not _is_probably_text(file_path):
        return f"(binary file: {filename_key}, {file_path.stat().st_size} bytes)"

    try:
        text = file_path.read_text(encoding='utf-8', errors='replace')
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... (truncated, {len(text)} total chars)"
        return text
    except Exception as e:
        return f"(error reading file: {e})"


def _is_probably_text(path: Path) -> bool:
    """快速判断文件是否可能是文本文件（读取前 1024 字节）"""
    try:
        with open(path, 'rb') as f:
            chunk = f.read(1024)
        # 检查是否有空字节
        return b'\x00' not in chunk
    except Exception:
        return False

class GatewayHandler(SimpleHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # --- API routes (first match wins) ---

        # Health
        if path == '/api/health':
            return self._json({"status": "ok"})

        # List pending approvals
        if path == '/api/approvals':
            from src.workspace import list_approvals
            return self._json(list_approvals())

        # List skills
        if path == '/api/skills':
            from src.skill_registry import scan_skills
            return self._json(scan_skills())

        # Get workspace
        if path == '/api/workspace':
            from src.workspace import get_workspace
            ws = get_workspace()
            return self._json({"workspace": str(ws) if ws else None})

        # List tasks
        if path == '/api/tasks':
            from src.scheduler import list_tasks
            return self._json(list_tasks())

        # List sessions
        if path == '/api/sessions':
            sessions = list_sessions()
            return self._json([{
                "session_id": s.session_id,
                "title": s.title,
                "message_count": s.message_count,
                "updated_at": s.updated_at,
            } for s in sessions])

        # Download file
        if path.startswith('/api/downloads/'):
            dl_id = self._path_segment(path, 2)
            from src.workspace import get_download_path
            file_path = get_download_path(dl_id)
            if file_path is None:
                return self._json({"error": "download not found"}, 404)
            try:
                data = file_path.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Disposition', 'attachment; filename="' + file_path.name + '"')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            return

        # Get individual attachment
        if '/attachments/' in path:
            parts = path.split('/api/sessions/')[1].split('/')
            sid = parts[0]
            filename = parts[2]
            file_path = ATTACHMENTS_DIR / sid / filename
            if not file_path.exists():
                return self._json({"error": "not found"}, 404)
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        # List session attachments
        if path.endswith('/attachments'):
            sid = path.split('/api/sessions/')[1].split('/')[0]
            attach_dir = ATTACHMENTS_DIR / sid
            if not attach_dir.exists():
                return self._json([])
            items = []
            for f in attach_dir.iterdir():
                if f.is_file():
                    # 从 原始名_uuid8.ext 还原原始名
                    fname = f.name
                    original = re.sub(r'_[a-f0-9]{8}(\.[^.]+)$', r'\1', fname)
                    items.append({"filename": fname, "original_name": original, "size": f.stat().st_size})
            return self._json(items)

        # Session detail
        if path.startswith('/api/sessions/'):
            sid = path.split('/api/sessions/')[1].split('/')[0]
            session = load_session(sid)
            if session is None:
                return self._json({"error": "not found"}, 404)
            return self._json({
                "session_id": session.session_id,
                "title": session.title,
                "messages": [{"role": m["role"], "content": m["content"]} for m in session.messages],
                "message_count": session.message_count,
            })

        # Static files (fallback)
        if path == '/':
            path = '/index.html'
        return super().do_GET()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # DELETE /api/workspace
        if path == '/api/workspace':
            from src.workspace import clear_workspace
            clear_workspace()
            return self._json({"status": "cleared"})

        # DELETE /api/sessions/<id>
        if path.startswith('/api/sessions/'):
            sid = path.split('/api/sessions/')[1].split('/')[0]
            # DELETE /api/sessions/<id>/attachments/<filename>
            if '/attachments/' in path:
                from urllib.parse import unquote
                filename = unquote(path.split('/attachments/')[1].split('/')[0])
                file_path = ATTACHMENTS_DIR / sid / filename
                import os as _os
                print(f"[DELETE] sid={sid} filename={repr(filename)} exists={file_path.exists()}")
                if file_path.exists():
                    # 列出目录内容对比
                    print(f"[DELETE] dir={_os.listdir(str(ATTACHMENTS_DIR / sid))}")
                if not file_path.exists():
                    return self._json({"error": "not found", "filename": filename}, 404)
                file_path.unlink()
                return self._json({"status": "deleted", "filename": filename})
            # DELETE /api/sessions/<id>
            if delete_session(sid):
                return self._json({"status": "deleted", "session_id": sid})
            else:
                return self._json({"error": "not found or cannot delete"}, 404)

        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # POST /api/sessions — create new session
        if path == '/api/sessions':
            session = create_session()
            return self._json({
                "session_id": session.session_id,
                "title": session.title,
                "message_count": 0,
            }, 201)

        # POST /api/workspace — set workspace
        if path == '/api/workspace':
            body = self._read_json()
            from src.workspace import set_workspace
            result = set_workspace(body.get('path', ''))
            return self._json({"result": result})

        # POST /api/tasks — create task
        if path == '/api/tasks':
            body = self._read_json()
            from src.scheduler import create_task
            task = create_task(body.get('content',''), body.get('trigger_time',''), body.get('session_id',''), body.get('repeat_rule',''))
            if task:
                return self._json(task, 201)
            return self._json({"error": "invalid task params"}, 400)

        # POST /api/approvals/<id>/approve or /reject
        if path.startswith('/api/approvals/'):
            parts = path.split('/api/approvals/')[1].split('/')
            if len(parts) >= 2:
                aid = parts[0]
                action = parts[1]
                from src.workspace import approve as do_approve, reject as do_reject
                if action == 'approve':
                    return self._json({"status": "approved" if do_approve(aid) else "not found"})
                elif action == 'reject':
                    return self._json({"status": "rejected" if do_reject(aid) else "not found"})
            return self._json({"error": "invalid approval path"}, 400)

        # Extract session_id from path for session-scoped routes
        if not path.startswith('/api/sessions/'):
            return self._json({"error": "not found"}, 404)

        sid = path.split('/api/sessions/')[1].split('/')[0]

        # POST .../rename
        if '/rename' in path:
            session = load_session(sid)
            if session is None:
                return self._json({"error": "session not found"}, 404)
            body = self._read_json()
            title = body.get('title', '').strip()
            if title:
                session.title = title
                save_session(session)
                return self._json({"status": "renamed", "session_id": sid, "title": title})
            return self._json({"error": "title required"}, 400)

        # POST .../attachments — upload file (multipart/form-data)
        if '/attachments' in path and not '/messages' in path:
            content_type = self.headers.get('Content-Type', '')
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                return self._json({"error": "no data"}, 400)
            body = self.rfile.read(content_length)

            filename, file_data = _parse_multipart(body, content_type)
            if filename is None:
                # 兼容旧格式：纯 binary body，用 UUID 命名
                file_data = body
                safe_name = uuid.uuid4().hex
            else:
                # 保留原始文件名，加 uuid 短尾防重
                stem, ext = os.path.splitext(filename)
                safe_name = f"{stem}_{uuid.uuid4().hex[:8]}{ext}"

            attach_dir = ATTACHMENTS_DIR / sid
            attach_dir.mkdir(parents=True, exist_ok=True)
            (attach_dir / safe_name).write_bytes(file_data)
            return self._json({
                "filename": safe_name,
                "original_name": filename or safe_name,
                "size": len(file_data),
                "path": f"{sid}/{safe_name}",
            }, 201)

        # POST .../messages/stream — SSE streaming
        if '/messages/stream' in path:
            session = load_session(sid)
            if session is None:
                return self._json({"error": "session not found"}, 404)
            body = self._read_json()
            content_text = body.get('content', '').strip()
            if not content_text:
                return self._json({"error": "content required"}, 400)

            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()

            from src.agent import _run_agent_stream
            try:
                for event in _run_agent_stream(_config, session, content_text):
                    line = 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
                    self.wfile.write(line.encode('utf-8'))
                    self.wfile.flush()
            except Exception as e:
                err = json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False)
                self.wfile.write(('data: ' + err + '\n\n').encode('utf-8'))
                self.wfile.flush()
            return

        # POST .../messages — send message (default fallback)
        if '/messages' in path:
            session = load_session(sid)
            if session is None:
                return self._json({"error": "session not found"}, 404)
            body = self._read_json()
            content = body.get('content', '').strip()
            if not content:
                return self._json({"error": "content required"}, 400)
            # 将附件列表注入到消息中，让 model 知道
            attachments = body.get('attachments', [])
            if attachments:
                parts = ["[The user has attached the following files — content is already provided below, no need to read them again:]"]
                for fname in attachments:
                    file_content = _read_attachment_content(sid, fname)
                    parts.append(f"--- {fname} ---\n{file_content}")
                attach_info = "\n".join(parts)
                content = attach_info + "\n\n" + content
            try:
                reply = process_and_compact(_config, session, content)
                return self._json({"reply": reply, "session_id": session.session_id})
            except Exception as e:
                return self._json({"reply": f"[API Error] {str(e)[:200]}", "session_id": session.session_id})

        return self._json({"error": "not found"}, 404)

    def _path_segment(self, path: str, index: int) -> str:
        """Extract a segment from a /api/xxx/yyy/zzz path by 0-based index"""
        parts = [p for p in path.split('/') if p]
        return parts[index] if index < len(parts) else ""

    def _read_json(self):
        """Read and parse JSON request body"""
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length == 0:
                return {}
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            return {}

    def _json(self, data, status=200):
        data_bytes = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data_bytes)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data_bytes)

    def log_message(self, format, *args):
        print(f"[gateway] {args[0]} {args[1]} {args[2]}")

    # Fix: override the path for static file serving
    def translate_path(self, path):
        if path == '/index.html' or path == '/':
            return str(STATIC_DIR / 'index.html')
        # Only serve from static dir
        if path.startswith('/'):
            path = path[1:]
        target = STATIC_DIR / path
        if target.exists() and target.is_relative_to(STATIC_DIR):
            return str(target)
        return str(STATIC_DIR / 'index.html')

_scheduler = None

def main():
    global _config, _scheduler
    try:
        _config = load_config()
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    # Start scheduler engine
    from src.scheduler import SchedulerEngine
    from src.agent import process_message
    _scheduler = SchedulerEngine(_config, process_message)
    _scheduler.start()

    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    server = ThreadingHTTPServer(('127.0.0.1', port), GatewayHandler)
    print(f"Gateway: http://localhost:{port}")
    print(f"Web UI:  http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping gateway...")

if __name__ == '__main__':
    main()

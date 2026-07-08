"""
SJTUClaw Gateway — HTTP Server

使用 python 内置 http.server，提供 API + 静态文件服务。
"""

import json
import os
import sys
import threading
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


class GatewayHandler(SimpleHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # List pending approvals
        if path == '/api/approvals':
            from src.workspace import list_approvals
            approvals = list_approvals()
            return self._json(approvals)

        if path == '/api/health':
            return self._json({"status": "ok"})

        if path == '/api/sessions':
            sessions = list_sessions()
            return self._json([{
                "session_id": s.session_id,
                "title": s.title,
                "message_count": s.message_count,
                "updated_at": s.updated_at,
            } for s in sessions])

        if path.startswith('/api/sessions/') and path.endswith('/messages'):
            return self._json({"error": "use POST"}, 405)

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

        # Download files
        if path.startswith('/api/downloads/'):
            dl_id = path.split('/api/downloads/')[1].split('/')[0]
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
        if path.startswith('/api/sessions/') and '/attachments/' in path:
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
        if path.startswith('/api/sessions/') and path.endswith('/attachments'):
            sid = path.split('/api/sessions/')[1].split('/')[0]
            attach_dir = ATTACHMENTS_DIR / sid
            if not attach_dir.exists():
                return self._json([])
            items = []
            for f in attach_dir.iterdir():
                if f.is_file():
                    items.append({"filename": f.name, "size": f.stat().st_size})
            return self._json(items)

        # Static files
        if path == '/':
            path = '/index.html'
        return super().do_GET()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # DELETE /api/sessions/<id>
        if path.startswith('/api/sessions/'):
            sid = path.split('/api/sessions/')[1].split('/')[0]
            if delete_session(sid):
                return self._json({"status": "deleted", "session_id": sid})
            else:
                return self._json({"error": "not found or cannot delete"}, 404)

        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/sessions':
            session = create_session()
            return self._json({
                "session_id": session.session_id,
                "title": session.title,
                "message_count": 0,
            }, 201)

        # POST /api/sessions/<id>/rename
        if '/rename' in path:
            sid = path.split('/api/sessions/')[1].split('/')[0]
            session = load_session(sid)
            if session is None:
                return self._json({"error": "session not found"}, 404)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            except Exception:
                return self._json({"error": "invalid JSON"}, 400)
            title = body.get('title', '').strip()
            if title:
                session.title = title
                save_session(session)
                return self._json({"status": "renamed", "session_id": sid, "title": title})
            return self._json({"error": "title required"}, 400)

        # POST /api/sessions/<id>/attachments
        if path.endswith('/attachments'):
            # This route should be before /messages to avoid conflict
            sid = path.split('/api/sessions/')[1].split('/')[0]
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                return self._json({"error": "no data"}, 400)
            body = self.rfile.read(content_length)
            import uuid
            attach_dir = ATTACHMENTS_DIR / sid
            attach_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{uuid.uuid4().hex}"
            (attach_dir / filename).write_bytes(body)
            return self._json({"filename": filename, "size": len(body), "path": f"{sid}/{filename}"}, 201)

        # POST /api/sessions/<id>/messages
        if '/messages' in path:
            sid = path.split('/api/sessions/')[1].split('/')[0]
            session = load_session(sid)
            if session is None:
                return self._json({"error": "session not found"}, 404)

            try:
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            except Exception:
                return self._json({"error": "invalid JSON"}, 400)

            content = body.get('content', '').strip()
            if not content:
                return self._json({"error": "content required"}, 400)

            try:
                reply = process_and_compact(_config, session, content)
                return self._json({"reply": reply, "session_id": session.session_id})
            except Exception as e:
                return self._json({"reply": f"[API Error] {str(e)[:200]}", "session_id": session.session_id})

        # POST /api/approvals/<id>/approve or /reject
        if path.startswith('/api/approvals/'):
            parts = path.split('/api/approvals/')[1].split('/')
            if len(parts) >= 2:
                aid = parts[0]
                action = parts[1]
                from src.workspace import approve as do_approve, reject as do_reject
                if action == 'approve':
                    ok = do_approve(aid)
                    return self._json({"status": "approved" if ok else "not found"})
                elif action == 'reject':
                    ok = do_reject(aid)
                    return self._json({"status": "rejected" if ok else "not found"})

        return self._json({"error": "not found"}, 404)

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
    server = ThreadingHTTPServer(('0.0.0.0', port), GatewayHandler)
    print(f"Gateway: http://localhost:{port}")
    print(f"Web UI:  http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping gateway...")


if __name__ == '__main__':
    main()

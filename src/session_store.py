"""Session Store — 会话管理与持久化

每个 session 保存为 data/sessions/<sessionId>.json。
支持并发读写的 session 级线程锁。
"""

import json
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.config import ROOT_DIR


SESSIONS_DIR = ROOT_DIR / "data" / "sessions"
_sess_locks: Dict[str, threading.RLock] = {}
_sess_locks_lock = threading.Lock()


def _get_sess_lock(session_id: str) -> threading.Lock:
    """获取 session 线程锁"""
    with _sess_locks_lock:
        if session_id not in _sess_locks:
            _sess_locks[session_id] = threading.RLock()
        return _sess_locks[session_id]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_dir() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"


def append_message(session_id: str, role: str, content: str) -> bool:
    """原子操作：追加消息到 session（线程安全）"""
    lock = _get_sess_lock(session_id)
    with lock:
        session = load_session(session_id)
        if session is None:
            return False
        session.messages.append({"role": role, "content": content})
        session.updated_at = _now()
        path = _session_path(session_id)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"[错误] 保存 session {session_id} 失败：{e}", file=__import__("sys").stderr)
            return False
        return True



class Session:
    """单个会话的数据模型"""

    def __init__(
        self,
        session_id: str,
        title: str = "",
        messages: Optional[List[Dict[str, str]]] = None,
        summary: str = "",
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
    ):
        self.session_id = session_id
        self.title = title or "新会话"
        self.messages = messages or []
        self.summary = summary
        self.created_at = created_at or _now()
        self.updated_at = updated_at or _now()

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "messages": self.messages,
            "summary": self.summary,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Session":
        return cls(
            session_id=data["session_id"],
            title=data.get("title", "新会话"),
            messages=data.get("messages", []),
            summary=data.get("summary", ""),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    @property
    def message_count(self) -> int:
        return len(self.messages)


# ============================================================
# Session 备份与恢复（Session 类定义之后）
# ============================================================

BACKUP_DIR = SESSIONS_DIR / ".backups"
MAX_BACKUP_COPIES = 3

def _backup_session(session_id: str) -> None:
    """保存 session 备份，保留最近 MAX_BACKUP_COPIES 份"""
    src = _session_path(session_id)
    if not src.exists():
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        import shutil
        shutil.copy2(src, BACKUP_DIR / f"{session_id}_{ts}.json")
        backups = sorted(BACKUP_DIR.glob(f"{session_id}_*.json"))
        for old_file in backups[:-MAX_BACKUP_COPIES]:
            old_file.unlink()
    except OSError:
        pass


def recover_session(session_id: str) -> Optional[Session]:
    """从备份恢复损坏的 session"""
    if not BACKUP_DIR.exists():
        return None
    backups = sorted(BACKUP_DIR.glob(f"{session_id}_*.json"))
    if not backups:
        return None
    for backup in reversed(backups):
        try:
            data = json.loads(backup.read_text())
            print(f"[恢复] session {session_id} 从 {backup.name} 恢复", file=__import__("sys").stderr)
            return Session.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            continue
    print(f"[错误] session {session_id} 所有备份均损坏", file=__import__("sys").stderr)
    return None


def list_sessions() -> List[Session]:
    """列出所有已保存的 session"""
    _ensure_dir()
    sessions = []
    for f in sorted(SESSIONS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.suffix == ".json":
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                sessions.append(Session.from_dict(data))
            except (json.JSONDecodeError, KeyError, OSError) as e:
                print(f"[警告] session 文件损坏：{f.name} — {e}", file=__import__("sys").stderr)
    return sessions


def load_session(session_id: str) -> Optional[Session]:
    """加载指定 session（线程安全）"""
    path = _session_path(session_id)
    if not path.exists():
        return None
    lock = _get_sess_lock(session_id)
    with lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Session.from_dict(data)
        except (json.JSONDecodeError, KeyError, OSError) as e:
            print(f"[错误] 加载 session {session_id} 失败：{e}", file=__import__("sys").stderr)
            recovered = recover_session(session_id)
            if recovered:
                return recovered
            return None


def save_session(session: Session) -> None:
    """保存 session 到本地文件（线程安全）"""
    _ensure_dir()
    session.updated_at = _now()
    path = _session_path(session.session_id)
    lock = _get_sess_lock(session.session_id)
    with lock:
        _backup_session(session.session_id)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"[错误] 保存 session {session.session_id} 失败：{e}", file=__import__("sys").stderr)


def delete_session(session_id: str) -> bool:
    """删除指定 session"""
    path = _session_path(session_id)
    if not path.exists():
        return False
    lock = _get_sess_lock(session_id)
    with lock:
        try:
            path.unlink()
            return True
        except OSError as e:
            print(f"[错误] 删除 session {session_id} 失败：{e}", file=__import__("sys").stderr)
            return False


def create_session(title: str = "") -> Session:
    """创建新 session"""
    existing = list_sessions()
    ids = []
    for s in existing:
        sid = s.session_id
        if sid.startswith("session_"):
            try:
                ids.append(int(sid.split("_")[1]))
            except ValueError:
                pass
    next_num = max(ids) + 1 if ids else 1
    session_id = f"session_{next_num:03d}"
    session = Session(session_id=session_id, title=title or "新会话")
    save_session(session)
    return session

"""Scheduler — 定时任务服务

管理一次性任务和周期性任务，到期时调用已有 agent loop。
任务持久化存储在 data/tasks/ 目录。
"""

import json
import time
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.config import ROOT_DIR, LLMConfig

TASKS_DIR = ROOT_DIR / "data" / "tasks"
CHECK_INTERVAL = 10

# 时区锚定：读取 .env 中的 TZ 配置，默认 Asia/Shanghai
# 所有任务时间存储为 UTC，展示时转换到本地时区
LOCAL_TZ = timezone(timedelta(hours=8))  # China Standard Time (UTC+8)
UTC_TZ = timezone.utc


def _now_utc() -> str:
    """返回当前 UTC 时间的 ISO 字符串"""
    return datetime.now(UTC_TZ).isoformat(timespec="seconds")


def _now_local() -> str:
    """返回当前本地时间的 ISO 字符串（带时区偏移）"""
    return datetime.now(LOCAL_TZ).isoformat(timespec="seconds")


def _to_utc(dt: datetime) -> datetime:
    """将本地时间转换为 UTC"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(UTC_TZ)


def _to_local(dt: datetime) -> datetime:
    """将 UTC 时间转换为本地时间"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    return dt.astimezone(LOCAL_TZ)


def _now() -> str:
    """（兼容旧接口）返回当前 UTC 时间"""
    return _now_utc()


def _ensure_dir():
    TASKS_DIR.mkdir(parents=True, exist_ok=True)


def _task_path(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.json"


def _next_id() -> str:
    tasks = list_tasks()
    ids = []
    for t in tasks:
        tid = t.get("task_id", "")
        if tid.startswith("task_"):
            try:
                ids.append(int(tid.split("_")[1]))
            except ValueError:
                pass
    next_num = max(ids) + 1 if ids else 1
    return f"task_{next_num:03d}"


def _parse_interval(rule: str) -> Optional[int]:
    rule = rule.strip().lower()
    if rule.endswith("s") and rule[:-1].isdigit():
        return int(rule[:-1])
    if rule.endswith("m") and rule[:-1].isdigit():
        return int(rule[:-1]) * 60
    if rule.endswith("h") and rule[:-1].isdigit():
        return int(rule[:-1]) * 3600
    if rule.endswith("d") and rule[:-1].isdigit():
        return int(rule[:-1]) * 86400
    try:
        return int(rule)
    except ValueError:
        return None


def _parse_time(time_str: str) -> Optional[datetime]:
    """解析时间字符串，返回本地时区 datetime

    支持格式：
        +30m / +1h / +7d — 相对当前本地时间
        2026-07-20 10:00  — 绝对时间（视为本地时区）
        22:00              — 当日时间（视为本地时区）
    """
    ts = time_str.strip()
    if ts.startswith("+") or (ts[-1] in "smhd" and ts[0].isdigit()):
        seconds = _parse_interval(ts if not ts.startswith("+") else ts[1:])
        if seconds is not None:
            return datetime.now(LOCAL_TZ) + timedelta(seconds=seconds)
        return None
    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%H:%M"]:
        try:
            dt = datetime.strptime(ts, fmt)
            if fmt == "%H:%M":
                dt = dt.replace(year=datetime.now(LOCAL_TZ).year,
                                month=datetime.now(LOCAL_TZ).month,
                                day=datetime.now(LOCAL_TZ).day)
                if dt.replace(tzinfo=LOCAL_TZ) < datetime.now(LOCAL_TZ):
                    dt += timedelta(days=1)
            return dt.replace(tzinfo=LOCAL_TZ)
        except ValueError:
            continue
    return None


def _next_trigger(dt: datetime, rule: str) -> Optional[str]:
    seconds = _parse_interval(rule)
    if seconds is None:
        return None
    # dt 是本地时区时间，加上间隔后转 UTC 存储
    next_dt = dt + timedelta(seconds=seconds)
    return _to_utc(next_dt).isoformat(timespec="seconds")


# --- CRUD ---

def create_task(content: str, trigger_time: str, session_id: str, repeat_rule: str = "") -> Optional[Dict]:
    dt_local = _parse_time(trigger_time)
    if dt_local is None:
        return None
    if repeat_rule and _parse_interval(repeat_rule) is None:
        return None

    dt_utc = _to_utc(dt_local)

    _ensure_dir()
    task_id = _next_id()
    task = {
        "task_id": task_id,
        "content": content,
        "session_id": session_id,
        "trigger_at": dt_utc.isoformat(timespec="seconds"),
        "trigger_at_local": dt_local.isoformat(timespec="seconds"),
        "timezone": "Asia/Shanghai",
        "repeat_rule": repeat_rule,
        "status": "pending",
        "repeat_count": 0,
        "history": [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    with open(_task_path(task_id), "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    return task


def list_tasks() -> List[Dict]:
    _ensure_dir()
    tasks = []
    for f in sorted(TASKS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.suffix == ".json":
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    tasks.append(json.load(fh))
            except (json.JSONDecodeError, OSError):
                pass
    return tasks


def get_task(task_id: str) -> Optional[Dict]:
    path = _task_path(task_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_task(task: Dict) -> None:
    task["updated_at"] = _now()
    with open(_task_path(task["task_id"]), "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)


def cancel_task(task_id: str) -> bool:
    task = get_task(task_id)
    if task is None:
        return False
    task["status"] = "cancelled"
    save_task(task)
    return True


def delete_task(task_id: str) -> bool:
    path = _task_path(task_id)
    if not path.exists():
        return False
    path.unlink()
    return True


# --- Engine ---

class SchedulerEngine:
    def __init__(self, config: LLMConfig, agent_func: Callable):
        self._config = config
        self._agent_func = agent_func
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print(f"[scheduler] started (interval: {CHECK_INTERVAL}s)")

    def stop(self):
        self._running = False

    def _run_loop(self):
        while self._running:
            try:
                self._check_tasks()
            except Exception as e:
                print(f"[scheduler] error: {e}")
            time.sleep(CHECK_INTERVAL)

    def _check_tasks(self):
        now_utc = datetime.now(UTC_TZ)
        for task in list_tasks():
            if task["status"] != "pending":
                continue
            trigger = task.get("trigger_at", "")
            if not trigger:
                continue
            try:
                dt = datetime.fromisoformat(trigger)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC_TZ)
            except (ValueError, TypeError):
                continue
            if dt > now_utc:
                continue
            self._execute_task(task)

    def _execute_task(self, task: Dict):
        tid = task["task_id"]
        content = task["content"]
        sid = task["session_id"]

        task["status"] = "running"
        save_task(task)

        from src.session_store import load_session, save_session as save_sess
        session = load_session(sid)
        if session is None:
            task["status"] = "failed"
            task["history"].append({"time": _now(), "error": f"Session {sid} not found"})
            save_task(task)
            return

        print(f"[scheduler] exec {tid}: {content[:80]}")
        try:
            reply = self._agent_func(self._config, session, content)
            task["history"].append({"time": _now(), "content": content, "reply": (reply or "")[:500]})
            task["repeat_count"] = task.get("repeat_count", 0) + 1

            if task.get("repeat_rule"):
                next_time = _next_trigger(datetime.now(LOCAL_TZ), task["repeat_rule"])
                if next_time:
                    task["trigger_at"] = next_time
                    task["status"] = "pending"
                else:
                    task["status"] = "completed"
            else:
                task["status"] = "completed"

            save_task(task)
            print(f"[scheduler] {tid} done")
        except Exception as e:
            task["status"] = "failed"
            task["history"].append({"time": _now(), "error": str(e)})
            save_task(task)
            print(f"[scheduler] {tid} failed: {e}")

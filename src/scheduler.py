"""Scheduler — 定时任务服务

管理一次性任务和周期性任务，到期时调用已有 agent loop。
任务持久化存储在 data/tasks/ 目录。
"""

import json
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.config import ROOT_DIR, LLMConfig

TASKS_DIR = ROOT_DIR / "data" / "tasks"
CHECK_INTERVAL = 10


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
    ts = time_str.strip()
    if ts.startswith("+") or (ts[-1] in "smhd" and ts[0].isdigit()):
        seconds = _parse_interval(ts if not ts.startswith("+") else ts[1:])
        if seconds is not None:
            return datetime.now() + timedelta(seconds=seconds)
        return None
    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%H:%M"]:
        try:
            dt = datetime.strptime(ts, fmt)
            if fmt == "%H:%M":
                dt = dt.replace(year=datetime.now().year, month=datetime.now().month, day=datetime.now().day)
                if dt < datetime.now():
                    dt += timedelta(days=1)
            return dt
        except ValueError:
            continue
    return None


def _next_trigger(dt: datetime, rule: str) -> Optional[str]:
    seconds = _parse_interval(rule)
    if seconds is None:
        return None
    return (dt + timedelta(seconds=seconds)).isoformat(timespec="seconds")


# --- CRUD ---

def create_task(content: str, trigger_time: str, session_id: str, repeat_rule: str = "") -> Optional[Dict]:
    dt = _parse_time(trigger_time)
    if dt is None:
        return None
    if repeat_rule and _parse_interval(repeat_rule) is None:
        return None

    _ensure_dir()
    task_id = _next_id()
    task = {
        "task_id": task_id,
        "content": content,
        "session_id": session_id,
        "trigger_at": dt.isoformat(timespec="seconds"),
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
        now = datetime.now()
        for task in list_tasks():
            if task["status"] != "pending":
                continue
            trigger = task.get("trigger_at", "")
            if not trigger:
                continue
            try:
                dt = datetime.fromisoformat(trigger)
            except (ValueError, TypeError):
                continue
            if dt > now:
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
                next_time = _next_trigger(datetime.now(), task["repeat_rule"])
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

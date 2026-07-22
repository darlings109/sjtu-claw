"""Scheduler 端到端验证脚本

测试流程：
  1. 清理旧任务
  2. 创建任务（+20 秒后触发）
  3. 启动 SchedulerEngine
  4. 等待触发
  5. 检查任务是否被执行
  6. 清理

Usage:
    python tests/test_scheduler.py
"""

import sys
import time
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.scheduler import create_task, get_task, delete_task, SchedulerEngine
from src.config import load_config
from src.session_store import create_session, delete_session

TEST_DELAY = 20  # seconds


def test_scheduler_e2e():
    print("=" * 60)
    print("Scheduler 端到端验证")
    print("=" * 60)

    # 0. 清理旧任务
    print(f"\n[1/5] 清理旧任务数据...")
    from pathlib import Path
    from src.scheduler import TASKS_DIR
    if TASKS_DIR.exists():
        for f in TASKS_DIR.iterdir():
            if f.suffix == ".json":
                f.unlink()

    # 1. 创建 session
    print(f"\n[2/5] 创建测试 session...")
    session = create_session()
    sid = session.session_id
    print(f"  session_id: {sid}")

    # 2. 创建任务
    print(f"\n[3/5] 创建定时任务（+{TEST_DELAY}s）...")
    task = create_task(
        content="[scheduler test] 请回复：Scheduler 定时任务验证通过 ✅",
        trigger_time=f"+{TEST_DELAY}s",
        session_id=sid,
        repeat_rule="",
    )
    if task is None:
        print("  ❌ 任务创建失败")
        return False
    tid = task["task_id"]
    print(f"  task_id: {tid}")
    print(f"  trigger_at: {task['trigger_at']} (UTC)")
    print(f"  trigger_at_local: {task['trigger_at_local']}")
    print(f"  content: {task['content'][:60]}")

    # 3. 启动 scheduler
    print(f"\n[4/5] 启动 SchedulerEngine...")
    config = load_config()

    # Fake agent function that records being called
    call_log = {"called": False, "args": None, "reply": ""}

    def test_agent(cfg, sess, user_content):
        call_log["called"] = True
        call_log["args"] = (cfg is not None, sess.session_id, user_content[:100])
        # Return a fake reply (no real LLM call needed)
        call_log["reply"] = f"[test mock] received: {user_content[:60]}..."
        print(f"  🤖 Agent called: {user_content[:80]}")
        return call_log["reply"]

    engine = SchedulerEngine(config, test_agent)
    engine.start()

    # 4. 等待触发
    print(f"  ⏳ 等待最多 {TEST_DELAY + 10}s...")
    waited = 0
    max_wait = TEST_DELAY + 15
    while waited < max_wait:
        time.sleep(2)
        waited += 2
        task_data = get_task(tid)
        if task_data is None:
            print(f"  ❌ 任务文件丢失（waited {waited}s）")
            engine.stop()
            delete_session(sid)
            return False

        status = task_data.get("status", "unknown")
        history = task_data.get("history", [])
        local_trigger = task_data.get("trigger_at_local", "?")
        print(f"  [{waited:2d}s] status={status:12s} history={len(history)} trigger_local={local_trigger}")

        if call_log["called"]:
            print(f"\n  ✅ Agent 已被调用！")
            print(f"  reply: {call_log['reply']}")
            break

        if status == "failed":
            error_msg = history[-1].get("error", "unknown") if history else "unknown"
            print(f"\n  ❌ 任务执行失败: {error_msg}")
            engine.stop()
            delete_session(sid)
            return False

    engine.stop()

    # 5. 检查结果
    print(f"\n[5/5] 检查结果...")
    if call_log["called"]:
        print(f"  ✅ Agent 被调用: yes")
        print(f"  ✅ 调用的 content: {call_log['args'][2][:80]}")
        print(f"  ✅ 返回值: {call_log['reply']}")
        final_task = get_task(tid)
        if final_task:
            print(f"  最终状态: {final_task['status']}")
            print(f"  历史记录: {len(final_task.get('history', []))} 条")
        print(f"\n{'='*60}")
        print("✅ Scheduler 端到端验证通过！")
        print(f"{'='*60}")
        result = True
    else:
        print(f"  ❌ Agent 未被调用（waited {waited}s）")
        print(f"\n{'='*60}")
        print("❌ Scheduler 端到端验证失败")
        print(f"{'='*60}")
        result = False

    # 6. 清理
    delete_task(tid)
    delete_session(sid)
    print(f"\n  清理完成: task={tid} session={sid}")

    return result


if __name__ == "__main__":
    success = test_scheduler_e2e()
    sys.exit(0 if success else 1)

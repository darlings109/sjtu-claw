"""Claw — 最小 Agent Runtime 入口

启动命令：
    python -m src.main
"""

import json
import re
import sys

from src.config import load_config
from src.agent import process_message
from src.memory_store import add_memory, delete_memory, list_memories
from src.scheduler import create_task, list_tasks, get_task, cancel_task
from src.session_store import (
    Session,
    list_sessions,
    load_session,
    create_session,
    delete_session,
    save_session,
)


def _parse_command_args(raw_args: str):
    """解析命令参数，兼容 <id> 和 cmd<arg> 格式"""
    raw = raw_args.strip()
    parts = raw.split()
    if not parts:
        return []
    result = []
    for p in parts:
        # cmd<arg> 格式 → cmd + arg
        m = re.match(r"^(\w+)<(.+)>$", p)
        if m:
            result.append(m.group(1))
            result.append(m.group(2))
        else:
            # 去掉单个 token 的尖括号包装
            result.append(p.strip("<>"))
    return result


def print_sessions(sessions, current_id: str) -> None:
    """打印 session 列表"""
    print("Sessions:")
    for s in sessions:
        marker = "*" if s.session_id == current_id else " "
        print(f"  {marker} {s.session_id:15s} {s.title:12s} messages={s.message_count:<4d} updated={s.updated_at}")


def handle_session_command(session: Session, raw_input: str) -> Session:
    """处理 /session 命令，返回（可能切换后的）当前 session"""
    # 剥离 /session 前缀（容错拼写）
    cleaned = re.sub(r"^/\w+", "", raw_input.strip()).strip()
    parts = _parse_command_args(cleaned)

    if not parts:
        print("用法: /session new | list | switch <id> | rename [id] <title> | delete <id>")
        return session

    cmd = parts[0]

    if cmd == "new":
        session = create_session()
        print(f"Created session: {session.session_id}")
        return session

    elif cmd == "list":
        all_sessions = list_sessions()
        print_sessions(all_sessions, session.session_id)
        return session

    elif cmd == "switch":
        if len(parts) < 2:
            print("用法: /session switch <sessionId>")
            return session
        target = load_session(parts[1])
        if target is None:
            print(f"Session {parts[1]} 不存在。")
            return session
        print(f"Switched to session: {target.session_id}")
        if target.messages:
            print("History:")
            for msg in target.messages:
                role_char = msg["role"].capitalize()
                preview = msg["content"][:80]
                if len(msg["content"]) > 80:
                    preview += "..."
                print(f"  {role_char}> {preview}")
        return target

    elif cmd == "rename":
        if len(parts) < 2:
            print("用法: /session rename [sessionId] <title>  （省略 sessionId 则重命名当前 session）")
            return session
        if len(parts) == 2:
            # 只有 title → 重命名当前 session
            session.title = parts[1]
            save_session(session)
            print(f"当前 session 已重命名为: {session.title}")
        else:
            # sessionId + title
            target = load_session(parts[1])
            if target is None:
                print(f"Session {parts[1]} 不存在。")
                return session
            target.title = " ".join(parts[2:])
            save_session(target)
            print(f"Session {target.session_id} 已重命名为: {target.title}")
        return session

    elif cmd == "delete":
        if len(parts) < 2:
            print("用法: /session delete <sessionId>")
            return session
        if parts[1] == session.session_id:
            print("不能删除当前 session。请先切换到其他 session。")
            return session
        if delete_session(parts[1]):
            print(f"Session {parts[1]} 已删除。")
        else:
            print(f"Session {parts[1]} 不存在。")
        return session

    # 兼容不带参数的 /session（等同于 /session list）
    print("用法: /session new | list | switch <id> | rename [id] <title> | delete <id>")
    return session


def handle_memory_command(session: Session, raw_input: str) -> Session:
    """处理 /memory 命令"""
    # 剥离 /memory 前缀
    cleaned = re.sub(r"^/\w+", "", raw_input.strip()).strip()
    parts = _parse_command_args(cleaned)

    if not parts:
        print("用法: /memory add <content> | list | delete <id>")
        return session

    cmd = parts[0]

    if cmd == "add":
        if len(parts) < 2:
            print("用法: /memory add <content>")
            return session
        content = " ".join(parts[1:])
        mem_id = add_memory(content)
        print(f"Added memory: {mem_id}")

    elif cmd == "list":
        memories = list_memories()
        if not memories:
            print("没有记忆。")
        else:
            print("Memories:")
            for m in memories:
                print(f"  {m['memory_id']}: {m['content'][:80]}")

    elif cmd == "delete":
        if len(parts) < 2:
            print("用法: /memory delete <id>")
            return session
        if delete_memory(parts[1]):
            print(f"Memory {parts[1]} 已删除。")
        else:
            print(f"Memory {parts[1]} 不存在。")

    else:
        print(f"未知 memory 命令: {cmd}")

    return session


def main() -> None:
    """主入口：多轮对话 Loop"""
    # 读取配置
    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    # 启动 scheduler
    from src.scheduler import SchedulerEngine
    from src.agent import process_message
    _scheduler = SchedulerEngine(config, process_message)
    _scheduler.start()

    # 恢复或创建 session
    all_sessions = list_sessions()
    if all_sessions:
        current = all_sessions[0]
        print(f"Resumed session: {current.session_id}")
    else:
        current = create_session()
        print(f"Created session: {current.session_id}")

    print("Type /exit to quit, /session for session management, /memory for memories.\n")

    while True:
        try:
            user_input = input(f"{current.session_id}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            save_session(current)
            break

        if not user_input:
            continue

        # 退出
        if user_input == "/exit":
            print("bye.")
            save_session(current)
            break

        # session 命令（容错拼写）
        if re.match(r"^/sess", user_input):
            current = handle_session_command(current, user_input)
            print()
            continue

        # memory 命令（容错拼写）
        if re.match(r"^/mem", user_input):
            current = handle_memory_command(current, user_input)
            print()
            continue

        # workspace 命令
        if re.match(r"^/workspace", user_input):
            current = handle_workspace_command(current, user_input)
            print()
            continue

        # approval 命令
        if re.match(r"^/approve|^/reject", user_input):
            current = handle_workspace_command(current, user_input)
            print()
            continue

        # skill 命令
        if re.match(r"^/skill", user_input):
            handle_skill_command(config, current, user_input)
            print()
            continue

        # scheduler 命令
        if re.match(r"^/task", user_input):
            handle_task_command(config, current, user_input)
            print()
            continue

        # 手动压缩命令
        if user_input == "/compact":
            from src.agent import compact_now
            compact_now(config, current)
            print()
            continue

        # 以 / 开头的未知命令 → 提示，不发给 LLM
        if user_input.startswith("/"):
            print(f"未知命令: {user_input.split()[0]}  可用命令: /exit /session /memory\n")
            continue

        # 处理普通消息
        try:
            from src.agent import process_and_compact
            reply = process_and_compact(config, current, user_input)
            print(f"Assistant> {reply}\n")
        except (ConnectionError, ValueError) as e:
            print(f"[错误] {e}\n", file=sys.stderr)
        except Exception as e:
            print(f"[错误] 未知异常：{e}\n", file=sys.stderr)


def handle_skill_command(config, session: Session, raw_input: str) -> Session:
    """处理 /skill 命令"""
    cleaned = re.sub(r"^/\w+", "", raw_input.strip()).strip()
    parts = cleaned.split(maxsplit=1)

    from src.skill_registry import scan_skills, load_skill

    if not parts:
        print("Usage: /skill list | show <name> | <name> <task>")
        return session

    cmd = parts[0]

    if cmd == "list":
        skills = scan_skills()
        if not skills:
            print("No skills found.")
        else:
            print("Available skills:")
            for s in skills:
                print(f"  {s['name']}: {s['description']}")
        return session

    if cmd == "show":
        if len(parts) < 2:
            print("Usage: /skill show <name>")
            return session
        skill_name = parts[1]
        content_s = load_skill(skill_name)
        if content_s is None:
            print(f"Skill not found: {skill_name}")
        else:
            print(f"--- {skill_name} ---")
            print(content_s)
        return session

    if cmd == "usage":
        print("Skill usage tracking not yet implemented.")
        return session

    # /skill <name> <task>
    skill_name = cmd
    task = parts[1] if len(parts) > 1 else ""
    skill_content = load_skill(skill_name)
    if skill_content is None:
        print(f"Skill not found: {skill_name}. Use /skill list to see available skills.")
        return session

    # Load skill and inject into context
    enhanced_content = "[Using skill: " + skill_name + "]\n\n" + skill_content + "\n\n---\n\nUser task: " + task if task else "[Using skill: " + skill_name + "]\n" + skill_content
    from src.agent import process_and_compact
    try:
        reply = process_and_compact(config, session, enhanced_content)
        print(f"Assistant> {reply}")

        # Record skill usage in session
        if not hasattr(session, "skill_usage"):
            session.skill_usage = []
        session.skill_usage.append({
            "skill": skill_name,
            "task": task,
            "source": "explicit",
            "time": __import__("datetime").datetime.now().isoformat(),
        })
    except Exception as e:
        print(f"[Error] {e}")
    return session


def handle_workspace_command(session: Session, raw_input: str) -> Session:
    """处理 /workspace 和 /approve /reject 命令"""
    cleaned = re.sub(r"^/\w+", "", raw_input.strip()).strip()
    parts = cleaned.split()

    # /workspace
    if raw_input.startswith("/workspace"):
        if not parts:
            from src.workspace import get_workspace
            ws = get_workspace()
            print(f"Current workspace: {ws or '(not set)'}")
            return session
        if parts[0] == "set":
            from src.workspace import set_workspace
            print(set_workspace(" ".join(parts[1:])))
        elif parts[0] == "clear":
            from src.workspace import clear_workspace
            clear_workspace()
            print("Workspace cleared.")
        else:
            print("Usage: /workspace | /workspace set <path> | /workspace clear")
        return session

    # /approve <id>
    if raw_input.startswith("/approve"):
        if not parts:
            print("Usage: /approve <id> [reason]")
            return session
        from src.workspace import approve
        if approve(parts[0]):
            print(f"Approved: {parts[0]}")
        else:
            print(f"Approval {parts[0]} not found")
        return session

    # /reject <id>
    if raw_input.startswith("/reject"):
        if not parts:
            print("Usage: /reject <id> [reason]")
            return session
        from src.workspace import reject
        if reject(parts[0]):
            print(f"Rejected: {parts[0]}")
        else:
            print(f"Approval {parts[0]} not found")
        return session

    return session


def handle_task_command(config, session, raw_input: str) -> None:
    """处理 /task 命令"""
    cleaned = re.sub(r"^/\w+", "", raw_input.strip()).strip()
    parts = _parse_command_args(cleaned)
    if not parts:
        print("用法: /task new <content> <time> [repeat] | list | cancel <id>")
        return

    cmd = parts[0]
    if cmd == "new":
        if len(parts) < 3:
            print("用法: /task new <content> <time> [repeat]")
            print("示例: /task new 提醒我写报告 +30m 或 /task new 整理代码 22:00 1d")
            return
        content = parts[1]
        trigger = parts[2]
        repeat = parts[3] if len(parts) > 3 else ""
        result = create_task(content, trigger, session.session_id, repeat)
        if result is None:
            print("无法创建任务：时间格式或重复规则无效")
        else:
            print(f"Created task: {result['task_id']} (trigger: {result['trigger_at']})")

    elif cmd == "list":
        tasks = list_tasks()
        if not tasks:
            print("没有任务。")
        else:
            print("Tasks:")
            for t in tasks:
                print(f"  {t['task_id']:12s} {t['status']:10s} trigger={t['trigger_at']} content={t['content'][:40]}")

    elif cmd == "cancel":
        if len(parts) < 2:
            print("用法: /task cancel <taskId>")
            return
        if cancel_task(parts[1]):
            print(f"Task {parts[1]} 已取消。")
        else:
            print(f"Task {parts[1]} 不存在。")

    elif cmd == "show":
        if len(parts) < 2:
            print("用法: /task show <taskId>")
            return
        t = get_task(parts[1])
        if t is None:
            print(f"Task {parts[1]} 不存在。")
        else:
            print(json.dumps(t, ensure_ascii=False, indent=2))
    else:
        print("用法: /task new <content> <time> [repeat] | list | cancel <id> | show <id>")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in ("gateway", "--gateway", "server"):
        sys.argv.pop(1)
        from src.web.server import main as gateway_main
        gateway_main()
    else:
        main()

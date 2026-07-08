"""Basic tests for SJTUClaw core modules"""
import sys
sys.path.insert(0, ".")

def test_session_create():
    from src.session_store import create_session
    s = create_session("test")
    assert s.title == "test"
    assert s.session_id.startswith("session_")
    print(f"  OK create_session: {s.session_id}")

def test_session_save_load():
    from src.session_store import create_session, load_session, save_session
    s = create_session("save-test")
    s.messages.append({"role": "user", "content": "hello"})
    save_session(s)
    s2 = load_session(s.session_id)
    assert s2.message_count == 1
    print(f"  OK save/load: {s2.message_count} msg")

def test_memory_crud():
    from src.memory_store import add_memory, list_memories, delete_memory
    mid = add_memory("test memory", "manual")
    memories = list_memories()
    assert any(m["memory_id"] == mid for m in memories)
    delete_memory(mid)
    memories = list_memories()
    assert not any(m["memory_id"] == mid for m in memories)
    print("  OK memory CRUD")

def test_tool_registry():
    from src.tool_registry import get_registry
    r = get_registry()
    assert "current_time" in r.tool_names
    result = r.execute("current_time", {})
    assert len(result) > 5
    print(f"  OK tool registry: {len(r.tool_names)} tools")

def test_workspace():
    from src.workspace import set_workspace, get_workspace, safe_resolve
    set_workspace(".")
    assert get_workspace() is not None
    assert safe_resolve("src") is not None
    assert safe_resolve("/etc/passwd") is None
    print("  OK workspace: safe_resolve works")

def test_compactor():
    from src.compactor import snip_compact, should_snip
    msgs = [{"role": "user", "content": f"msg-{i}"} for i in range(60)]
    assert should_snip(msgs)
    result = snip_compact(msgs)
    assert len(result) < len(msgs)
    print(f"  OK compactor: {len(msgs)} -> {len(result)}")

if __name__ == "__main__":
    print("Running tests...")
    test_session_create()
    test_session_save_load()
    test_memory_crud()
    test_tool_registry()
    test_workspace()
    test_compactor()
    print("All tests passed!")

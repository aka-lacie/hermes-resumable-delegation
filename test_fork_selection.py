"""The advertised fork choice controls actual child context and durable history."""
import json

import pytest


@pytest.mark.parametrize("surface", ["registry", "inline"])
def test_spawn_exposes_fork_choice_and_keeps_fresh_child_isolated(harness, surface):
    from agent.subagent_context import bind_fork_source
    from hermes_cli.plugins import get_plugin_manager
    from tools import delegate_tool
    from tools.registry import registry

    make_parent, db, observed, _ = harness
    parent = make_parent()
    schema = delegate_tool._build_dynamic_schema_overrides()
    task_props = schema["parameters"]["properties"]["tasks"]["items"]["properties"]
    assert task_props["fork_context"]["type"] == "boolean"
    assert task_props["fork_context"]["default"] is True
    # The parent must not simultaneously be told that every child has no history.
    assert "Children know nothing of this conversation" not in schema["description"]
    assert "knows nothing about your conversation history" not in task_props["goal"]["description"]
    args = {"tasks": [
        {"goal": "Use the default context choice"},
        {"goal": "Fork explicitly", "fork_context": True},
        {"goal": "Review independently", "fork_context": False, "context": "Only this supplied evidence"},
    ]}
    history = [{"role": "user", "content": "PARENT_REQUIREMENT"},
               {"role": "assistant", "content": "PARENT_CONCLUSION", "finish_reason": "stop"}]
    with bind_fork_source(parent, history):
        raw = (parent._dispatch_delegate_task(args) if surface == "inline" else
               registry.get_entry("delegate_task").handler(args, parent_agent=parent))
    response = json.loads(raw)
    assert all(row["status"] == "completed" for row in response["results"]), response
    sessions = {row["session_id"]: row for row in observed}
    for index, result in enumerate(response["results"]):
        sid = result["session_id"]
        expected_fork = index < 2
        for messages in (sessions[sid]["history"], db.get_messages_as_conversation(sid)):
            content = json.dumps(messages)
            assert ("PARENT_REQUIREMENT" in content) is expected_fork
            assert ("PARENT_CONCLUSION" in content) is expected_fork
        if not expected_fork:
            assert "Only this supplied evidence" in sessions[sid]["prompt"]
    # Extension edits must not mutate the host schema seen after unload.
    get_plugin_manager().unload("resumable-delegation")
    native = delegate_tool._build_dynamic_schema_overrides()
    native_task = native["parameters"]["properties"]["tasks"]["items"]["properties"]
    assert "fork_context" not in native_task
    assert "Children know nothing of this conversation" in native["description"]
    parent.close()


@pytest.mark.parametrize("source", ["task", "policy", "policy_exception"])
def test_invalid_fork_policy_refuses_batch_before_copying_history(harness, monkeypatch, source):
    from agent.subagent_extension import get_subagent_extension
    from tools.registry import registry

    make_parent, _, observed, children = harness
    parent = make_parent()
    parent._session_messages = [{"role": "user", "content": "Private parent context"}]
    tasks = [{"goal": "Valid first task"}, {"goal": "Invalid second task"}]
    if source == "task":
        tasks[1]["fork_context"] = "false"
    else:
        extension = get_subagent_extension()
        original = extension.child_options
        def options(task):
            result = original(task)
            if task["goal"] == "Invalid second task":
                if source == "policy_exception":
                    raise RuntimeError("Cannot determine child policy")
                result["fork_context"] = "false"
            return result
        monkeypatch.setattr(extension, "child_options", options)
    handler = registry.get_entry("delegate_task").handler
    refused = json.loads(handler({"tasks": tasks}, parent_agent=parent))
    assert refused.get("error"), refused
    assert not observed and not children
    assert json.loads(handler({"action": "list"}, parent_agent=parent))["subagents"] == []
    parent.close()

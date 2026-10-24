"""The advertised fork choice controls actual child context and durable history."""
import json
from copy import deepcopy

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
    history = [
        {"role": "user", "content": "PARENT_REQUIREMENT", "_db_persisted": True, "_row_id": 4},
        {"role": "assistant", "content": "PARENT_CONCLUSION", "finish_reason": "stop", "reasoning": "PRIVATE_REASONING"},
        {"role": "assistant", "content": "COMPACTION_HANDOFF", "_compressed_summary": True, "finish_reason": "incomplete"},
        {"role": "user", "content": [{"type": "text", "text": "CURRENT_REQUEST"}]},
        {"role": "user", "content": "RECOVERY_SCAFFOLDING", "_empty_recovery_synthetic": True},
        {"role": "assistant", "content": "PARTIAL_ANSWER", "finish_reason": "incomplete"},
        {"role": "assistant", "content": "SPAWN_ROUND", "tool_calls": [
            {"id": "a", "function": {"name": "delegate_task", "arguments": "{}"}},
            {"id": "b", "function": {"name": "delegate_task", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "a", "content": "SIBLING_RESULT"},
    ]
    original = deepcopy(history)
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
            assert ("COMPACTION_HANDOFF" in content) is expected_fork
            assert ("CURRENT_REQUEST" in content) is expected_fork
            assert all(marker not in content for marker in (
                "PRIVATE_REASONING", "RECOVERY_SCAFFOLDING", "PARTIAL_ANSWER", "SPAWN_ROUND", "SIBLING_RESULT"))
        if not expected_fork:
            assert "Only this supplied evidence" in sessions[sid]["prompt"]
    assert history == original
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


def test_formatter_can_preserve_completed_tools_and_select_per_child(harness, monkeypatch):
    from agent.subagent_context import bind_fork_source
    from agent.subagent_extension import get_subagent_extension
    from tools.registry import registry

    make_parent, db, observed, _ = harness
    parent = make_parent()
    source = [
        {"role": "user", "content": "Original request", "_db_persisted": True},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "read", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "read", "content": "Completed tool evidence"},
        {"role": "assistant", "content": "Conclusion", "reasoning": "Prior reasoning"},
        {"role": "user", "content": "Current ask"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "spawn", "type": "function", "function": {"name": "delegate_task", "arguments": "{}"}}]},
    ]
    original = deepcopy(source)
    calls = []
    def format_history(messages, *, task):
        assert messages == original  # every sibling gets the unformatted boundary
        calls.append(task["goal"])
        messages.pop()  # remove the unfinished spawn, retain the earlier tool exchange
        if task["goal"] == "Short format":
            return [{"role": "user", "content": "Plugin-authored summary"}]
        return messages
    monkeypatch.setattr(get_subagent_extension(), "format_fork_history", format_history)
    with bind_fork_source(parent, source):
        response = json.loads(registry.get_entry("delegate_task").handler(
            {"tasks": [{"goal": "Full format"}, {"goal": "Short format"}]}, parent_agent=parent))
    assert all(row["status"] == "completed" for row in response["results"]), response
    assert calls == ["Full format", "Short format"]
    full, short = [db.get_messages_as_conversation(row["session_id"]) for row in response["results"]]
    assert full[0]["content"] == "Original request"  # parent's persisted flag cannot suppress this write
    assert any(m.get("tool_calls", [{}])[0].get("id") == "read" for m in full if m.get("tool_calls"))
    assert any(m.get("tool_call_id") == "read" and m["content"] == "Completed tool evidence" for m in full)
    assert short[0]["content"] == "Plugin-authored summary"
    assert "Completed tool evidence" not in json.dumps(short)
    assert source == original
    assert len(observed) == 2
    def refuse_new_forks(messages, *, task):
        raise RuntimeError("New forks disabled")
    monkeypatch.setattr(get_subagent_extension(), "format_fork_history", refuse_new_forks)
    resumed = json.loads(registry.get_entry("delegate_task").handler(
        {"action": "resume", "session_id": response["results"][0]["session_id"], "message": "Continue"},
        parent_agent=parent))
    assert resumed["results"][0]["status"] == "completed", resumed
    assert "Completed tool evidence" in json.dumps(observed[-1]["history"])
    parent.close()


@pytest.mark.parametrize("invalid", ["wrong_type", "unmatched_result", "unfinished_call", "exception"])
def test_formatter_failure_refuses_entire_batch_before_allocation(harness, monkeypatch, invalid):
    from agent.subagent_extension import get_subagent_extension
    from tools.registry import registry

    make_parent, _, observed, children = harness
    parent = make_parent()
    def format_history(messages, *, task):
        if task["goal"] == "Valid first task":
            return [{"role": "user", "content": "Valid history"}]
        if invalid == "exception":
            raise RuntimeError("Formatter failed")
        return {"wrong_type": "not history", "unmatched_result": [
            {"role": "tool", "tool_call_id": "unknown", "content": "orphan"}], "unfinished_call": [
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "unfinished", "function": {"name": "read_file", "arguments": "{}"}}]}]}[invalid]
    monkeypatch.setattr(get_subagent_extension(), "format_fork_history", format_history)
    handler = registry.get_entry("delegate_task").handler
    response = json.loads(handler({"tasks": [{"goal": "Valid first task"}, {"goal": "Invalid second task"}]}, parent_agent=parent))
    assert response.get("error"), response
    assert not observed and not children
    assert json.loads(handler({"action": "list"}, parent_agent=parent))["subagents"] == []
    parent.close()

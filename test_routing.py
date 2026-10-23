"""Advertised per-child routes reach execution and survive parent reconstruction.

Selection is part of the plugin's public contract. Exercise actual host provider
resolution: a mocked credential resolver would miss leaking the default endpoint
or credentials into a child selected on another provider.
"""
import json

import pytest


@pytest.fixture
def routing(harness, monkeypatch):
    from hermes_cli.config import load_config
    from tools import delegate_tool, delegate_tool_config

    cfg = load_config()
    cfg["delegation"] = {
        "model": "default-model", "base_url": "http://127.0.0.1:2/v1",
        "api_key": "default-test-key", "api_mode": "chat_completions",
        "request_overrides": {"temperature": 0.9},
        "fallback_providers": [{"provider": "custom", "model": "default-fallback"}],
        "max_concurrent_children": 4,
    }
    cfg["providers"] = {"review-route": {
        "base_url": "http://127.0.0.1:3/v1", "api_key": "review-test-key",
        "api_mode": "codex_responses", "extra_body": {"temperature": 0.2},
    }}
    monkeypatch.setattr(delegate_tool, "_resolve_delegation_credentials",
                        delegate_tool_config._resolve_delegation_credentials)
    return harness, cfg


@pytest.mark.parametrize("surface", ["registry", "inline"])
def test_selected_routes_reach_children_and_resume_with_fresh_credentials(routing, surface):
    from tools import delegate_tool
    from tools.registry import registry

    (make_parent, _, observed, children), cfg = routing
    parent = make_parent()
    def call(args):
        if surface == "inline":
            return json.loads(parent._dispatch_delegate_task(args))
        return json.loads(registry.get_entry("delegate_task").handler(args, parent_agent=parent))

    # These are public arguments the parent must actually be offered, not merely
    # undocumented fields that happen to survive dispatch.
    props = delegate_tool._build_dynamic_schema_overrides()["parameters"]["properties"]
    assert {"model", "provider"} <= props["tasks"]["items"]["properties"].keys()
    assert "model" in props and "provider" not in props  # resume keeps its provider
    first = call({"tasks": [
        {"goal": "Review using defaults", "fork_context": False},
        {"goal": "Review with another model", "model": "fast-model", "fork_context": False},
        {"goal": "Review on another provider", "model": "review-model",
         "provider": "review-route", "fork_context": False},
    ]})
    assert all(row["status"] == "completed" for row in first["results"]), first
    by_model = {child.model: child for child in children}
    default, fast, selected = [by_model[name] for name in ("default-model", "fast-model", "review-model")]
    for child in (default, fast):
        assert child.base_url == cfg["delegation"]["base_url"]
        assert child.api_key == "default-test-key"
        assert child.request_overrides == {"temperature": 0.9}
    assert selected.base_url == "http://127.0.0.1:3/v1"
    assert selected.api_key == "review-test-key"
    assert selected.requested_provider == "review-route"
    assert selected.api_mode == "codex_responses"
    assert selected.request_overrides == {"extra_body": {"temperature": 0.2}}
    assert not selected._fallback_chain
    sid = selected.session_id
    parent.close()
    parent = make_parent()
    cfg["delegation"].update(model="unrelated-default", base_url="http://127.0.0.1:4/v1")
    cfg["providers"]["review-route"]["api_key"] = "rotated-review-test-key"
    second = call({"action": "resume", "session_id": sid, "message": "Review the follow-up",
                   "model": "review-next"})
    assert second["results"][0]["status"] == "completed", second
    resumed = children[-1]
    assert resumed.session_id == sid
    assert resumed.model == "review-next"
    assert resumed.requested_provider == "review-route"
    assert resumed.base_url == selected.base_url
    assert resumed.api_key == "rotated-review-test-key"
    assert "Review on another provider" in json.dumps(observed[-1]["history"])
    third = call({"action": "resume", "session_id": sid, "message": "One more check"})
    assert third["results"][0]["status"] == "completed", third
    assert children[-1].model == "review-next"
    parent.close()


@pytest.mark.parametrize("selection", [
    {"model": " "},
    {"provider": "review-route"},
    {"model": "review-model", "provider": "AUTO"},
    {"model": "review-model", "provider": "nonexistent-test-provider"},
])
def test_invalid_selection_refuses_batch_without_starting_or_retaining_children(routing, selection):
    from tools.registry import registry

    (make_parent, _, observed, children), _ = routing
    parent = make_parent()
    handler = registry.get_entry("delegate_task").handler
    refused = json.loads(handler({"tasks": [
        {"goal": "Valid first assignment", "model": "valid-model"},
        {"goal": "Invalid second assignment", **selection},
    ]}, parent_agent=parent))
    assert refused.get("error"), refused
    assert not observed and not children
    assert json.loads(handler({"action": "list"}, parent_agent=parent))["subagents"] == []
    parent.close()

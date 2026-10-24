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
        "backend": "per-task", "model": "default-model", "base_url": "http://127.0.0.1:2/v1",
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
    assert {"child_model", "child_provider"} <= props["tasks"]["items"]["properties"].keys()
    assert "model" in props and "provider" not in props  # resume keeps its provider
    first = call({"tasks": [
        {"goal": "Review using defaults", "fork_context": False},
        {"goal": "Review with another model", "child_model": "fast-model", "fork_context": False},
        {"goal": "Review on another provider", "child_model": "review-model",
         "child_provider": "review-route", "fork_context": False},
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
    assert not resumed._fallback_chain
    assert "Review on another provider" in json.dumps(observed[-1]["history"])
    third = call({"action": "resume", "session_id": sid, "message": "One more check"})
    assert third["results"][0]["status"] == "completed", third
    assert children[-1].model == "review-next"
    parent.close()


@pytest.mark.parametrize("selection", [
    {"child_model": " "},
    {"child_model": 42},
    {"child_provider": "review-route"},
    {"child_model": "review-model", "child_provider": "AUTO"},
    {"child_model": "review-model", "child_provider": "nonexistent-test-provider"},
])
def test_invalid_selection_refuses_only_that_child(routing, selection):
    from tools.registry import registry

    (make_parent, _, observed, children), _ = routing
    parent = make_parent()
    handler = registry.get_entry("delegate_task").handler
    refused = json.loads(handler({"tasks": [
        {"goal": "Valid first assignment", "child_model": "valid-model"},
        {"goal": "Invalid second assignment", **selection},
    ]}, parent_agent=parent))
    assert refused["results"][0]["status"] == "completed", refused
    assert refused["results"][1]["status"] == "error", refused
    assert len(observed) == len(children) == 1
    assert children[0].model == "valid-model"
    roster = json.loads(handler({"action": "list"}, parent_agent=parent))["subagents"]
    assert [row["session_id"] for row in roster] == [children[0].session_id]
    parent.close()


def test_backend_parameters_reach_retained_service_launch(routing):
    """The public retained API must accept the selected backend's vocabulary."""
    from agent.subagent_lifecycle import SubagentLifecycleService

    (make_parent, _, _, children), cfg = routing
    parent = make_parent()
    service = SubagentLifecycleService(lambda: parent)
    with pytest.raises(ValueError, match="backend-specific"):
        service.launch_session(goal="Ambiguous selector", task_parameters={"model": "ignored-model"})
    assert not children
    launched = service.launch_session(goal="Review through the plugin API", task_parameters={
        "child_model": "review-model", "child_provider": "review-route",
    })
    sid = launched["results"][0]["session_id"]
    assert children[-1].requested_provider == "review-route"
    assert children[-1].api_key == "review-test-key"
    # Continuation belongs to the saved route, even after changing routing strategy.
    cfg["delegation"]["backend"] = "default"
    resumed = service.resume_session(sid, "Continue the same review")
    assert resumed["results"][0]["session_id"] == sid
    assert children[-1].model == "review-model"
    assert children[-1].requested_provider == "review-route"
    parent.close()


def test_retention_composes_with_another_backend_without_advertising_our_selectors(harness, delegate_task):
    """Installing retention must not replace a user's routing backend or its schema."""
    from agent.delegation_provider import DelegationProvider
    from agent.subagent_extension import get_subagent_extension
    from hermes_cli.config import load_config
    from tools.delegate_tool import _build_dynamic_schema_overrides

    class Tiers(DelegationProvider):
        @property
        def name(self):
            return "test-tiers"

        def task_parameters(self, config):
            return {"tier": {"type": "string", "enum": ["deep"]}}

        def route_task(self, task, config):
            return {"model": "deep-model"} if task.get("tier") == "deep" else dict(config)

    make_parent, _, _, children = harness
    get_subagent_extension().ctx.register_delegation_provider(Tiers())
    load_config()["delegation"] = {"backend": "test-tiers"}
    parent = make_parent()
    props = _build_dynamic_schema_overrides()["parameters"]["properties"]["tasks"]["items"]["properties"]
    assert "tier" in props and "fork_context" in props
    assert not {"child_model", "child_provider", "model", "provider"} & props.keys()
    result = json.loads(delegate_task(tasks=[
        {"goal": "Use the installed strategy", "tier": "deep"},
        {"goal": "Reject a field from the inactive strategy", "child_model": "wrong-model"},
    ], parent_agent=parent))
    assert result["results"][0]["session_id"] == children[0].session_id
    assert children[0].model == "deep-model"
    assert result["results"][1]["status"] == "error"
    assert len(children) == 1
    parent.close()


@pytest.mark.parametrize("old_field", ["model", "provider"])
def test_stale_spawn_selectors_are_not_silently_ignored(harness, old_field, delegate_task):
    """An old cached tool call must be refused, never run on an unintended route."""

    make_parent, _, _, children = harness
    parent = make_parent()
    result = json.loads(delegate_task(tasks=[{"goal": "Old schema request", old_field: "old-selection"}],
                                      parent_agent=parent))
    assert "child_model" in result["error"] and "child_provider" in result["error"]
    assert not children
    parent.close()

"""Difficulty routing refuses malformed choices while preserving valid siblings."""
import json
from copy import deepcopy
import pytest


@pytest.mark.parametrize("bad", [
    {"difficulty": "unknown"}, {"difficulty": 3},
    {"difficulty": "hard"},
])
def test_invalid_difficulty_refuses_only_its_task(harness, bad):
    from hermes_cli.config import load_config
    from tools.delegate_tool import delegate_task
    make_parent, _, _, children = harness
    load_config()["delegation"] = {"backend": "per-task", "backends": {"per-task": {
        "difficulty_routes": {"easy": {"model": "small"}},
    }}}
    parent = make_parent()
    result = json.loads(delegate_task(tasks=[{"goal": "Valid sibling", "difficulty": "easy"},
                                             {"goal": "Invalid choice", **bad}], parent_agent=parent))
    assert result["results"][0]["status"] == "completed", result
    assert result["results"][1]["status"] == "error", result
    assert [c.model for c in children] == ["small"]
    parent.close()


@pytest.mark.parametrize("settings", [{"command": "bad-command"}, {"args": ["bad"]},
                                       {"reasoning_effort": "typo"}])
def test_invalid_route_settings_do_not_launch_a_child(harness, settings):
    from hermes_cli.config import load_config
    from tools.delegate_tool import delegate_task
    make_parent, _, _, children = harness
    load_config()["delegation"] = {"backend": "per-task", "backends": {"per-task": {
        "difficulty_routes": {"hard": settings},
    }}}
    parent = make_parent()
    result = json.loads(delegate_task(tasks=[{"goal": "Bad route", "difficulty": "hard"}], parent_agent=parent))
    assert result.get("error"), result
    assert not children
    parent.close()


def test_route_overlay_is_detached_from_profile_configuration(harness):
    from agent.delegation_registry import get_active_provider
    cfg = {"backend": "per-task", "model": "default", "reasoning_effort": "high", "backends": {"per-task": {
        "difficulty_routes": {"easy": {"reasoning_effort": False}, "hard": {
            "model": "large", "request_overrides": {"extra_body": {"value": 1}}, "fallback_providers": [],
        }},
    }}}
    original = deepcopy(cfg)
    provider = get_active_provider(cfg)
    assert provider.route_task({}, cfg)["model"] == "default"
    assert provider.route_task({"difficulty": "easy"}, cfg)["reasoning_effort"] is False
    route = provider.route_task({"difficulty": "hard"}, cfg)
    assert route["model"] == "large" and route["fallback_providers"] == []
    route["request_overrides"]["extra_body"]["value"] = 2
    assert cfg == original


@pytest.mark.parametrize("selected,blocks,expected", [
    ("resumable", {"resumable": "legacy-model"}, "legacy-model"),
    ("resumable", {"per-task": "new-model"}, "new-model"),
    ("per-task", {"resumable": "legacy-model"}, "legacy-model"),
    ("resumable", {"resumable": "legacy-model", "per-task": "new-model"}, "new-model"),
])
def test_renamed_backend_preserves_config_and_saved_session_routes(harness, selected, blocks, expected):
    from hermes_cli.config import load_config
    from tools.delegate_tool import delegate_task
    make_parent, _, _, children = harness
    cfg = load_config()
    cfg["delegation"] = {"backend": "per-task", "backends": {
        key: {"difficulty_routes": {"hard": {"model": model}}} for key, model in blocks.items()
    }}
    parent = make_parent()
    parent._delegation_backend = selected  # An existing session may still pin the earlier name.
    result = json.loads(delegate_task(tasks=[{"goal": "Use saved routing choice", "difficulty": "hard"}], parent_agent=parent))
    assert result["results"][0]["status"] == "completed", result
    assert [child.model for child in children] == [expected]
    parent.close()


def test_explicit_empty_canonical_settings_do_not_restore_legacy_difficulty(harness):
    from agent.delegation_registry import get_active_provider
    cfg = {"backend": "resumable", "backends": {"per-task": {}, "resumable": {
        "difficulty_routes": {"hard": {"model": "legacy-model"}},
    }}}
    assert "difficulty" not in get_active_provider(cfg).task_parameters(cfg)

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
    load_config()["delegation"] = {"backend": "resumable", "backends": {"resumable": {
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
    load_config()["delegation"] = {"backend": "resumable", "backends": {"resumable": {
        "difficulty_routes": {"hard": settings},
    }}}
    parent = make_parent()
    result = json.loads(delegate_task(tasks=[{"goal": "Bad route", "difficulty": "hard"}], parent_agent=parent))
    assert result.get("error"), result
    assert not children
    parent.close()


def test_route_overlay_is_detached_from_profile_configuration(harness):
    from agent.delegation_registry import get_active_provider
    cfg = {"backend": "resumable", "model": "default", "reasoning_effort": "high", "backends": {"resumable": {
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

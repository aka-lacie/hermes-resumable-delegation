"""Per-task routes reach real children without changing parent, siblings, or another profile."""

import json
from unittest.mock import patch

import hermes_yaml as yaml


def test_profile_routes_through_registry_and_real_children(tmp_path, monkeypatch):
    from agent.secret_scope import set_multiplex_active
    from gateway.run import _profile_runtime_scope
    from run_agent import AIAgent
    from tools import delegate_tool as dt
    from tools.delegate_tool_results import _child_route_metadata
    from tools.registry import registry

    from pathlib import Path
    from conftest import install_routing_plugin
    from hermes_state import SessionDB
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    homes = [tmp_path / "a", tmp_path / "b"]
    for i, home in enumerate(homes):
        home.mkdir()
        (home / "config.yaml").write_text(yaml.safe_dump({
            "compression": {"enabled": False},
            "terminal": {"cwd": str(home)},
            "delegation": {
                "model": f"default-{i}", "base_url": "http://127.0.0.1:1/v1", "api_key": "test-only",
                "reasoning_effort": "high", "max_concurrent_children": 4,
                "max_spawn_depth": 2, "orchestrator_enabled": True,
                "difficulty_routes": {
                    "easy": {"model": f"easy-{i}", "reasoning_effort": "max"},
                    "medium": {},
                    "hard": {"model": f"hard-{i}", "reasoning_effort": "high"},
                },
            },
        }))
    for home in homes:
        install_routing_plugin(home)
    monkeypatch.delenv("HERMES_IGNORE_USER_CONFIG", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(homes[0]))
    built = []

    def capture(batch, background):
        built.append(batch)
        return json.dumps({"routes": [_child_route_metadata(c) for _, _, c in batch.children]})

    monkeypatch.setattr(dt, "_run_batch", capture)  # stop only before the actual provider calls
    set_multiplex_active(True)
    try:
        with patch("agent.process_bootstrap.OpenAI"):
            for i in (0, 1, 0):
                with _profile_runtime_scope(homes[i]):
                    from hermes_cli.plugins import discover_plugins
                    discover_plugins(force=True)
                    db = SessionDB(db_path=homes[i] / "state.db")
                    original = (homes[i] / "config.yaml").read_bytes()
                    parent = AIAgent(
                        session_db=db, session_id="parent",
                        model="parent-model", provider="custom", base_url="http://127.0.0.1:1/v1", api_key="test-only",
                        reasoning_config={"enabled": True, "effort": "low"},
                        enabled_toolsets=["file", "delegation"], skip_memory=True, quiet_mode=True,
                    )
                    parent._ensure_db_session()
                    start = len(built)
                    try:
                        tasks = [{"goal": "Inspect a bounded component carefully", **({"difficulty": d} if d else {})}
                                 for d in ("easy", "medium", "hard", None)]
                        response = json.loads(registry.dispatch("delegate_task", {"tasks": tasks}, parent_agent=parent))
                        assert "error" not in response, response
                        batch = built[-1]
                        children = [c for _, _, c in batch.children]
                        assert [c.model for c in children] == [f"easy-{i}", f"default-{i}", f"hard-{i}", f"default-{i}"]
                        assert [c.reasoning_config["effort"] for c in children] == ["max", "high", "high", "high"]
                        assert parent.model == "parent-model" and parent.reasoning_config["effort"] == "low"
                        assert all("delegate_task" in c.valid_tool_names for c in children)
                        schema = dt._build_dynamic_schema_overrides()["parameters"]["properties"]["tasks"]
                        assert set(schema["items"]["properties"]["difficulty"]["enum"]) == {"easy", "medium", "hard"}
                        # An easy child can choose hard later; omitted difficulty returns to the profile default.
                        nested = json.loads(registry.dispatch("delegate_task", {"tasks": [
                            {"goal": "Investigate newly discovered complexity", "difficulty": "hard"},
                            {"goal": "Check an ordinary follow-up component"},
                        ]}, parent_agent=children[0]))
                        assert "error" not in nested, nested
                        leaves = [c for _, _, c in built[-1].children]
                        assert [c.model for c in leaves] == [f"hard-{i}", f"default-{i}"]
                        assert all("delegate_task" not in c.valid_tool_names for c in leaves)
                        assert children[0].model == f"easy-{i}" and children[0].reasoning_config["effort"] == "max"
                        assert (homes[i] / "config.yaml").read_bytes() == original
                        # The result distinguishes a fallback from the requested route.
                        children[0].model = "fallback-model"
                        from tools.delegate_tool_child_run import _fabricated_entry
                        entry = _fabricated_entry(0, "error", "provider stopped", children[0])
                        assert entry["model"] == "fallback-model"
                        assert entry["requested_model"] == f"easy-{i}"
                        assert entry["route"]["label"] == "easy"
                    finally:
                        for batch in reversed(built[start:]):
                            for _, _, child in reversed(batch.children):
                                from tools.delegate_tool_child_run import _close_child
                                _close_child(child, "test child cleanup")
                        parent.close()
                        db.close()
    finally:
        set_multiplex_active(False)

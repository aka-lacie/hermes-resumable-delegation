"""Shared native-plugin fixtures; run from the target Hermes checkout."""
import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path.cwd()))


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("TERMINAL_CWD", str(tmp_path))
    cfg = {"compression": {"enabled": False}, "plugins": {"enabled": ["resumable-delegation"], "entries": {"resumable-delegation": {"allow_tool_override": True}}},
           "terminal": {"cwd": str(tmp_path)}}
    monkeypatch.setattr("hermes_cli.config.load_config", lambda *a, **kw: cfg)
    monkeypatch.setattr("hermes_cli.config.load_config_readonly", lambda *a, **kw: cfg)
    import shutil
    from hermes_cli.plugins import discover_plugins, get_plugin_manager
    target = tmp_path / "plugins" / "resumable-delegation"
    shutil.copytree(Path(__file__).parent, target, ignore=shutil.ignore_patterns("test_*", "__pycache__", ".git", ".pytest_cache", ".ruff_cache"))
    (tmp_path / "config.yaml").write_text(json.dumps(cfg))
    discover_plugins(force=True)
    assert get_plugin_manager()._subagent_extensions
    from agent.turn_context import build_turn_context
    from hermes_state import SessionDB
    from run_agent import AIAgent
    observed = []
    children = []

    def run_conversation(child, user_message, conversation_history=None, task_id=None, **kwargs):
        from agent import conversation_loop as loop
        ctx = build_turn_context(
            child, user_message, None, conversation_history, task_id, None, None,
            restore_or_build_system_prompt=loop._restore_or_build_system_prompt,
            install_safe_stdio=loop._install_safe_stdio, sanitize_surrogates=loop._sanitize_surrogates,
            summarize_user_message_for_log=loop._summarize_user_message_for_log,
            set_session_context=loop.set_session_context, set_current_write_origin=loop.set_current_write_origin,
            ra=loop._ra,
        )
        observed.append({"session_id": child.session_id, "history": deepcopy(ctx.messages),
                         "model": child.model, "provider": child.provider, "tools": deepcopy(child.tools),
                         "prompt": child.ephemeral_system_prompt, "workspace": child._delegate_workspace})
        children.append(child)
        ctx.messages.append({"role": "assistant", "content": "Findings retained for follow-up."})
        child._flush_messages_to_session_db(ctx.messages, conversation_history)
        return {"final_response": "Findings retained for follow-up.", "completed": True,
                "messages": ctx.messages, "api_calls": 0}

    # Replace the external execution only; production construction, worker,
    # persistence prologue, result routing, registration and teardown remain.
    monkeypatch.setattr(AIAgent, "run_conversation", run_conversation)
    def credentials(route, parent):
        return {"provider": route.get("provider"), "model": route.get("model"),
                "base_url": "http://127.0.0.1:1/v1", "api_key": "test-key", "api_mode": "chat_completions"}
    monkeypatch.setattr("tools.delegate_tool._resolve_delegation_credentials", credentials)
    # This isolated host has no external completion consumer; exercise the
    # production synchronous fallback through both model-facing dispatch paths.
    monkeypatch.setattr("tools.delegate_tool_dispatch._resolve_async_wake_sid", lambda *args: None)
    with patch("agent.process_bootstrap.OpenAI"):
        db = SessionDB(db_path=tmp_path / "state.db")
        def parent(session_id="owner"):
            agent = AIAgent(api_key="test-key", base_url="http://127.0.0.1:1/v1", model="test/model",
                            provider="custom", enabled_toolsets=[], quiet_mode=True, skip_context_files=True,
                            skip_memory=True, session_db=db, session_id=session_id)
            agent._ensure_db_session()
            return agent
        yield parent, db, observed, children
        for child in children:
            child.close()
        db.close()

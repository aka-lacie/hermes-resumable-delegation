"""Retained delegation policy using only Hermes' documented plugin contracts."""
import json
from agent.subagent_extension import SubagentExtension
from .fork_context import conversation_snapshot
from .presentation import _roster_entry, extend_schema


class RetainedDelegation(SubagentExtension):
    def __init__(self, ctx):
        self.ctx = ctx

    @property
    def sessions(self):
        return self.ctx.subagent_lifecycle

    def enabled(self):
        return self.ctx.get_config("enabled", True) is True

    def child_options(self, task):
        if any(key in task for key in ("model", "provider")):
            raise ValueError("Spawn selectors moved to the per-task backend: use child_model/child_provider, "
                             "or the active backend's declared parameters. Start a new parent session to refresh tools.")
        title = str(task.get("title") or " ".join(str(task["goal"]).split())[:80]).strip() or "Delegated task"
        return {"retain": True, "fork_context": True,
                "review_skills": self.ctx.get_config("review_skills", True) is True, "title": title}

    def extend_schema(self, schema):
        schema["parameters"] = extend_schema(schema["parameters"])
        schema["description"] = schema["description"].replace(
            "Children know nothing of this conversation: pass everything needed via 'context', including any required ",
            "With fork_context=false, pass all needed background via 'context', including any required ")
        schema["description"] += (
            "\nNew children fork conversation context by default; tasks[].fork_context=false starts fresh. "
            "Forks include user turns, final answers and compaction summaries, excluding tool history and private reasoning."
            "\nSpawn routing uses the active delegation backend and its declared task parameters. "
            "On resume, only model can change within the saved provider."
            "\nCompleted children retain their conversations on disk. Resume by session_id with a new assignment; "
            "tools and skills refresh at activation. list shows recent running/idle children ordered by activity; "
            "query searches older retained sessions. observe reads without waking; close retires an idle child. "
            "There is no idle expiry. Supply changed context in your follow-up assignment.")
        return schema

    def format_fork_history(self, messages, *, task):
        return conversation_snapshot(messages)

    def format_assignment(self, message, *, session_id, timestamp):
        prefix = f"[Parent assignment at {timestamp}]\n"
        return prefix + message if isinstance(message, str) else [{"type": "text", "text": prefix}, *message]

    def handle_action(self, action, request):
        sid = request.get("session_id")
        if action in {"steer", "stop"} and not sid:
            return None  # Preserve native live-ID clients.
        handlers = {
            "list": lambda: self.sessions.list_sessions(query=request.get("query"), limit=request.get("limit", 20)),
            "observe": lambda: self.sessions.observe_session(sid, limit=request.get("limit", 20)),
            "close": lambda: self.sessions.close_session(sid),
            "resume": lambda: self.sessions.resume_session(sid, request.get("message"), model=request.get("model"),
                                                           background=request.get("background", False)),
            "steer": lambda: self.sessions.steer_session(sid, request.get("message")),
            "stop": lambda: self.sessions.stop_session(sid),
        }
        if action not in handlers:
            return None
        try:
            result = handlers[action]()
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        if action == "list":
            result["subagents"] = [_roster_entry(row) for row in result["subagents"]]
        elif action == "observe":
            result["session"] = _roster_entry(result["session"])
        elif action == "close":
            result = {"action": action, **_roster_entry(result)}
        return json.dumps(result, ensure_ascii=False)

"""Model-facing descriptions and bounded roster presentation."""

def _roster_entry(record):
    entry = {key: record[key] for key in ("session_id", "title", "assignment", "status", "created_at",
                                         "last_activity_at", "model", "provider")}
    entry["title"] = entry["title"][:120]
    if len(entry["assignment"]) > 500:
        entry["assignment"] = entry["assignment"][:500] + "…"
        entry["assignment_truncated"] = True
    return entry



def extend_schema(parameters):
    """Expose the session surface only in profiles that enable retained children."""
    from copy import deepcopy
    parameters = deepcopy(parameters)
    props = parameters["properties"]
    props.pop("subagent_id", None)
    props["action"] = {
        "type": "string", "enum": ["spawn", "resume", "list", "observe", "steer", "stop", "close"],
        "description": "Spawn a new child; resume an idle conversation; list recent running/idle children "
        "(query searches all retained children); observe history; steer/stop a running child; close an idle "
        "child permanently. Execution returns through the normal delegation completion path.",
    }
    props["session_id"] = {"type": "string", "description": "Stable child session ID from spawn, completion, or list."}
    props["message"] = {"type": "string", "description": "Next assignment for resume, or course correction for steer. "
                         "Supply relevant changes since the child's previous assignment."}
    props["model"] = {"type": "string", "description": "Optional resume model override within the saved provider."}
    props["query"] = {"type": "string", "description": "Search all your retained children, including older/closed sessions."}
    props["limit"] = {"type": "integer", "minimum": 1, "maximum": 100, "description": "Maximum list entries or observed messages (default 20)."}
    props["tasks"]["items"]["properties"]["title"] = {
        "type": "string", "description": "Optional short stable title. Defaults to a shortened initial assignment.",
    }
    props["tasks"]["items"]["properties"]["model"] = {
        "type": "string", "description": "Optional model for this new child, overriding delegation defaults. "
        "Keeps the selected provider unless provider is also supplied; no provider inference.",
    }
    props["tasks"]["items"]["properties"]["provider"] = {
        "type": "string", "description": "Optional configured provider for this new child; requires model. "
        "Use a specific provider name, not auto. Hermes resolves its credentials and transport from this profile. "
        "Omit to keep the configured delegation provider or inherit the parent's route.",
    }
    return parameters

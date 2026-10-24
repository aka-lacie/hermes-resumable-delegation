"""Conversation-only fork policy; the host supplies detached durable history."""
from copy import deepcopy


def conversation_snapshot(messages):

    result = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        summary = message.get("_compressed_summary") is True
        final = (
            role == "assistant" and not message.get("tool_calls")
            and message.get("finish_reason") in {None, "stop", "end_turn"}
        )
        if role != "user" and not final and not summary:
            continue
        # Rebuild instead of copying session row ids, persistence flags, opaque
        # reasoning signatures, usage anchors, or the parent's tool-call metadata.
        # Wire-only sidecars can contain recalled memory and request-hook injections.
        # A history fork carries durable conversation content, not those transient additions.
        content = message.get("content")
        if not content:
            continue
        row = {"role": role, "content": deepcopy(content)}
        for key in ("timestamp", "_compressed_summary", "_compressed_summary_has_user_turn"):
            if key in message:
                row[key] = deepcopy(message[key])
        if final:
            row["finish_reason"] = "stop"
        result.append(row)
    return result


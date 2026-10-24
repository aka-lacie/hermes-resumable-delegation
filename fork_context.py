"""Conversation-only fork policy; the host supplies detached durable history."""
from copy import deepcopy


def conversation_snapshot(messages):
    from agent.context_compressor import is_compaction_summary_message

    result = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        summary = is_compaction_summary_message(message)
        final = (
            role == "assistant" and not message.get("tool_calls")
            and message.get("finish_reason") in {None, "stop", "end_turn"}
        )
        if role != "user" and not final and not summary:
            continue
        # Rebuild instead of copying session row ids, persistence flags, opaque
        # reasoning signatures, usage anchors, or the parent's tool-call metadata.
        content = message.get("api_content")
        if content is None:
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


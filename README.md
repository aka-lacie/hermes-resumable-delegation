# Resumable delegation

An independently installable native Hermes plugin for parent-directed continuation
of delegated conversations. Idle children occupy disk, not a live agent. Each new
activation uses current tools, skills, instructions and credentials.

## Host requirements and enablement

This plugin requires the proposed retained-conversation host changes on
`feat/resumable-delegation` (validated at `b21e9cf3b77286adf7df3fc2d0c095767ae4e68f`,
based on upstream `e5eb6b36fe78eb012cefd1f5f436cd458411b8b3`). These changes are
not yet merged into upstream Hermes; an unpatched release is not supported.

Retained operations require a native SessionDB owner. Managed compute workers
using RuntimeSessionStore cannot currently retain conversations. The existing
worker restrictions remain enforced.


Requires the host's documented `ctx.register_subagent_extension` and
`ctx.subagent_lifecycle` conversation APIs. Older Hermes versions fail registration
with an explicit compatibility error. Currently requires in-process plugin loading;
Hermes refuses this extension under `plugins.isolation: host`.

Install the repository root as a native Hermes plugin named `resumable-delegation`,
then merge these settings with the
profile's existing configuration (do not replace other entries):

```yaml
plugins:
  enabled:
    - resumable-delegation
  entries:
    resumable-delegation:
      allow_tool_override: true
      settings:
        enabled: true
        review_skills: true
```

Both settings default to true when the plugin is enabled. `allow_tool_override`
is Hermes' existing operator consent gate for changing the built-in `delegate_task`
surface. The plugin preserves normal spawn routing, limits, completion delivery
and legacy live-ID controls. It does not replace or monkeypatch the execution engine.

## Model-facing interface

```json
{"tasks": [{"goal": "Review this PR", "title": "PR review", "fork_context": true}]}
{"action": "resume", "session_id": "<child ID>", "message": "I fixed the race; review the updated diff."}
{"action": "list"}
{"action": "list", "query": "PR review"}
{"action": "observe", "session_id": "<child ID>"}
{"action": "steer", "session_id": "<running child ID>", "message": "Focus on deployment."}
{"action": "stop", "session_id": "<running child ID>"}
{"action": "close", "session_id": "<idle child ID>"}
```

Spawn/completion return stable session IDs. Titles are parent-supplied or derived
from the first assignment. List shows running/idle children ordered by last activity,
with creation/activity timestamps and bounded assignment previews. The default
window is 20; query searches all owned children, including older/closed entries.
Observe returns bounded history without waking or renewing a child.

Resume supplies the next assignment and optionally a model within the saved
provider. Include relevant changes in that assignment: later parent history is
not synchronized automatically. Assignments are labeled with parent provenance
and a timestamp. Busy children must be steered or stopped. Close permanently retires
an idle child while retaining history. There is no idle TTL or retained-child cap;
normal transcript deletion remains authoritative. This is conversation continuation,
not execution replay after a crash. Earlier one-off transcripts are not enrolled.

Skills review uses the host's normal eligibility and resource limits. It can update
skills, cannot write memory, and is cancelled before the next activation. The host
protects concurrent skill updates and cleans up the reviewer independently of the
completed child. `review_skills: false` disables this plugin's request for child review.

## Dependencies

There are no additional Python packages, services, or companion plugins to install.
The plugin uses Hermes' public `SubagentExtension` and plugin-context APIs.
Workflow, memory, messaging/reaction, provider, and steering plugins are not required.
All model and credential selection stays in Hermes configuration; the plugin ships
no provider presets, user instructions, or profile configuration.

## Ownership boundary

The plugin owns interface/schema, roster presentation, title/assignment formatting,
retention opt-in, and review policy. It imports only the documented extension
contract and calls `ctx.subagent_lifecycle` and `ctx.get_config`.

Hermes owns storage, parent/profile authorization, routing identity, exclusive
activation, transcript continuation, current capability reconstruction, interruption,
skills-review execution and safe teardown. Removing the plugin restores native
model-facing delegation; history and explicit host lifecycle operations remain.
No external messages, provider requests, database writes, or config writes occur at
plugin registration.

Sibling messaging and direct user messaging through the retained-child lifecycle
are not implemented here yet. Those will build on this boundary.

## Verification

From the patched Hermes checkout, use its canonical test runner and PM-built test
environment (set `HERMES_PYTHON` to the selected test interpreter if not activated):

```bash
scripts/run_tests.sh /path/to/hermes-resumable-delegation/test_sessions.py -j 2
scripts/run_tests.sh tests/plugins/test_subagent_extension.py tests/agent/test_delegated_review.py
```

Tests load this plugin through real native discovery in temporary profiles. They
exercise construction, disk persistence, cleanup, parent reconstruction and resume
through registry, inline and plugin API paths; changed tools, workspace/fork history,
admission failure, live controls, and unload are covered. External provider execution
is replaced. Core tests separately protect profile isolation, explicit tool consent,
and extension removal, plus durable storage, contention and review safety.

## License

MIT; see [LICENSE](LICENSE).

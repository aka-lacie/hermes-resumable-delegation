# Resumable delegation

An independently installable native Hermes plugin for parent-directed continuation
of delegated conversations. Idle children occupy disk, not a live agent. Each new
activation uses current tools, skills, instructions and credentials.

## Host requirements and enablement

This plugin requires the proposed retained-conversation host changes on
`feat/resumable-delegation` (validated at `51328ec601d2f46d1b0d62dd3c9f74853cb24dbd`,
based on upstream `f4ac0bea1ea50bba62886fb0b7e308e4edee8fd3`). These changes are
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
{"tasks": [{"goal": "Independently review this function", "context": "Inspect src/parser.py for edge cases.", "fork_context": false}]}
{"tasks": [{"goal": "Review the API", "provider": "review-provider", "model": "review-model"}, {"goal": "Check the tests", "model": "fast-model"}]}
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
Observe returns bounded history without waking or renewing a child. With the host
observation-preview fix, assistant entries include compact `tool_calls` (name,
file target or command preview), and tool results retain their stored `tool_name`.
Tool output previews are capped at 1,500 characters; longer text keeps its head
and tail with an explicit omitted-character count. Assistant prose can use the
remaining 12,000-character window, which also counts the compact metadata.
`truncated: true` signals omitted messages or shortened previews. Previews are
text, not necessarily parseable JSON; stored transcripts remain complete.
Older hosts still return their original observation format: this plugin does not
patch host storage or reconstruct metadata that the host has discarded.

Each spawn task can select `model` and an optional configured `provider`. Model-only
selection keeps the delegation provider/endpoint (or the parent's route when no
delegation route is configured); Hermes does not infer a provider from a model name.
A provider override requires an explicit model and a specific provider name, not
`auto`. It resolves that provider's own credentials and transport from the current
profile, without reusing another route's endpoint, request overrides or fallback
chain. Different tasks in one batch may select different routes. Omitting both
selectors preserves normal delegation defaults. Names in the example above are
placeholders for providers/models available in your profile.

New children fork conversation context by default. `tasks[].fork_context: false`
starts fresh with the assignment and supplied context. A fork copies user turns,
final answers and compaction summaries into the child's own history; tool-call
history and private reasoning are excluded. Include needed tool findings in
`context`. This plugin explicitly requests the fork default through its
`child_options` policy. Core stays fresh by default: merely registering an extension
or retaining a conversation does not enable forking. An explicit per-task boolean
overrides the plugin preference. Ordinary delegation remains fresh without this opt-in.

Resume supplies the next assignment and optionally a top-level `model` within the
saved provider. Changing providers requires a new child. Saved routes survive changes
to delegation defaults; current credentials are resolved at each activation.
Include relevant changes in that assignment: later parent history is
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
Provider setup and credentials stay in Hermes configuration. The parent can select
configured providers/models per child; no difficulty-routing plugin or policy is
required. The plugin ships no provider presets, user instructions, or profile configuration.

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
scripts/run_tests.sh /path/to/hermes-resumable-delegation -j 2
scripts/run_tests.sh tests/plugins/test_subagent_extension.py tests/agent/test_delegated_review.py
```

Tests load this plugin through real native discovery in temporary profiles. They
exercise construction, disk persistence, cleanup, parent reconstruction and resume
through registry, inline and plugin API paths; changed tools, workspace/fork history,
admission failure, live controls, and unload are covered. External provider execution
is replaced. Routing tests use real host credential resolution to check mixed-route
batches, endpoint/credential separation, refreshed credentials on resume, saved model
changes, and invalid selection refusing a whole batch before launch.
Core tests separately protect unchanged fresh defaults for generic/disabled/unloaded
extensions and retained API calls, profile isolation, explicit tool consent,
and extension removal, plus durable storage, contention and review safety.

## License

MIT; see [LICENSE](LICENSE).

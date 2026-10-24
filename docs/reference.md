# Persistent Subagents reference

For installation and examples, start with the [README](../README.md).

## Settings

These keys live under `plugins.entries.resumable-delegation.settings`:

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | Enable this extension and make its routing backend available. |
| `review_skills` | `true` | Request eligible skills-only review for retained children. |

The profile must also enable the plugin and grant `allow_tool_override: true`.
Setting `enabled: false` while `per-task` (or its `resumable` alias) remains
selected makes routing unavailable; select another installed backend when disabling it.

There is no global fork setting here: the plugin defaults to inheritance and each
spawn task can set `fork_context: false`. Retention and forking are independent.

## Upstream controls and plugin additions

On the reviewed upstream base (`5894e750c3db`), `delegate_task` already supports
`spawn`, `list`, `steer` and `stop`. Native live controls target `subagent_id`.
The retained-session adapter resolves a stable `session_id` to the current live
child and calls the existing upstream steering/stopping implementation. Legacy
live-ID requests remain supported.

The plugin's `list` returns owned retained conversations, including idle children,
and adds search across older/closed entries. `resume`, `observe` and `close` are
new model-facing actions supplied by this plugin and the retained-session host API.
Upstream also has a separate plugin run-handle API for launch, status, wait, result,
cancel and steer; that API is distinct from continuing a completed conversation.

## Listing and observation

Spawn and completion return stable session IDs. Titles are supplied by the parent
or derived from the initial assignment. List returns recent running/idle children
ordered by activity, with creation/activity timestamps and bounded assignment
previews. A query searches all owned children, including older and closed entries.
`limit` defaults to 20 and accepts 1–100 for list entries or observed messages.

Observe does not wake a child or renew its activity. Assistant entries include
compact tool-call previews: name, file target or command preview. Tool results
retain their stored `tool_name`. Tool output previews are capped at 1,500 characters;
longer text keeps its head and tail with an omitted-character count. Assistant prose
can use the remainder of the 12,000-character window, which includes preview metadata.
`truncated: true` indicates omitted messages or shortened previews. These previews
are text, not necessarily parseable JSON; stored transcripts remain complete.
Content and preview metadata use the same redaction policy as normal child results,
including vault-value scrubbing, before truncation and budgeting. Observation does
not rewrite the stored transcript. Query scans do not hold the database writer lock.

## Routing details

The optional `per-task` backend combines normal delegation settings, a configured
difficulty route, and explicit child selectors, in that order. Model-only selection
keeps the delegation provider/endpoint, or the parent's route if no delegation
route is configured. A model name does not implicitly select a provider.

An explicit `child_provider` uses that provider's current credentials and transport
from the profile. It does not reuse another route's endpoint, request overrides or
fallback chain. Different tasks in one batch may use different routes.

Difficulty routes accept `model`, `provider`, `base_url`, `api_key`, `api_mode`,
`request_overrides`, `fallback_providers` and `reasoning_effort`. Transport
`command`/`args` belong in provider configuration and are rejected here. A route
setting `provider` should also supply the appropriate model for that provider.

Saved child routes survive changes to delegation defaults. Credentials refresh on
each activation; resume can change the model within the saved provider. Parent
sessions keep the routing backend their tools were built with, so configuration
changes require a new parent session to expose the new parameters.

## Host boundary and dependencies

The required patched host provides `ctx.register_subagent_extension`,
`ctx.register_delegation_provider`, `SubagentExtension.format_fork_history` and the
`ctx.subagent_lifecycle` conversation APIs. Retention requires native SessionDB;
RuntimeSessionStore-managed workers and retained cross-profile routes are unsupported.
The extension requires in-process loading and is refused under `plugins.isolation: host`.
Ordinary nonretained profile delegation remains available.

The plugin owns the model-facing schema/actions, roster presentation, titles,
assignment formatting, retention preference, fork format, optional routing backend
and review preference. Hermes owns storage, parent/profile authorization, saved
route identity, exclusive activation, transcript continuation, current capabilities,
interruption, review execution and teardown. Registration itself makes no provider
requests, sends no messages and writes no database or configuration data.

Internal Python delegation callers such as `/review` do not inherit this policy.
Model-facing calls and explicit `launch_session` calls opt into the extension.

The conversation-only fork projection lives in [`fork_context.py`](../fork_context.py).
The host supplies an unformatted, detached boundary; other extensions can retain
completed tool exchanges or use another projection. The companion uses durable
`content`, excluding ephemeral `api_content` memory/request-hook injections, and the
host-provided `_compressed_summary` marker. Core validates the result, appends an
assistant boundary after trailing user history to separate the new assignment, and
persists the child's own history. An explicit fork requires an enabled formatter;
ordinary core launches remain fresh. The formatter controls history only: it cannot
replace core's child instructions, select identity policy, or override tool
definitions. Even system/developer messages returned in history do not replace
the host-built child prompt. This API does not implement preservation of the
parent's complete request prefix for prompt-cache reuse.

The plugin retains Hermes' existing delegated-worker instruction policy. It does
not enable parent `SOUL.md` inheritance or provide role-specific instruction files.
Conversation continuity is independent of persona and instruction inheritance.

Assignments carry parent provenance and a timestamp. Skills review cannot write
memory, is cancelled before the child's next activation, and uses host protections
for concurrent skill updates and independent reviewer cleanup.

Workflow, memory, messaging/reaction, provider and steering plugins are not
prerequisites. The package contains no provider presets, user instructions or
profile configuration. Removing it restores native model-facing delegation;
saved history and explicit host lifecycle operations remain available.

## Migrating from earlier drafts

These changes concern earlier versions of this plugin, not ordinary upstream users:

- The routing backend is now `per-task` (displayed as **Per-task routing**).
  Rename `delegation.backend: resumable` to `per-task` and move the settings block
  from `delegation.backends.resumable` to `delegation.backends.per-task`.
  The old backend name and settings remain accepted for compatibility with earlier
  configurations and saved session backend selections. If both settings blocks exist,
  the `per-task` block wins, including an explicitly empty block. This changes only
  routing names; it does not enable or disable conversation retention.

- Replace spawn `tasks[].model` / `tasks[].provider` with `child_model` /
  `child_provider`, and select `delegation.backend: per-task`. Old selector names
  are rejected rather than silently ignored. Resume's top-level `model` is unchanged.
- Move `delegation.difficulty_routes` to
  `delegation.backends.per-task.difficulty_routes`.
- Programmatic retained launches pass backend parameters through
  `launch_session(task_parameters={...})`. The separate run-handle
  `launch(SubagentLaunchRequest(...))` API remains separate from backend routing.

## Verification

From the patched Hermes checkout, use its canonical test runner and PM-built test
environment. Set `HERMES_PYTHON` to that test interpreter if it is not activated:

```bash
scripts/run_tests.sh /path/to/hermes-resumable-delegation -j 2
scripts/run_tests.sh tests/plugins/test_subagent_extension.py tests/agent/test_delegated_review.py
```

Tests load the plugin through real discovery in temporary profiles and replace
external model execution. Coverage includes persistence and resume after parent
reconstruction; refreshed capabilities; fork/fresh selection and custom formats;
admission and live controls; mixed routes, credential separation and saved-route
reconstruction; internal `/review` isolation, durable fork content and assignment
separation, activation budgets, timeout retirement, invalid parameters and unload.
Host tests cover fresh defaults,
ownership, profile isolation, transcript validation, contention and review safety.

A separate Linux acceptance run used a disposable profile and an existing local
provider with real model calls. It covered fresh and forked children, model/provider
selection, resume after parent reconstruction, bounded observation, close/refusal,
and background results consumed by a real parent turn through the CLI completion
consumer. This validates the native in-process path; it does not establish gateway
platform delivery, managed-worker support, or macOS/Windows compatibility. The full
host suite remains unverified. The README pins the tested host revision.

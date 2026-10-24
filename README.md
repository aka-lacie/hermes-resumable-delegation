# Resumable delegation

Give a personal agent delegated conversations it can return to as work develops.
A child can review a change, finish, and later review your revisions with its earlier
findings intact. Between assignments, its conversation stays on disk with no live
agent running.

The plugin combines five features. They work together, but solve different problems:

| Feature | What it adds | When it applies |
| --- | --- | --- |
| **Continuation** | Resume completed children by stable session ID; list, observe, steer, stop or close them. | Enabled with the plugin. |
| **Context forking** | Start a child with selected conversation history from its parent. | On by default for new children; opt out per task. |
| **Model/provider selection** | Choose a different model or configured provider for each child. | Opt in with `delegation.backend: resumable`. |
| **Difficulty routing** | Let the agent choose among your `easy`, `medium` and `hard` routes. | Optional configuration under the `resumable` backend. |
| **Skills review** | Request an eligible child's post-task review to update skills. | Requested by default; can be disabled. |

Forking determines **how a child starts**; continuation preserves **what it learns**.
A child can start fresh and still be resumed later. Routing chooses who does the
work, and skills review can retain reusable lessons beyond that conversation.

## Setup

**Development preview:** this requires the proposed Hermes host changes on
`feat/resumable-delegation` at `63ef3d0fc0` (upstream base `5894e750c3db`). They are
not yet merged upstream. Use a patched host with native SessionDB and in-process
plugins; managed workers using RuntimeSessionStore are not supported.

No extra Python packages, services or companion plugins are required. Configure
providers and credentials through Hermes as usual.

1. Merge this into the target profile's `config.yaml`, preserving existing entries:

   ```yaml
   plugins:
     enabled:
       - resumable-delegation
     entries:
       resumable-delegation:
         allow_tool_override: true
   ```

   `allow_tool_override` permits the plugin to extend Hermes' existing
   `delegate_task` tool. It keeps the normal execution limits and completion delivery.

2. Install the plugin in that same profile:

   ```bash
   hermes plugins install https://github.com/aka-lacie/hermes-resumable-delegation --enable
   ```

   For a named profile, use `hermes --profile <profile> plugins install ... --enable`.

3. Restart the Hermes process serving that profile and start a new parent
   conversation so its tools include the plugin's controls.

This is enough for continuation, context forking and skills review. Model/provider
selectors and difficulty choices require the optional routing setup below.

## 1. Continue a child's work

The following JSON examples are **arguments to `delegate_task`**, used by the
parent agent. You can ask the parent to perform these actions in normal conversation.

Start a child:

```json
{"tasks": [{"goal": "Review this PR for concurrency bugs", "title": "Concurrency review"}]}
```

Keep the child's `session_id` from spawn or completion. Once it finishes, send a
follow-up to that same conversation:

```json
{"action": "resume", "session_id": "<child ID>", "message": "I fixed the race; review the updated diff."}
```

Resume reconstructs the child with its saved history and current tools, skills,
instructions and credentials. Include relevant changes in the new assignment;
later parent turns are not copied automatically.

Other controls use the same tool:

| Action | Arguments besides `action` | Effect |
| --- | --- | --- |
| `list` | Optional `query`, `limit` | Find owned children; a query also searches older and closed entries. |
| `observe` | `session_id`, optional `limit` | Read bounded history without waking the child. |
| `steer` | `session_id`, `message` | Redirect a running child. |
| `stop` | `session_id` | Interrupt a running child. |
| `close` | `session_id` | Permanently retire an idle child from reuse, preserving its history. |

Use `steer` or `stop` while a child is busy; resume is for idle children.
There is no automatic idle expiry or retained-child cap.

## 2. Choose inherited or fresh context

New children inherit user turns, final answers and compaction summaries by default.
**Tool history and private reasoning are excluded.** Put any needed tool findings
in the task's `context`.

For an independent assessment, start fresh:

```json
{"tasks": [{"goal": "Review this function independently", "fork_context": false, "context": "Inspect src/parser.py for edge cases."}]}
```

This still creates a resumable child. The plugin owns the filtering policy; core
captures, validates and persists the snapshot. Different instructions, tools or
history formatting can reduce reuse of the parent's prompt cache.

## 3. Choose a model or provider per child

Add this to the profile's configuration, then restart Hermes and start a new
parent conversation:

```yaml
delegation:
  backend: resumable
```

Now spawn tasks can use `child_model` and `child_provider`:

```json
{"tasks": [{"goal": "Review the API", "child_provider": "review-provider", "child_model": "review-model"}, {"goal": "Check the tests", "child_model": "fast-model"}]}
```

Replace these placeholders with configured providers and available models.

- `child_model` alone keeps the configured delegation provider and endpoint.
- `child_provider` requires an explicit `child_model` and a named provider, not `auto`.
- Omitting both uses normal delegation defaults. An invalid route refuses that
  task; valid siblings can still run.
- Resume accepts an optional top-level `model` within the child's saved provider.
  Changing providers requires a new child.

Enabling the plugin does **not** select this backend automatically. Continuation
and fork controls also work with other routing backends, using their own selectors.

## 4. Configure difficulty routes

Optionally define choices under that backend. Replace the model placeholders:

```yaml
delegation:
  backend: resumable
  backends:
    resumable:
      difficulty_routes:
        easy: {model: fast-model, reasoning_effort: low}
        medium: {}
        hard: {model: review-model, reasoning_effort: high}
```

The parent can then choose a route without naming a model:

```json
{"tasks": [{"goal": "Investigate this intermittent race", "difficulty": "hard"}]}
```

Only configured levels are advertised. `{}` uses the normal route unchanged.
An explicit `child_model` or `child_provider` overrides the difficulty choice;
omitting difficulty uses normal defaults, including in nested delegation.
No model or provider presets ship with the plugin.

## 5. Control skills review

Eligible children can receive a post-task review that updates **skills, not memory**.
The host applies its normal eligibility, cancellation and resource limits; enabling
review does not guarantee one runs after every task.

To disable the plugin's review request, add this under its existing entry:

```yaml
plugins:
  entries:
    resumable-delegation:
      settings:
        review_skills: false
```

## Limits and removal

Children belong to their parent conversation and profile. Direct user chat with a
child, peer messaging and retained cross-profile routes are not implemented.
Process loss stops active execution; resuming saved history does not replay a
crashed task. Earlier one-off delegates are not automatically enrolled.

Before disabling or removing the plugin, change `delegation.backend` back to
`default` (or another installed backend) if it is set to `resumable`. Saved history
remains, but the plugin's model-facing continuation controls disappear.

See the [reference](docs/reference.md) for observation limits, routing details,
settings, earlier-draft migration, host APIs and verification instructions.

## License

MIT; see [LICENSE](LICENSE).

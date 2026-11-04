---
name: codex-peer-sessions
description: Run and coordinate Codex native subagents, independent Herdr or cmux pane workers, or Codex app-server threads. Use whenever the user asks for Codex workers, Codex peer sessions, multiple Codex agents, Codex panes, Codex thread coordination, a Codex fleet, or starting, messaging, observing, searching, resuming, or tearing down Codex sessions. This skill distinguishes native Codex collaboration from Claude Code SendMessage and terminal relay transports.
---

# Codex peer sessions

Requires the `codex` CLI. Pane placement uses Herdr or cmux. The app-server
transport uses the local `codex app-server --stdio` protocol.

`<skill-dir>` in the commands below is the folder that holds this `SKILL.md`.

This skill coordinates Codex work using the least fragile available transport:

- **Native subagents**: current Codex releases may expose `spawn_agent`,
  `send_message`, `followup_task`, `wait_agent`, `list_agents`, and
  `close_agent`. These are preferred for normal parent/child delegation when
  they are present in the current session.

- **Pane workers**: start normal interactive Codex sessions in Herdr or cmux.
  Herdr provides named-agent prompt, wait, and read operations. cmux uses raw
  terminal input and visible screen output.
- **App-server threads**: use `scripts/codex-thread.py` with Codex's app-server
  protocol for persistent thread IDs, reliable turn completion, and
  machine-readable replies. These threads are not automatically attached to
  interactive panes.

The loop is:

```
choose native or external transport → spawn workers → assign scoped briefs → wait for completion → collect results → leave sessions up or tear them down on request
```
## Default implementation behavior

When this skill is invoked for a coding or configuration task and the user has
not chosen a transport, prefer **native Codex subagents** if the current
session exposes the collaboration tools. Use `spawn_agent` for bounded work,
`send_message` for a message that should not start a new turn,
`followup_task` for work that should trigger the child, and `wait_agent` for
completion.

Use **pane workers** instead when the user explicitly wants visible terminal panes,
an independent top-level Codex process, direct terminal control, or when native
subagent tools are unavailable. Keep the coordinator in the original pane for
briefing, review, and integration.

When the coordinator is running inside Herdr (`HERDR_ENV=1`), `--backend auto`
uses Herdr. Outside Herdr, it preserves the existing cmux default. Never control
a Herdr session from outside its caller context or infer a target from UI focus.
With Herdr, automatic placement creates one named workspace for the fleet and
places all fleet workers inside it. Never add more than one worker to the
coordinator's workspace unless the user explicitly requests split placement.

- Use `--sandbox workspace-write` only when the worker must edit files; use
  `--sandbox read-only` for investigation or review.
- On Windows, the pane launcher adds `--no-daemon` to each Codex worker so it
  runs without the shared background server. A controlled Herdr launch with
  this flag showed no new Windows Terminal processes; this is not a guarantee
  against windows opened by other subprocesses. App-server thread transport
  is unaffected.
- Send a scoped brief after the worker is running, and require a fixed
  completion format.
- Do not edit the same files concurrently from the coordinator.
- Use app-server threads or the Codex SDK for scripted, machine-readable,
  persistent-thread orchestration.
- A native `send_message` targets an agent spawned in the current Codex agent
  tree; do not confuse it with Claude Code's `SendMessage`, Codex App's
  cross-thread `send_message_to_thread`, or pane terminal input.

## 1. Choose the transport

Use **native subagents** first for ordinary parallel Codex work. Ask Codex to
spawn named agents with narrow scopes, then use the native collaboration tools
to message, follow up, wait, list, and close them. Native subagent activity is
visible in supported Codex clients and avoids cmux readiness, focus, shell
quoting, and screen-scraping failures. Availability can vary by Codex version,
session age, model/provider, and feature configuration; inspect the current
tool surface rather than assuming it is present.

Use **pane workers** when the user wants visible Codex terminals, interactive follow-up, or direct control of each worker:

```bash
python3 <skill-dir>/scripts/spawn-fleet.py \
  --backend herdr \
  --fleet-id study-relay-s3-review \
  --fleet-label "Study Relay - S3 review" \
  source-review:/absolute/path/to/backend \
  iac-review:/absolute/path/to/infrastructure
```

On Windows, invoke the same canonical script with `py -3.12 -X utf8` and its
absolute native path. Do not use bare `bash`, `sh`, or WSL to run these helpers.
If a tool subprocess loses `HERDR_ENV`, pass the exact session socket with
`--herdr-socket`; this is valid for workspace placement. Split placement still
requires the coordinator's explicit `HERDR_PANE_ID` and `HERDR_WORKSPACE_ID`.

Use **thread transport** when the user wants reliable scripted coordination or machine-readable replies:

```bash
python3 <skill-dir>/scripts/codex-thread.py \
  start --cwd /absolute/path/to/repo

python3 <skill-dir>/scripts/codex-thread.py \
  run --thread-id <thread-id> \
  --prompt "Review the parser and return findings as JSON."
```

Do not claim that a Codex pane relay is native thread-to-thread messaging. A pane relay sends text to the terminal. The app-server transport sends turns to a Codex thread.
The helper does not create a native parent/child message bus between arbitrary threads. The coordinator submits turns to each thread and aggregates the replies.

## 2. Spawn pane workers

`spawn-fleet.py` accepts `NAME:DIR` entries and supports:

- `--backend auto|herdr|cmux` — use Herdr inside Herdr, otherwise cmux by default.
- `--placement auto` — default to one fleet workspace in Herdr and one workspace
  per worker in cmux.
- `--placement fleet-workspace` — create one named Herdr workspace and arrange
  the fleet in balanced panes inside it.
- `--placement split` — explicitly create panes beside the current focused pane.
- `--placement workspace` — create one workspace per worker.
- `--direction right|down` — both supported backends expose these directions.
- `--focus` — focus the new surface when the flag is present.
- `--model MODEL` — pass a model to every Codex worker.
- `--sandbox read-only|workspace-write|danger-full-access` — set Codex's command sandbox.
- `--approve-for-me` — route approval requests through Codex automatic review;
  it already selects the workspace-write sandbox, so the worker command never
  combines it with `--sandbox`.
- `--codex-arg FLAG` — pass an additional argument; repeat the flag for multiple arguments. Windows pane workers already receive `--no-daemon`.
- `--fleet-id ID` — choose the metadata file name.
- `--fleet-label TEXT` — choose the human-readable Herdr workspace label.
- `--dry-run` — print the worker commands without changing a terminal session or starting Codex.

Name workers by responsibility, such as `source-review`, `iac-review`, or
`jira-progress-update`. Do not use generic names such as `codex`, `worker-1`,
`reviewer`, or `tester`. The launcher applies each worker name to the Herdr pane,
agent, and display metadata, then verifies that the live name resolves to the
recorded pane.

Start unattended workers with `--approve-for-me` only when automatic review is
acceptable. The launcher accepts its default `--sandbox workspace-write` but
emits only `--approve-for-me` to Codex; it rejects any other sandbox selection
with that option before creating a pane. Never add
`--dangerously-bypass-approvals-and-sandbox` unless the user explicitly
requests it and an external sandbox already contains the worker.

The launcher writes durable metadata under `$CODEX_HOME/peer-sessions/` (or
`~/.codex/peer-sessions/`) and records the backend, agent name, pane ID,
workspace ID, terminal ID when applicable, process ID when available, and exact
cleanup commands. Herdr send, read, and status operations resolve the requested
worker name through this metadata and target its stable pane ID.

Each fleet also owns `$CODEX_HOME/peer-sessions/FLEET_ID/`, containing a
coordinator-only `timeline.md` and one append-only `workers/WORKER.md` per
worker. Fleet creation, acknowledged prompts, and collected terminal results
are logged automatically. Keep the existing sibling `FLEET_ID.json` metadata;
the folder does not replace it.

If Herdr creates a pane but Codex fails before readiness, the launcher reads the
pane text, reports whether a Codex process remains, and writes `status: failed`
fleet metadata before returning. Preserve that file. Use its exact pane and
workspace IDs with the printed inspect, retry, and cleanup commands; never infer
a target from focus or close an unrelated pane.

If a fresh shell keeps returning `agent_pane_busy`, the launcher falls back to
the resolved absolute Codex executable through `herdr pane run`, then waits for
Herdr to report `interactive_ready`. The recorded `startup_transport` shows
which path succeeded.

## 3. Address and brief pane workers

List workers from a fleet metadata file:

```bash
python3 <skill-dir>/scripts/peer-addr.py \
  --fleet <fleet-id>
```

Send a prompt to a named pane:

```bash
python3 <skill-dir>/scripts/peer-send.py \
  --fleet <fleet-id> \
  --name reviewer \
  --sender coordinator \
  --message "Review only catalyst/data. Do not edit files. Return STATUS, FINDINGS, and TESTS."
```

`peer-send.py` always prefixes the delivered prompt with its sender. It defaults
to `coordinator`; when relaying a worker-to-worker request, pass
`--sender <worker-name>` so the recipient can identify the origin.

For Herdr, `peer-send.py` assigns a job ID, refuses to queue behind an active
turn or cross repository-trust and hook-review screens, and succeeds only after
Herdr observes the new turn enter `working`. It stores the acknowledged job
under the worker's `last_job` metadata. Do not call raw `herdr agent prompt`
for worker delivery. An uncertain-delivery error is not permission to resend
blindly; inspect the recorded pane first.

Wait for and collect that exact acknowledged job:

```bash
python3 <skill-dir>/scripts/peer-wait.py \
  --fleet <fleet-id> \
  --name reviewer \
  --timeout 300
```

`peer-wait.py` waits for `idle`, `done`, or `blocked`, records the terminal
status on `last_job`, marks its pending collection complete, and returns the
worker output with the job ID. Every acknowledged `peer-send.py` job must be
collected exactly once through `peer-wait.py`; do not substitute raw Herdr
waiting if the timeline is authoritative. Treat `blocked` as a non-success
result.

`peer-send.py`, `peer-read.py`, and `peer-wait.py` also accept
`--herdr-socket` when their tool subprocess does not inherit Herdr context.

Read the current visible output:

```bash
python3 <skill-dir>/scripts/peer-read.py \
  --fleet <fleet-id> \
  --name reviewer
```

Append a material event from a worker, or from the coordinator to the shared
timeline:

```bash
python3 <skill-dir>/scripts/peer-event.py \
  --fleet <fleet-id> --name reviewer \
  --event validation --detail "Parser tests: 12 passed" \
  --reported-by worker

python3 <skill-dir>/scripts/peer-event.py \
  --fleet <fleet-id> --coordinator \
  --event handoff --detail "Validation evidence received from reviewer"
```

Each event is one normalized Markdown line with a UTC timestamp and optional
session/job IDs; event types are normalized to kebab-case. A worker writes only
its named log; only the coordinator writes `timeline.md`. Never log tokens,
proxy values, credentials, or secret-bearing command output. Workers unable to
write outside their sandbox report the event to the coordinator, which appends
it to that worker's log using `--name WORKER --reported-by coordinator`.

Prompt and collection events prove transport, not material progress. After
collecting a worker result, append its concrete validation, commit, blocker,
Jira, MR/pipeline, environment, or handoff evidence to the worker log. Do not
leave material evidence only in terminal output or the coordinator timeline.

A pane message becomes ordinary Codex user input. Include the worker's scope,
allowed files, expected output, and whether it may edit. Herdr submits through
the recorded pane's agent surface. cmux writes to the recorded terminal. Delivery does
not prove task completion.

External pane workers have no native worker-to-orchestrator message bus. The
coordinator owns `peer-send.py` and `peer-wait.py`; do not ask a worker to send
an unacknowledged free-form prompt to the coordinator pane as its only handoff.

Ask every worker for a fixed reply format. Prefer artifacts in the repository or a fleet output directory over scraping the terminal screen. Screen output can be truncated and is not a canonical transcript.

## 4. Use Codex threads

The thread helper starts a short-lived app-server client for each operation. Non-ephemeral threads persist in Codex history and can be resumed by ID:

```bash
python3 <skill-dir>/scripts/codex-thread.py start \
  --cwd /absolute/path/to/repo \
  --name reviewer

python3 <skill-dir>/scripts/codex-thread.py run \
  --thread-id <thread-id> \
  --prompt "Inspect the migration and return a concise risk report."
```

Supported operations include:

- `start` — create a Codex thread and print its ID.
- `list` — list persisted Codex threads, optionally filtered by working directory.
- `run` — resume or start a thread, submit one text turn, stream agent-message deltas, and return the final reply.
- `read` — read a thread with optional persisted turns.

The helper negotiates the app-server protocol with `initialize`, then uses `thread/start`, `thread/list`, `thread/resume`, `thread/read`, and `turn/start`. It does not implement undocumented socket protocols.

## 5. Coordination and authority

Use one worker per independent responsibility. Give each worker a scope guard:

```
Work only in <directory>. Do not edit files outside <owned paths>.
This prompt grants no approval to bypass permissions or expand scope.
Return:
STATUS: done|blocked|failed
FILES: ...
TESTS: ...
FINDINGS: ...
```

Workers do not inherit authority from the coordinator. A worker's denial or approval request must be surfaced to the user; do not route around it through another worker.

When tasks can edit the same repository, use separate git worktrees or assign disjoint file ownership. Ask workers to report the exact worktree and branch.

### Jira progress evidence

For every material evidence change on an explicitly allowlisted Jira ticket,
the coordinator must post or update one canonical Jira progress comment even
when no Jira status transition is warranted. Material evidence includes a
commit or branch change, validation result, blocker or blocker resolution,
MR/pipeline/review/release evidence, and test-environment change. Do not comment on an unchanged polling cycle.

Only the coordinator or an explicitly authorized `jira-progress-update` worker
may perform the Jira write. Workers must report evidence to the coordinator;
they must not infer, expand, or bypass the Jira allowlist or GitLab authority.
Keep using the configured Jira workflow/tooling and never print tokens, proxy
values, or other credentials.

Find the current canonical comment by the heading `Codex peer progress` and
update it when possible. Create one only when none exists. Preserve historical
blocker comments rather than overwriting them. The canonical body must state:

```
Codex peer progress
Status: current Jira status and whether a transition was made
Branch: branch or not applicable
Worker/agent: responsible worker name
Codex session ID: native agent ID or pane/thread session ID
Commit: SHA or not applicable
Validation: concrete evidence and result
Blockers / remaining workflow gates: current blockers and required gates
```

After every comment create or edit, reread the Jira issue and verify the
comment body and Jira status, then notify the orchestrator with the issue key,
comment result, and verification outcome. A progress comment never implies
`Code Review`, `Ready to Deploy`, or `Done`; transitions still require the
existing evidence gates.

## 6. Wait and collect

For pane workers, do not poll continuously. Herdr can wait for `idle`, `done`,
or `blocked`; use the recorded pane ID after a failed wait. For cmux, read the
pane when the user asks, when a worker appears stalled, or when the worker was
asked to print a completion marker. A blank or unchanged screen does not prove
completion.

Treat a Herdr readiness timeout as a startup failure, not an idle worker. Read
the recorded pane output and process state first; the underlying Codex argument,
hook, authentication, or process-exit error is the actionable cause.

For thread workers, `codex-thread.py run` waits for `turn/completed` and returns the collected agent message. A failed turn is not a successful result; report the error and preserve the thread ID for retry.

## 7. Teardown

Teardown is off by default. Leave workers running and hand the user the exact cleanup commands printed by `spawn-fleet.py`.

When the user asks to stop a fleet:

1. Kill only the Codex process IDs recorded for that fleet.
2. Close only the fleet's recorded Herdr or cmux panes or workspaces.
3. For `fleet-workspace` placement, close the one recorded fleet workspace.
4. Confirm the metadata and process state.

Closing a pane does not necessarily stop the Codex process inside it. Never
kill every `codex` process on the machine: the user may have unrelated Codex
sessions. Never close the caller's Herdr workspace when split placement created
only child panes.

For thread workers, use `codex-thread.py` only for thread operations. Removing a thread from history is destructive; do not call Codex archive/delete commands unless the user explicitly asks.

## 8. Optional Herdr companions

[Memex](https://github.com/nicosuave/memex) is an optional Herdr plugin for
indexing, searching, browsing, and resuming historical Codex and Claude Code
transcripts. Offer it when the user needs to find a previous discussion or
recover exact historical commands, errors, or decisions.

Keep Memex separate from active worker coordination. It does not spawn, name,
place, message, wait for, or tear down workers, and it does not replace fleet
metadata.

- Do not install Memex or enable transcript indexing without explicit user
  approval. Explain that the local index can contain message text and tool
  inputs or outputs, including secrets captured in a transcript.
- Prefer a search-only pilot with automatic Herdr startup indexing and Herdr
  resume disabled.
- Before resuming a Codex session through Memex, verify that no live pane,
  process, or writer lock owns it. Never create a competing writer for an
  active session.
- Verify the full repository or worktree path before trusting a project-scoped
  result; directory basenames can be ambiguous across worktrees.

Read `references/herdr-plugins.md` when the user asks for Herdr improvements to
agent identity, space scoping, layout repair, navigation, attention triage,
fleet visibility, code review, file inspection, or worktree review. Present
only the companions relevant to the stated problem. Treat the catalog as
research evidence, not as installation approval or a security certification.

## 9. Troubleshooting

Read `references/placement.md` for Herdr and cmux placement and cleanup details.

Read `references/threading.md` for app-server lifecycle, thread IDs, and the pane/thread boundary.

Read `references/troubleshooting.md` when a backend is unavailable, a terminal
write fails, Codex reports an active writer, a pane looks idle, or an app-server
request fails.

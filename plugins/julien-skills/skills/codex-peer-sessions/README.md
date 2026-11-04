# codex-peer-sessions

Run a local fleet of Codex CLI sessions in Herdr or cmux panes, or coordinate persistent Codex threads through the Codex app-server protocol.

## Requirements

- Codex CLI with `codex app-server --stdio` support.
- Herdr or cmux for pane placement.
- Python 3.9 or newer.

## Pane workflow

```bash
python3 <skill-dir>/scripts/spawn-fleet.py \
  --backend herdr \
  --fleet-id parser-review \
  --fleet-label "Parser review" \
  api-test-review:/absolute/path/to/repo \
  cli-test-review:/absolute/path/to/repo
```

Herdr automatically creates one named workspace for the fleet, arranges its
workers in balanced panes, and keeps the coordinator's workspace unchanged.
On Windows, the launcher adds `--no-daemon` to pane workers so they run without
the shared Codex background server. This does not change the app-server thread
workflow.
The launcher writes fleet metadata to `$CODEX_HOME/peer-sessions/` and prints
the exact cleanup commands. It also creates one append-only Markdown timeline
folder per fleet with `timeline.md` and `workers/WORKER.md`. Send a prompt to
one worker and read its visible terminal output:

```bash
python3 <skill-dir>/scripts/peer-send.py \
  --fleet <fleet-id> \
  --name api-test-review \
  --sender coordinator \
  --message "Review the parser. Do not edit files. Return STATUS, FINDINGS, and TESTS."

python3 <skill-dir>/scripts/peer-read.py \
  --fleet <fleet-id> \
  --name api-test-review
```

Every delivered prompt begins with its sender identity. The default sender is
`coordinator`; use `--sender WORKER` when relaying a worker-to-worker message.

Append an explicit worker event with `peer-event.py --fleet ID --name WORKER
--event TYPE --detail TEXT --reported-by worker`, or use `--coordinator`
instead of `--name` for the shared timeline. Coordinators append on behalf of
sandboxed workers with `--name WORKER --reported-by coordinator`. Collect every
acknowledged send exactly once through `peer-wait.py`. Never place secrets or
secret-bearing output in event logs.

Herdr addresses workers by stable agent name and supports prompt, wait, and
read operations. cmux uses recorded terminal IDs. Neither transport is native
peer messaging. Terminal output can be truncated; use repository artifacts for
durable results.

`--approve-for-me` already selects Codex's workspace-write sandbox. The
launcher omits an explicit `--sandbox` from that worker command and rejects a
different sandbox selection before creating a pane. If Codex exits during
Herdr readiness detection, the launcher includes the pane output in the error,
writes failed-fleet metadata with the created pane ID, and prints pane-scoped
inspection, retry, and cleanup commands.

## Thread workflow

```bash
python3 <skill-dir>/scripts/codex-thread.py \
  start --cwd /absolute/path/to/repo --name reviewer

python3 <skill-dir>/scripts/codex-thread.py \
  run --thread-id <thread-id> \
  --prompt "Review the parser and return findings as JSON."
```

Thread mode uses Codex's app-server JSON-RPC protocol, stores non-ephemeral threads in Codex history, and returns machine-readable turn results.
The helper is a coordinator client, not a native thread-to-thread message bus: it submits turns to individual threads and aggregates replies.

## Files

| File | Purpose |
| --- | --- |
| `SKILL.md` | Agent workflow and safety rules |
| `scripts/spawn-fleet.py` | Create Herdr or cmux panes/workspaces and launch Codex |
| `scripts/herdr_client.py` | Call Herdr with explicit caller and agent IDs |
| `scripts/cmux_client.py` | Call cmux with recorded pane and terminal IDs |
| `scripts/peer-addr.py` | List and update fleet worker metadata |
| `scripts/peer-send.py` | Send text to a Codex pane |
| `scripts/peer-read.py` | Read a Codex pane screen |
| `scripts/peer-event.py` | Append one normalized fleet or worker timeline event |
| `scripts/fleet_events.py` | Create and append fleet-owned Markdown event logs |
| `scripts/peer-wait.py` | Wait for and collect an acknowledged Herdr job |
| `scripts/codex-thread.py` | Start, list, read, resume, and run Codex threads |
| `scripts/fleet_state.py` | Shared fleet metadata persistence |
| `scripts/self_check.py` | Stdlib-only metadata self-check |
| `tests/test_peer_sessions.py` | Stdlib-only launcher and addressing tests |
| `references/placement.md` | Herdr and cmux placement and cleanup |
| `references/threading.md` | Codex app-server thread protocol |
| `references/troubleshooting.md` | Common failures and recovery |

## Safety

Workers receive user prompts but no extra authority. Do not use `--dangerously-bypass-approvals-and-sandbox` by default. Kill exact worker process IDs before closing their panes, and never kill every Codex process on the machine.

## Validation

```bash
python3 -m unittest discover -s tests -v
python3 scripts/self_check.py
```

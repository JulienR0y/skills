# Troubleshooting

## Herdr rejects the caller context

Run:

```bash
test "${HERDR_ENV:-}" = 1
printf '%s\n' "$HERDR_WORKSPACE_ID" "$HERDR_PANE_ID"
```

Start the coordinating Codex session inside Herdr before using the Herdr
backend. Do not control a separately focused Herdr session from an outside
shell.

Some tool subprocesses do not inherit `HERDR_ENV`. For workspace placement,
pass the verified session socket with `--herdr-socket`. Do not use this to infer
or control a different session. Split placement still requires the caller pane
and workspace environment IDs.

## Herdr reports `agent_pane_busy`

A newly created pane can take a short time to reach an interactive shell prompt.
The launcher retries this specific condition for 5s, then runs the resolved
absolute Codex executable in that pane and waits for `interactive_ready`. For
any later failure, inspect the pane instead of reusing or closing unrelated IDs.

## Windows Terminal opens extra windows during a pane launch

The pane launcher adds `--no-daemon` on Windows so a Codex worker runs without
the shared background server. A controlled Herdr launch with this flag produced
no new Windows Terminal processes. The flag is independent of `--sandbox` and
does not prevent other subprocesses from opening windows.
Windows Event Viewer AppModel Runtime event 211 records processes added to the
Windows Terminal app container; each entry is not a new terminal window.
Compare `WindowsTerminal.exe` and `OpenConsole.exe` start times before
attributing a burst of event 211 entries to new windows.
For a fleet launched with an older helper, inspect its recorded `command` before
restarting anything; pass `--codex-arg=--no-daemon` on a new launch. Do not
change the system's default terminal setting to work around one fleet.

## Herdr times out waiting for Codex readiness

Do not treat the timeout as the root cause. The launcher reads the newly created
pane after the failed start and reports the exact Codex output when available.
It also writes a fleet metadata file with `status: failed`, the pane ID, the
workspace ID, and the startup error.

Use the exact commands printed with the failure. They follow this shape:

```bash
herdr pane read <pane-id> --source recent-unwrapped --lines 80
herdr agent start <name> --kind codex --pane <pane-id> -- <validated-codex-args>
herdr pane close <pane-id>               # split placement only
herdr workspace close <workspace-id>     # workspace placement only
```

Run the retry only after resolving the pane error and confirming that no Codex
process remains. Use only the cleanup command printed for the failed record.
Never close a pane or workspace obtained from focus or a different fleet.

Codex's `--approve-for-me` option already selects the workspace-write sandbox.
The launcher emits no separate `--sandbox` flag with it and rejects a requested
read-only or danger-full-access sandbox before pane creation.

## A new Codex worker shows the hook review screen

The first worker after installing a lifecycle hook can require explicit trust.
Read the hook file, approve it in Codex, and close the review screen before
sending work. Herdr can classify this screen as ready or done, so confirm the
actual pane text on first use. Do not interpret startup success as proof that
the initial prompt ran.

`peer-send.py` fails closed while the visible pane shows repository trust, hook
review, or another continue screen. Resolve the screen, then retry deliberately.

## Herdr says a prompt was sent but Codex stays idle

Use `peer-send.py`, not raw `herdr agent prompt`. It requires a state change and
records the acknowledged job ID. If delivery is uncertain, read the exact pane
and determine whether the prompt is buffered, submitted, or blocked before
resending it.

## `cmux` is unavailable

Run `command -v cmux` and `cmux --version`. The pane launcher requires a current cmux session. Use thread mode when a pane surface is not needed.

## The split command cannot find a focused pane

Run:

```bash
cmux pane list --json
```

`--placement split` must run inside the cmux session whose pane should be split. The launcher does not create an operating-system window.

## A pane looks idle

Read the terminal screen:

```bash
python3 <skill-dir>/scripts/peer-read.py \
  --fleet <fleet-id> --name <worker>
```

An idle screen can mean that Codex is waiting for input, waiting for approval, or has completed. Require an explicit completion marker or a durable output artifact.

## Herdr shows several workers as `codex`

New fleets apply the worker name to the agent, pane, and display metadata. They
also verify the name immediately after startup. Older fleets may have only a
name in their saved metadata. Use `peer-addr.py` to map that name to its recorded
pane ID; `peer-send.py` and `peer-read.py` use the pane ID automatically.

Do not infer worker identity from the current terminal title. Codex rewrites the
title from its working directory and activity state.

## A terminal write fails

Refresh fleet metadata with `peer-addr.py`. The pane or terminal may have been closed and its ID may no longer be valid. Do not reuse a stale terminal ID.

## Codex resume reports `already has an active writer`

Do not keep creating resume panes. Identify the writer process and its terminal
origin first:

```bash
ps -eo pid,ppid,tty,stat,lstart,args | rg '[c]odex'
tr '\0' '\n' < /proc/<pid>/environ | rg '^(TERM_PROGRAM|WARP_FOCUS_URL|CMUX|HERDR_)='
```

If `TERM_PROGRAM=WarpTerminal`, the original process may still expose an exact
`WARP_FOCUS_URL`. Open that local URI to focus the live Warp session. If the
writer is still performing a turn, do not terminate it. `codex fork
<thread-id>` can create an accessible backup with copied history, but the fork
is a separate coordinator and must not edit the same checkout concurrently.

## A thread run times out

Inspect the JSON-RPC error printed by `codex-thread.py`. Common causes are a stale thread ID, a blocked approval request, an unavailable model, or an app-server process that exited. Preserve the thread ID and retry rather than deleting the thread.

## A worker must be stopped

Use the exact PID from the fleet metadata, then close the matching pane or workspace. Do not run `pkill codex`; unrelated Codex sessions may belong to the user.

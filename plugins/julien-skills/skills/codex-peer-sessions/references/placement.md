# Herdr and cmux placement

## Herdr

Herdr placement requires the coordinator to run inside a Herdr-managed pane.
Verify `HERDR_ENV=1`, then target `HERDR_PANE_ID` for split placement. Never
infer the caller from whichever pane another client has focused.

Automatic placement creates one named workspace for the fleet. The first worker
uses the workspace's root pane. Later workers are added with breadth-first,
alternating right and down splits so 3 or 4 workers do not become narrow columns.
Use `--fleet-label` for the visible workspace label and `--fleet-id` for its
durable metadata identity.

The launcher uses:

- `herdr pane split --pane <id> --direction right|down --cwd <dir>`
- `herdr workspace create --cwd <dir> --label <name>`
- `herdr agent start <name> --kind codex --pane <id>`
- `herdr pane rename <pane-id> <name>`
- `herdr pane report-metadata <pane-id> --display-agent <name> --title <name>`
- `herdr agent rename <pane-id> <name>`
- `herdr agent prompt|get|read <pane-id>`

Herdr agent names must match `[a-z][a-z0-9_-]{0,31}`. Creation responses are
the source of truth for pane and workspace IDs. Human-facing commands accept the
worker name from fleet metadata, but the helpers target the recorded pane ID so
they continue working if Herdr later loses the optional agent name.

Use explicit `--placement split` only when the user wants workers beside the
coordinator. Never place more than one worker in the coordinator's workspace by
default. `--placement workspace` remains available when every worker needs a
separate workspace.

For split placement, cleanup closes only the created child panes. For
fleet-workspace placement, cleanup closes the one deduplicated fleet workspace.
For workspace placement, cleanup closes the created worker workspaces. Never
close the caller's workspace as split cleanup.

## cmux

The launcher uses the current cmux scoped API:

- `cmux pane list --json`
- `cmux pane <id> split --right|--down`
- `cmux pane <id> run -- <argv...>`
- `cmux workspace create --name <name>`
- `cmux workspace <id> run -- <argv...>`
- `cmux terminal <id> write --text <prompt>`
- `cmux terminal <id> keys Enter`

### Split placement

`--placement split` requires the launcher to run from an active cmux session with a focused pane. The launcher chains new splits from the pane it just created so the workers appear in order. It never closes the user's workspace during cleanup.

Use `--direction down` when several right-hand panes would become too narrow. The current cmux API exposes right and down splits; do not guess left or up flags.

### Workspace placement

Automatic cmux placement uses `--placement workspace`, which creates one
workspace per worker. `fleet-workspace` is currently Herdr-only. The launcher
records workspace IDs and closes only those IDs when the user requests teardown.

## Cleanup

The launcher prints cleanup commands with durable IDs. Follow this order:

```bash
kill <codex-pid> <codex-pid>
herdr workspace close <fleet-workspace-id>
cmux pane <pane-id> close
cmux workspace <workspace-id> close
```

Use only the cleanup command that matches the worker's placement. Closing a pane or workspace does not guarantee that its Codex process has stopped.

If cmux has no active session, use `--placement workspace` after opening a cmux session, or run the thread transport instead.

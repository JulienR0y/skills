# Codex thread transport

Codex CLI 0.147.0 exposes an app-server JSON-RPC interface over stdio. The helper starts a short-lived `codex app-server --stdio` client for each operation.

## Lifecycle

The helper sends:

1. `initialize`
2. `initialized`
3. One of `thread/start`, `thread/resume`, `thread/list`, or `thread/read`
4. `thread/name/set` when `--name` is supplied
5. `turn/start` for `run`

The helper waits for `turn/completed` and collects `item/agentMessage/delta` notifications. A completed turn is the only successful result; a successful JSON-RPC response to `turn/start` only means that Codex accepted the turn.

## Pane boundary

An interactive `codex` process launched in a cmux pane owns its own UI and app-server connection. A separate helper process cannot assume that it can inject turns into that pane's native thread. Use `peer-send.py` for visible pane input, or use `codex-thread.py` for machine-readable thread turns.

`codex-thread.py` does not claim that arbitrary Codex threads are native peers. It starts or resumes one thread per operation, submits a turn, and returns the result to the coordinator. The coordinator is responsible for fan-out, result aggregation, and follow-up prompts.

Do not read or modify Codex's SQLite state files directly. Use the app-server protocol and `codex resume` for supported history operations.

## Permissions

The helper defaults to `workspace-write` sandboxing and `never` approval prompts for non-interactive runs. This prevents a headless worker from hanging on a user approval prompt, but it can cause a command to fail instead of asking for permission. Use `--approval-policy on-request` only when a separate approval handler is available.

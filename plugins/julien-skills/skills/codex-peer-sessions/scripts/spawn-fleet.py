#!/usr/bin/env python3
"""Launch named Codex CLI workers in cmux or Herdr panes and workspaces."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import sys
import time
import uuid
from pathlib import Path

from cmux_client import (
    CmuxError,
    create_workspace,
    focus_pane,
    focused_pane,
    pane_split,
    press_enter,
    run_in_pane,
    run_in_workspace,
    write_terminal,
)
from fleet_events import append_event, initialize_event_logs
from herdr_client import (
    HerdrError,
)
from herdr_client import (
    agent_get as herdr_agent_get,
)
from herdr_client import (
    prompt_agent as herdr_prompt_agent,
)
from herdr_client import (
    agent_rename as herdr_agent_rename,
)
from herdr_client import (
    create_workspace as herdr_create_workspace,
)
from herdr_client import (
    pane_process_info as herdr_pane_process_info,
)
from herdr_client import (
    pane_rename as herdr_pane_rename,
)
from herdr_client import (
    pane_report_metadata as herdr_pane_metadata,
)
from herdr_client import (
    pane_split as herdr_pane_split,
)
from herdr_client import (
    require_caller_context as herdr_caller_context,
)
from herdr_client import (
    start_agent as herdr_start_agent,
)

HERDR_AGENT_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def state_root() -> Path:
    return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "peer-sessions"


def parse_specs(raw: list[str]) -> list[tuple[str, str]]:
    specs = []
    seen = set()
    for item in raw:
        if ":" not in item:
            raise SystemExit(f"error: {item!r} is not NAME:DIR")
        name, directory = item.split(":", 1)
        name = name.strip()
        directory = str(Path(directory.strip()).expanduser().resolve())
        if not name or name in seen:
            raise SystemExit(f"error: invalid or duplicate worker name: {name!r}")
        if not Path(directory).is_dir():
            raise SystemExit(f"error: worker directory does not exist: {directory}")
        seen.add(name)
        specs.append((name, directory))
    return specs


def worker_command(args: argparse.Namespace, directory: str) -> list[str]:
    extra_approve = "--approve-for-me" in args.codex_arg
    extra_sandbox = any(
        value == "--sandbox"
        or value.startswith("--sandbox=")
        or value == "-s"
        or (value.startswith("-s") and not value.startswith("--"))
        for value in args.codex_arg
    )
    approve_for_me = args.approve_for_me or extra_approve
    if approve_for_me and args.sandbox != "workspace-write":
        raise SystemExit(
            "error: --approve-for-me implies the workspace-write sandbox; "
            "do not combine it with another --sandbox value"
        )
    if approve_for_me and extra_sandbox:
        raise SystemExit(
            "error: --approve-for-me cannot be combined with a sandbox flag in "
            "--codex-arg"
        )
    command = ["codex", "-C", directory]
    if args.model:
        command += ["--model", args.model]
    if args.sandbox and not approve_for_me and not extra_sandbox:
        command += ["--sandbox", args.sandbox]
    if args.approve_for_me and not extra_approve:
        command.append("--approve-for-me")
    command += args.codex_arg
    # Keep Windows pane workers off the shared background server.
    if os.name == "nt" and "--no-daemon" not in command:
        command.append("--no-daemon")
    return command


def process_id(result: dict) -> int | str | None:
    for key in ("process_id", "pid", "processId"):
        if result.get(key) is not None:
            return result[key]
    return None


def codex_pid(process_info: dict) -> int | str | None:
    """Return the exact foreground Codex PID reported for a Herdr pane."""
    for process in process_info.get("foreground_processes", []):
        argv = process.get("argv") or []
        if process.get("name") == "codex" or (argv and argv[0] == "codex"):
            return process.get("pid")
    return None


def herdr_codex_pid(pane_id: str) -> int | str | None:
    """Read a Codex PID without turning optional PID metadata into launch failure."""
    try:
        return codex_pid(herdr_pane_process_info(pane_id))
    except HerdrError:
        return None


def terminal_id(result: dict) -> str | None:
    for key in ("terminal_id", "terminalId"):
        if result.get(key):
            return result[key]
    return None


def resolve_backend(requested: str) -> str:
    """Preserve cmux defaults while preferring Herdr inside a Herdr pane."""
    if requested != "auto":
        if not shutil.which(requested):
            raise SystemExit(f"error: {requested!r} is not installed or not on PATH")
        return requested
    if os.environ.get("HERDR_ENV") == "1" and shutil.which("herdr"):
        return "herdr"
    if shutil.which("cmux"):
        return "cmux"
    raise SystemExit(
        "error: no usable backend; run inside Herdr or install cmux"
    )


def resolve_placement(requested: str, backend: str) -> str:
    """Choose a non-cluttering default without changing legacy explicit modes."""
    if requested == "auto":
        return "fleet-workspace" if backend == "herdr" else "workspace"
    if requested == "fleet-workspace" and backend != "herdr":
        raise SystemExit("error: fleet-workspace placement currently requires Herdr")
    return requested


def save_fleet(fleet_id: str, payload: dict) -> Path:
    root = state_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{fleet_id}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(path)
    return path


def print_cleanup(records: list[dict], backend: str) -> None:
    print("\nTeardown is off by default. When the user asks to stop this fleet:")
    pids = [str(record["pid"]) for record in records if record.get("pid") is not None]
    if pids:
        if os.name == "nt":
            print("  Stop-Process -Id " + ",".join(pids))
        else:
            print("  kill " + " ".join(pids))
    elif backend == "cmux":
        print("  # Find exact Codex PIDs with: cmux terminal <id> process show")
    pane_ids: list[str] = []
    workspace_ids: list[str] = []
    for record in records:
        if record.get("placement") == "split" and record.get("pane_id"):
            pane_ids.append(str(record["pane_id"]))
        elif record.get("workspace_id"):
            workspace_ids.append(str(record["workspace_id"]))
    for pane_id in dict.fromkeys(pane_ids):
        print(f"  {backend} pane close {pane_id}")
    for workspace_id in dict.fromkeys(workspace_ids):
        print(f"  {backend} workspace close {workspace_id}")
    print(
        "  # Do not use pkill codex; unrelated Codex sessions may still belong to the user."
    )


def print_recovery(records: list[dict], backend: str) -> None:
    """Print pane-scoped inspection and retry commands after launch failure."""
    if backend != "herdr":
        return
    print("Recovery for the created Herdr panes:")
    for record in records:
        pane_id = record.get("pane_id")
        if not pane_id:
            continue
        print(
            f"  herdr pane read {pane_id} "
            "--source recent-unwrapped --lines 80"
        )
        command = record.get("command") or []
        if command and record.get("name"):
            agent_args = command[1:] if command[0] == "codex" else command
            retry = [
                "herdr",
                "agent",
                "start",
                str(record["name"]),
                "--kind",
                "codex",
                "--pane",
                str(pane_id),
                "--",
                *agent_args,
            ]
            print("  # After fixing the reported cause: " + shlex.join(retry))


def fleet_payload(
    fleet_id: str,
    backend: str,
    args: argparse.Namespace,
    records: list[dict],
    status: str,
    error: str | None = None,
) -> dict:
    payload = {
        "fleet_id": fleet_id,
        "created_at": time.time(),
        "backend": backend,
        "placement": args.placement,
        "fleet_label": args.fleet_label or fleet_id,
        "fleet_workspace_id": (
            records[0].get("workspace_id")
            if args.placement == "fleet-workspace" and records
            else None
        ),
        "status": status,
        "workers": records,
    }
    if error is not None:
        payload["error"] = error
    return payload


def start_herdr_worker(
    name: str,
    directory: str,
    pane_id: str,
    workspace_id: str | None,
    placement: str,
    args: argparse.Namespace,
) -> dict:
    """Start one Herdr worker and verify its visible identity."""
    command = worker_command(args, directory)
    record = {
        "name": name,
        "backend": "herdr",
        "directory": directory,
        "placement": placement,
        "pane_id": pane_id,
        "workspace_id": workspace_id,
        "pid": None,
        "command": command,
        "name_verified": False,
        "herdr_target": pane_id,
        "startup_status": "starting",
    }
    try:
        run_result = herdr_start_agent(name, pane_id, command)
        record["run_result"] = run_result
        herdr_pane_rename(pane_id, name)
        herdr_pane_metadata(pane_id, "codex-peer-sessions", name, name)
        herdr_agent_rename(pane_id, name)
        agent = herdr_agent_get(name)
        if agent.get("pane_id") != pane_id or agent.get("name") != name:
            raise HerdrError(
                f"Herdr worker name verification failed for {name!r} in pane {pane_id}"
            )
    except HerdrError as error:
        record["pid"] = herdr_codex_pid(pane_id)
        record["startup_status"] = "failed"
        record["startup_error"] = str(error)
        pane_output = getattr(error, "pane_output", None)
        if pane_output:
            record["pane_output"] = pane_output
        error.partial_record = record
        raise
    pid = herdr_codex_pid(pane_id)
    record.update(
        {
            "pid": pid or process_id(agent),
            "agent": agent,
            "name_verified": True,
            "startup_status": "ready",
        }
    )
    return record


def launch_herdr_fleet_workspace(
    specs: list[tuple[str, str]],
    args: argparse.Namespace,
    fleet_id: str,
) -> list[dict]:
    """Place one visible fleet in one named Herdr workspace."""
    label = args.fleet_label or fleet_id
    workspace = herdr_create_workspace(label, specs[0][1], args.focus)
    workspace_id = workspace["workspace"]["workspace_id"]
    root_pane_id = workspace["root_pane"]["pane_id"]
    split_queue: list[tuple[str, int]] = [(root_pane_id, 0)]
    records: list[dict] = []
    try:
        for index, (name, directory) in enumerate(specs):
            if index == 0:
                pane_id = root_pane_id
            else:
                anchor, depth = split_queue.pop(0)
                direction = "right" if depth % 2 == 0 else "down"
                pane = herdr_pane_split(anchor, direction, directory, False)
                pane_id = pane["pane_id"]
                split_queue.extend(((anchor, depth + 1), (pane_id, depth + 1)))
            records.append(
                start_herdr_worker(
                    name,
                    directory,
                    pane_id,
                    workspace_id,
                    "fleet-workspace",
                    args,
                )
            )
    except (HerdrError, OSError) as error:
        partial_record = getattr(error, "partial_record", None)
        if partial_record:
            records.append(partial_record)
        elif not records:
            records.append(
                {
                    "name": specs[0][0],
                    "backend": "herdr",
                    "placement": "fleet-workspace",
                    "workspace_id": workspace_id,
                }
            )
        error.cleanup_records = records
        raise
    return records


def launch_worker(
    name: str,
    directory: str,
    args: argparse.Namespace,
    anchor: str | None,
    backend: str,
) -> tuple[dict, str | None]:
    command = worker_command(args, directory)
    if backend == "herdr":
        if not HERDR_AGENT_NAME.fullmatch(name):
            raise HerdrError(
                f"invalid Herdr agent name {name!r}; use [a-z][a-z0-9_-] and at most 32 characters"
            )
        if args.placement == "split":
            if anchor is None:
                anchor = herdr_caller_context()["pane_id"]
            pane = herdr_pane_split(anchor, args.direction, directory, args.focus)
            pane_id = pane["pane_id"]
            return start_herdr_worker(
                name,
                directory,
                pane_id,
                pane.get("workspace_id"),
                "split",
                args,
            ), pane_id

        workspace = herdr_create_workspace(
            f"{args.prefix}-{name}", directory, args.focus
        )
        workspace_id = workspace["workspace"]["workspace_id"]
        pane_id = workspace["root_pane"]["pane_id"]
        return start_herdr_worker(
            name,
            directory,
            pane_id,
            workspace_id,
            "workspace",
            args,
        ), None

    if args.placement == "split":
        if anchor is None:
            pane = focused_pane()
            anchor = pane.get("id")
        split = pane_split(anchor, args.direction)
        pane_id = split["pane_id"]
        run_result = run_in_pane(pane_id, command)
        record = {
            "name": name,
            "backend": "cmux",
            "directory": directory,
            "placement": "split",
            "pane_id": pane_id,
            "terminal_id": split.get("terminal_id") or terminal_id(run_result),
            "workspace_id": split.get("workspace_id"),
            "pid": process_id(run_result),
            "command": command,
            "run_result": run_result,
        }
        if args.focus:
            focus_pane(pane_id)
        return record, pane_id

    workspace = create_workspace(f"{args.prefix}-{name}")
    workspace_id = workspace["workspace_id"]
    run_result = run_in_workspace(workspace_id, command)
    record = {
        "name": name,
        "backend": "cmux",
        "directory": directory,
        "placement": "workspace",
        "pane_id": run_result.get("pane_id"),
        "terminal_id": terminal_id(run_result),
        "workspace_id": workspace_id,
        "pid": process_id(run_result),
        "command": command,
        "run_result": run_result,
    }
    if args.focus:
        from cmux_client import call

        call("workspace", workspace_id, "focus")
    return record, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Launch Codex CLI workers in cmux or Herdr panes and workspaces.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("specs", nargs="+", metavar="NAME:DIR")
    parser.add_argument(
        "--backend", choices=("auto", "cmux", "herdr"), default="auto"
    )
    parser.add_argument(
        "--placement",
        choices=("auto", "fleet-workspace", "split", "workspace"),
        default="auto",
    )
    parser.add_argument("--direction", choices=("right", "down"), default="right")
    parser.add_argument("--focus", action="store_true")
    parser.add_argument("--prefix", default="codex-peer")
    parser.add_argument("--fleet-id")
    parser.add_argument("--fleet-label")
    parser.add_argument("--model")
    parser.add_argument(
        "--sandbox",
        choices=("read-only", "workspace-write", "danger-full-access"),
        default="workspace-write",
    )
    parser.add_argument("--approve-for-me", action="store_true")
    parser.add_argument("--codex-arg", action="append", default=[])
    parser.add_argument(
        "--herdr-socket",
        help="Explicit Herdr socket for callers whose tool subprocess lost HERDR_ENV",
    )
    parser.add_argument(
        "--prompt",
        help="Send one initial prompt to every pane worker after launch.",
    )
    parser.add_argument("--startup-delay", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    specs = parse_specs(args.specs)
    worker_command(args, specs[0][1])
    backend = resolve_backend(args.backend)
    args.placement = resolve_placement(args.placement, backend)
    if args.herdr_socket:
        os.environ["HERDR_SOCKET_PATH"] = args.herdr_socket
    if backend == "herdr" and not args.dry_run:
        if args.placement == "split":
            herdr_caller_context()
        elif os.environ.get("HERDR_ENV") != "1" and not os.environ.get(
            "HERDR_SOCKET_PATH"
        ):
            raise HerdrError(
                "Herdr workspace control requires HERDR_ENV=1 or --herdr-socket"
            )
    fleet_id = args.fleet_id or f"fleet-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    if args.dry_run:
        print(f"fleet {fleet_id} (dry run, backend {backend})")
        for name, directory in specs:
            print(f"+ {name}: {worker_command(args, directory)!r}")
        if args.placement == "split":
            if backend == "herdr":
                print("placement requires HERDR_PANE_ID from a Herdr-managed caller")
            else:
                print("placement requires a focused pane in an active cmux session")
        elif args.placement == "fleet-workspace":
            print(f"placement creates one named {backend} workspace for the fleet")
        else:
            print(f"placement creates one {backend} workspace per worker")
        return 0
    records = []
    anchor = None
    try:
        if backend == "herdr" and args.placement == "fleet-workspace":
            records = launch_herdr_fleet_workspace(specs, args, fleet_id)
        else:
            for name, directory in specs:
                record, anchor = launch_worker(name, directory, args, anchor, backend)
                records.append(record)
        if args.prompt:
            for record in records:
                if backend == "herdr":
                    job_id = uuid.uuid4().hex
                    delivery = herdr_prompt_agent(
                        record["pane_id"], job_id, args.prompt
                    )
                    record["last_job"] = {
                        "job_id": job_id,
                        "delivery_status": delivery["delivery_status"],
                        "accepted_at": time.time(),
                    }
                elif record.get("terminal_id"):
                    time.sleep(args.startup_delay)
                    write_terminal(record["terminal_id"], args.prompt)
                    press_enter(record["terminal_id"])
    except (CmuxError, HerdrError, OSError) as error:
        print(f"error: fleet launch stopped: {error}", file=sys.stderr)
        cleanup_records = getattr(error, "cleanup_records", records)
        partial_record = getattr(error, "partial_record", None)
        if partial_record and partial_record not in cleanup_records:
            cleanup_records.append(partial_record)
        if cleanup_records:
            payload = fleet_payload(
                fleet_id,
                backend,
                args,
                cleanup_records,
                "failed",
                str(error),
            )
            initialize_event_logs(payload)
            append_event(payload, "fleet-failed", str(error))
            path = save_fleet(fleet_id, payload)
            print(f"metadata {path}", file=sys.stderr)
            print_recovery(cleanup_records, backend)
            print_cleanup(cleanup_records, backend)
        return 1

    payload = fleet_payload(fleet_id, backend, args, records, "ready")
    initialize_event_logs(payload)
    append_event(payload, "fleet-ready", f"backend={backend}; workers={len(records)}")
    for record in records:
        append_event(
            payload,
            "worker-ready",
            f"pane={record.get('pane_id') or '-'}; status={record.get('startup_status', 'ready')}",
            worker=record,
        )
    path = save_fleet(fleet_id, payload)
    print(f"fleet {fleet_id}")
    print(f"metadata {path}")
    for record in records:
        ids = [f"pane {record.get('pane_id')}"] if record.get("pane_id") else []
        if record.get("terminal_id"):
            ids.append(f"terminal {record['terminal_id']}")
        if record.get("workspace_id"):
            ids.append(f"workspace {record['workspace_id']}")
        if record.get("pid") is not None:
            ids.append(f"pid {record['pid']}")
        print(f"+ {record['name']}: " + ", ".join(ids))
    print_cleanup(records, backend)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

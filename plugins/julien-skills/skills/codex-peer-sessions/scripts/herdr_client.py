#!/usr/bin/env python3
"""Small stdlib-only client for Herdr's JSON command-line interface."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import re
from typing import Any


class HerdrError(RuntimeError):
    """A Herdr command failed."""


def pane_shell_arg(value: str) -> str:
    """Translate absolute Windows paths for Herdr's Git Bash pane shell."""
    if os.name == "nt" and re.match(r"^[A-Za-z]:[\\/]", value):
        tail = value[3:].replace("\\", "/")
        return f"/{value[0].lower()}/{tail}"
    return value


def require_control_context() -> None:
    """Reject implicit control of an unrelated default Herdr session."""
    if os.environ.get("HERDR_ENV") != "1" and not os.environ.get(
        "HERDR_SOCKET_PATH"
    ):
        raise HerdrError(
            "Herdr control requires a Herdr-managed caller or an explicit "
            "HERDR_SOCKET_PATH"
        )


def call(*args: str) -> Any:
    """Run one Herdr request and unwrap its JSON result envelope."""
    require_control_context()
    result = subprocess.run(
        ["herdr", *args],
        capture_output=True,
        check=False,
        text=True,
    )
    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    if not output and result.returncode == 0:
        return None
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        combined = "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part.strip()
        )
        raise HerdrError(
            f"herdr {' '.join(args)} returned non-JSON output:\n{combined}"
        ) from error
    if isinstance(payload, dict) and payload.get("error") is not None:
        raise HerdrError(f"herdr {' '.join(args)}: {payload['error']}")
    if result.returncode != 0:
        raise HerdrError(f"herdr {' '.join(args)}: {output}")
    if isinstance(payload, dict) and "result" in payload:
        return payload["result"]
    return payload


def call_text(*args: str) -> str:
    """Run a Herdr command whose successful output is plain terminal text."""
    require_control_context()
    result = subprocess.run(
        ["herdr", *args],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        output = (result.stderr or "").strip() or (result.stdout or "").strip()
        raise HerdrError(f"herdr {' '.join(args)}: {output}")
    return result.stdout.rstrip("\n")


def require_caller_context() -> dict[str, str]:
    """Return the explicit Herdr caller IDs or reject unsafe outside control."""
    if os.environ.get("HERDR_ENV") != "1":
        raise HerdrError(
            "HERDR_ENV is not 1; start the coordinating Codex session inside Herdr"
        )
    pane_id = os.environ.get("HERDR_PANE_ID")
    workspace_id = os.environ.get("HERDR_WORKSPACE_ID")
    if not pane_id or not workspace_id:
        raise HerdrError("Herdr caller context is missing pane or workspace IDs")
    return {"pane_id": pane_id, "workspace_id": workspace_id}


def pane_split(
    pane_id: str,
    direction: str,
    directory: str,
    focus: bool,
) -> dict[str, Any]:
    value = call(
        "pane",
        "split",
        "--pane",
        pane_id,
        "--direction",
        direction,
        "--cwd",
        directory,
        "--focus" if focus else "--no-focus",
    )
    pane = value.get("pane") if isinstance(value, dict) else None
    if not isinstance(pane, dict) or not pane.get("pane_id"):
        raise HerdrError(f"herdr pane split returned {value!r}")
    return pane


def pane_rename(pane_id: str, label: str) -> Any:
    """Give a pane a stable human-readable label."""
    return call("pane", "rename", pane_id, label)


def pane_report_metadata(
    pane_id: str,
    source: str,
    display_agent: str,
    title: str,
) -> Any:
    """Publish display-only labels independently of agent lifecycle detection."""
    return call(
        "pane",
        "report-metadata",
        pane_id,
        "--source",
        source,
        "--display-agent",
        display_agent,
        "--title",
        title,
    )


def pane_process_info(pane_id: str) -> dict[str, Any]:
    """Return foreground process information for one pane."""
    value = call("pane", "process-info", "--pane", pane_id)
    if isinstance(value, dict) and isinstance(value.get("process_info"), dict):
        return value["process_info"]
    if isinstance(value, dict):
        return value
    raise HerdrError(f"herdr pane process-info returned {value!r}")


def pane_read(pane_id: str, lines: int = 80) -> str:
    """Read recent plain text from a pane without requiring a live agent."""
    return call_text(
        "pane",
        "read",
        pane_id,
        "--source",
        "recent-unwrapped",
        "--lines",
        str(lines),
    )


def startup_error(pane_id: str, original: HerdrError) -> HerdrError:
    """Add exact pane evidence when an agent exits before Herdr sees readiness."""
    process_info: dict[str, Any] = {}
    try:
        process_info = pane_process_info(pane_id)
    except HerdrError:
        pass
    processes = process_info.get("foreground_processes", [])
    codex_running = any(
        process.get("name") == "codex"
        or any(str(value).rsplit("/", 1)[-1] == "codex" for value in process.get("argv") or [])
        for process in processes
    )
    try:
        output = pane_read(pane_id).strip()
    except HerdrError:
        output = ""
    state = (
        f"Codex startup failed before readiness in pane {pane_id}"
        if codex_running
        else f"Codex exited before reporting ready in pane {pane_id}"
    )
    details = [state, f"Herdr reported: {original}"]
    if output:
        details.append(f"Pane output:\n{output}")
    details.append(
        f"Inspect this pane: herdr pane read {pane_id} "
        "--source recent-unwrapped --lines 80"
    )
    error = HerdrError("\n".join(details))
    error.pane_id = pane_id
    error.pane_output = output or None
    error.early_exit = not codex_running
    return error


def create_workspace(
    name: str,
    directory: str,
    focus: bool,
) -> dict[str, Any]:
    value = call(
        "workspace",
        "create",
        "--cwd",
        directory,
        "--label",
        name,
        "--focus" if focus else "--no-focus",
    )
    if not isinstance(value, dict):
        raise HerdrError(f"herdr workspace create returned {value!r}")
    workspace = value.get("workspace")
    root_pane = value.get("root_pane")
    if not isinstance(workspace, dict) or not workspace.get("workspace_id"):
        raise HerdrError(f"herdr workspace create returned {value!r}")
    if not isinstance(root_pane, dict) or not root_pane.get("pane_id"):
        raise HerdrError(f"herdr workspace create returned {value!r}")
    return value


def start_agent(
    name: str,
    pane_id: str,
    command: list[str],
    retry_seconds: float = 5.0,
) -> dict[str, Any]:
    """Start Codex, retrying only Herdr's fresh-pane readiness race."""
    deadline = time.time() + retry_seconds
    while True:
        try:
            value = call(
                "agent",
                "start",
                name,
                "--kind",
                "codex",
                "--pane",
                pane_id,
                "--",
                *command[1:],
            )
            return value if isinstance(value, dict) else {"result": value}
        except HerdrError as error:
            if "agent_pane_busy" not in str(error):
                raise startup_error(pane_id, error) from error
            if time.time() >= deadline:
                executable = pane_shell_arg(shutil.which(command[0]) or command[0])
                arguments = [pane_shell_arg(value) for value in command[1:]]
                call("pane", "run", pane_id, executable, *arguments)
                ready_deadline = time.time() + 15
                while True:
                    try:
                        agent = agent_get(pane_id)
                    except HerdrError:
                        agent = {}
                    detected = agent.get("agent") == "codex" and agent.get(
                        "agent_status"
                    ) in {"idle", "done", "blocked", "working"}
                    if agent.get("interactive_ready") or detected:
                        return {
                            "agent": agent,
                            "startup_transport": "pane-run",
                        }
                    if time.time() >= ready_deadline:
                        raise startup_error(pane_id, error) from error
                    time.sleep(0.3)
            time.sleep(0.3)


def agent_get(name: str) -> dict[str, Any]:
    value = call("agent", "get", name)
    if isinstance(value, dict) and isinstance(value.get("agent"), dict):
        return value["agent"]
    return value if isinstance(value, dict) else {"result": value}


def agent_rename(target: str, name: str) -> Any:
    """Assign a human-readable name to the live agent in one pane."""
    return call("agent", "rename", target, name)


def agent_prompt(name: str, message: str) -> Any:
    return call("agent", "prompt", name, message)


def pane_send_keys(pane_id: str, *keys: str) -> Any:
    """Send a small, explicit key sequence to one recorded pane."""
    return call("pane", "send-keys", pane_id, *keys)


def agent_visible_text(name: str, lines: int = 80) -> str:
    return call_text(
        "agent", "read", name, "--source", "visible", "--lines", str(lines)
    )


def prompt_agent(
    target: str,
    job_id: str,
    message: str,
    timeout_seconds: float = 8.0,
) -> dict[str, Any]:
    """Submit one identified turn and prove that Codex started it."""
    before = agent_get(target)
    if before.get("interactive_ready") is False:
        raise HerdrError(f"Codex is not interactive-ready in {target}")
    if before.get("agent_status") == "working":
        raise HerdrError(
            f"Codex is already working in {target}; wait for a settled state "
            "before sending another turn"
        )
    visible = agent_visible_text(target)
    visible_lower = visible.lower()
    setup_markers = (
        "do you trust the contents",
        "review the following hooks",
        "press enter to continue",
    )
    if any(marker in visible_lower for marker in setup_markers):
        raise HerdrError(
            f"Codex setup screen is blocking prompt delivery in {target}; "
            "resolve it before retrying"
        )

    tagged_message = f"[codex-peer job {job_id}]\n{message}"
    try:
        call(
            "agent",
            "prompt",
            target,
            tagged_message,
            "--wait",
            "--until",
            "working",
            "--timeout",
            str(int(timeout_seconds * 1000)),
        )
    except HerdrError as error:
        if "agent_prompt_stalled" not in str(error) and "timeout" not in str(error):
            raise
        after_visible = agent_visible_text(target)
        pasted_now = (
            "[pasted content" in after_visible.lower()
            and "[pasted content" not in visible_lower
        )
        if not pasted_now:
            raise
        pane_send_keys(target, "enter")
    deadline = time.time() + timeout_seconds
    before_seq = before.get("state_change_seq")
    before_status = before.get("agent_status")
    while True:
        current = agent_get(target)
        changed = (
            current.get("state_change_seq") != before_seq
            or current.get("agent_status") != before_status
        )
        if changed and current.get("agent_status") in {
            "working",
            "blocked",
            "done",
            "idle",
        }:
            return {
                "delivery_status": "accepted",
                "job_id": job_id,
                "agent": current,
            }
        if time.time() >= deadline:
            raise HerdrError(
                f"prompt delivery is uncertain for job {job_id} in {target}; "
                "Herdr returned without a Codex state change"
            )
        time.sleep(0.2)


def agent_read(name: str, lines: int = 120) -> Any:
    return call_text(
        "agent",
        "read",
        name,
        "--source",
        "recent-unwrapped",
        "--lines",
        str(lines),
    )


def wait_agent(name: str, timeout_seconds: float = 300.0) -> dict[str, Any]:
    value = call(
        "agent",
        "wait",
        name,
        "--until",
        "idle",
        "--until",
        "done",
        "--until",
        "blocked",
        "--timeout",
        str(int(timeout_seconds * 1000)),
    )
    return value if isinstance(value, dict) else {"result": value}


def pane_send_text(pane_id: str, message: str) -> Any:
    return call("pane", "send-text", pane_id, message)

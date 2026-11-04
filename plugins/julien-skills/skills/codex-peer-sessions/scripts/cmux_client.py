#!/usr/bin/env python3
"""Small stdlib-only client for the current cmux scoped JSON API."""

from __future__ import annotations

import json
import subprocess
from typing import Any


class CmuxError(RuntimeError):
    """A cmux command failed."""


def call(*args: str) -> Any:
    """Run one cmux request and unwrap the optional JSON response envelope."""
    result = subprocess.run(
        ["cmux", "--json", *args],
        capture_output=True,
        check=False,
        text=True,
    )
    output = (result.stdout or "").strip()
    if not output:
        output = (result.stderr or "").strip()
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise CmuxError(
            f"cmux {' '.join(args)} returned non-JSON output:\n{output}"
        ) from error
    if result.returncode != 0 or (
        isinstance(payload, dict) and payload.get("code")
    ):
        message = payload.get("message", output) if isinstance(payload, dict) else output
        raise CmuxError(f"cmux {' '.join(args)}: {message}")
    if isinstance(payload, dict) and "value" in payload:
        return payload["value"]
    return payload


def focused_pane() -> dict[str, Any]:
    """Return the focused pane in the current cmux session."""
    panes = call("pane", "list")
    if not isinstance(panes, list):
        raise CmuxError(f"cmux pane list returned {panes!r}")
    for pane in panes:
        if pane.get("focused"):
            return pane
    raise CmuxError(
        "no focused cmux pane found; run the launcher inside an active cmux session"
    )


def pane_split(pane_id: str, direction: str) -> dict[str, Any]:
    """Split a pane using the current API's supported directions."""
    flag = "--right" if direction == "right" else "--down"
    value = call("pane", pane_id, "split", flag)
    if not isinstance(value, dict) or not value.get("pane_id"):
        raise CmuxError(f"cmux pane split returned {value!r}")
    return value


def run_in_pane(pane_id: str, argv: list[str]) -> dict[str, Any]:
    """Start a command in an existing pane."""
    value = call("pane", pane_id, "run", "--", *argv)
    return value if isinstance(value, dict) else {"result": value}


def create_workspace(name: str) -> dict[str, Any]:
    """Create a workspace and return its durable identifiers."""
    value = call("workspace", "create", "--name", name)
    if not isinstance(value, dict) or not value.get("workspace_id"):
        raise CmuxError(f"cmux workspace create returned {value!r}")
    return value


def run_in_workspace(workspace_id: str, argv: list[str]) -> dict[str, Any]:
    """Start a command in a workspace's root terminal."""
    value = call("workspace", workspace_id, "run", "--", *argv)
    return value if isinstance(value, dict) else {"result": value}


def write_terminal(terminal_id: str, text: str) -> Any:
    """Write text without shell interpolation."""
    return call("terminal", terminal_id, "write", "--text", text)


def press_enter(terminal_id: str) -> Any:
    """Submit the text written to a terminal."""
    return call("terminal", terminal_id, "keys", "enter")


def read_terminal(terminal_id: str) -> Any:
    """Read the visible terminal screen."""
    return call("terminal", terminal_id, "screen", "read")


def focus_pane(pane_id: str) -> Any:
    """Move cmux focus to one pane."""
    return call("pane", pane_id, "focus")

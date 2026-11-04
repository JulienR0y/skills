#!/usr/bin/env python3
"""Shared fleet metadata helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path


def root() -> Path:
    return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "peer-sessions"


def load_fleet(value: str) -> tuple[dict, Path]:
    candidate = Path(value).expanduser()
    path = candidate if candidate.suffix == ".json" else root() / f"{value}.json"
    if not path.is_file():
        raise SystemExit(f"fleet metadata not found: {path}")
    try:
        return json.loads(path.read_text()), path
    except json.JSONDecodeError as error:
        raise SystemExit(f"invalid fleet metadata: {path}") from error


def save_fleet(path_or_id: str | Path, payload: dict) -> Path:
    path = Path(path_or_id)
    if path.suffix != ".json":
        path = root() / f"{path}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(path)
    return path


def herdr_target(worker: dict) -> str:
    """Return the stable Herdr target recorded for a worker."""
    target = worker.get("pane_id") or worker.get("name")
    if not target:
        raise SystemExit("Herdr worker has neither a pane ID nor a name")
    return str(target)

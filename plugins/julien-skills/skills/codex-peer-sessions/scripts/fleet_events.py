"""Append-only Markdown event logs for one peer-session fleet."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from fleet_state import root


def _component(value: object) -> str:
    text = str(value)
    if not text or text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError(f"invalid event-log path component: {text!r}")
    return text


def _one_line(value: object) -> str:
    return " ".join(str(value).split()).replace("|", "\\|") or "-"


def normalize_event_type(value: object) -> str:
    """Return one stable kebab-case event type."""
    event_type = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    if not event_type:
        raise ValueError("event type must contain a letter or number")
    return event_type


def _worker_session_id(worker: dict) -> str | None:
    session = worker.get("agent_session") or worker.get("agent", {}).get(
        "agent_session"
    )
    return session.get("value") if isinstance(session, dict) else None


def initialize_event_logs(
    payload: dict, metadata_path: str | Path | None = None
) -> Path:
    """Create one fleet folder and record stable log paths in metadata."""
    fleet_id = _component(payload["fleet_id"])
    base = Path(metadata_path).parent if metadata_path else root()
    directory = base / fleet_id
    workers = directory / "workers"
    workers.mkdir(parents=True, exist_ok=True)
    timeline = directory / "timeline.md"
    timeline.touch(exist_ok=True)
    payload["timeline_log"] = str(timeline)
    for worker in payload.get("workers", []):
        path = workers / f"{_component(worker['name'])}.md"
        path.touch(exist_ok=True)
        worker["event_log"] = str(path)
    return directory


def append_event(
    payload: dict,
    event_type: str,
    detail: str,
    *,
    worker: dict | None = None,
    job_id: str | None = None,
    session_id: str | None = None,
    metadata_path: str | Path | None = None,
    reported_by: str | None = None,
) -> Path:
    """Append one normalized Markdown event to its single-owner log."""
    initialize_event_logs(payload, metadata_path)
    if worker is None:
        path = Path(payload["timeline_log"])
        owner = "coordinator"
    else:
        path = Path(worker["event_log"])
        owner = str(worker["name"])
        session_id = session_id or _worker_session_id(worker)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fields = [
        timestamp,
        normalize_event_type(event_type),
        f"worker={_one_line(owner)}",
    ]
    if reported_by:
        fields.append(f"reported_by={_one_line(reported_by)}")
    if session_id:
        fields.append(f"session={_one_line(session_id)}")
    if job_id:
        fields.append(f"job={_one_line(job_id)}")
    fields.append(_one_line(detail))
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write("- " + " | ".join(fields) + "\n")
    return path

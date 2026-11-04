#!/usr/bin/env python3
"""Append one event to a fleet timeline or worker-owned Markdown log."""

from __future__ import annotations

import argparse

from fleet_events import append_event
from fleet_state import load_fleet, save_fleet


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fleet", required=True)
    owner = parser.add_mutually_exclusive_group(required=True)
    owner.add_argument("--name")
    owner.add_argument("--coordinator", action="store_true")
    parser.add_argument("--event", required=True)
    parser.add_argument("--detail", required=True)
    parser.add_argument("--job-id")
    parser.add_argument("--session-id")
    parser.add_argument("--reported-by", choices=("worker", "coordinator"))
    args = parser.parse_args()

    payload, metadata_path = load_fleet(args.fleet)
    payload.setdefault("fleet_id", metadata_path.stem)
    worker = None
    if args.name:
        worker = next(
            (
                item
                for item in payload.get("workers", [])
                if item.get("name") == args.name
            ),
            None,
        )
        if worker is None:
            raise SystemExit(f"worker not found: {args.name}")
    path = append_event(
        payload,
        args.event,
        args.detail,
        worker=worker,
        job_id=args.job_id,
        session_id=args.session_id,
        metadata_path=metadata_path,
        reported_by=args.reported_by
        or ("coordinator" if args.coordinator else "worker"),
    )
    save_fleet(metadata_path, payload)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

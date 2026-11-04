#!/usr/bin/env python3
"""Wait for one acknowledged Herdr job and collect its terminal result."""

from __future__ import annotations

import argparse
import json
import os
import time

from fleet_events import append_event
from fleet_state import herdr_target, load_fleet, save_fleet
from herdr_client import agent_get, agent_read, wait_agent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fleet", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--lines", type=int, default=160)
    parser.add_argument("--herdr-socket")
    args = parser.parse_args()
    if args.herdr_socket:
        os.environ["HERDR_SOCKET_PATH"] = args.herdr_socket

    payload, path = load_fleet(args.fleet)
    payload.setdefault("fleet_id", path.stem)
    worker = next(
        (item for item in payload.get("workers", []) if item.get("name") == args.name),
        None,
    )
    if not worker:
        raise SystemExit(f"worker not found: {args.name}")
    if (worker.get("backend") or payload.get("backend")) != "herdr":
        raise SystemExit("peer-wait currently requires a Herdr worker")
    job = worker.get("last_job")
    if not job or not job.get("job_id"):
        raise SystemExit(f"worker {args.name} has no acknowledged job")
    if job.get("collection_status") == "collected":
        raise SystemExit(
            f"job {job['job_id']} for worker {args.name} is already collected"
        )

    target = herdr_target(worker)
    wait_agent(target, args.timeout)
    state = agent_get(target)
    output = agent_read(target, args.lines)
    status = state.get("agent_status", "unknown")
    job.update(
        {
            "terminal_status": status,
            "collection_status": "collected",
            "collected_at": time.time(),
        }
    )
    append_event(
        payload,
        "job-collected",
        f"terminal_status={status}",
        worker=worker,
        job_id=job["job_id"],
        session_id=(state.get("agent_session") or {}).get("value"),
        metadata_path=path,
    )
    save_fleet(path, payload)
    print(
        json.dumps(
            {
                "name": args.name,
                "job_id": job["job_id"],
                "status": status,
                "output": output,
            },
            indent=2,
        )
    )
    return 2 if status == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())

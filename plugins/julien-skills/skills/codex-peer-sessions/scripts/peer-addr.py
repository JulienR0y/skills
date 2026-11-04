#!/usr/bin/env python3
"""List workers in a Codex peer-session fleet."""

from __future__ import annotations

import argparse
import json

from fleet_state import herdr_target, load_fleet, save_fleet
from herdr_client import HerdrError, agent_get


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fleet", required=True, help="fleet ID or metadata JSON path")
    parser.add_argument("--name", help="show only one worker")
    parser.add_argument("--set-thread", nargs=2, metavar=("NAME", "THREAD_ID"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload, path = load_fleet(args.fleet)
    workers = payload.get("workers", [])
    if args.set_thread:
        name, thread_id = args.set_thread
        for worker in workers:
            if worker.get("name") == name:
                worker["thread_id"] = thread_id
                save_fleet(path, payload)
                break
        else:
            raise SystemExit(f"worker not found: {name}")

    if args.name:
        workers = [worker for worker in workers if worker.get("name") == args.name]
    if args.json:
        print(
            json.dumps(
                {
                    "fleet": payload.get("fleet_id"),
                    "metadata": str(path),
                    "workers": workers,
                },
                indent=2,
            )
        )
        return 0

    print(f"fleet {payload.get('fleet_id', path.stem)}")
    print(f"metadata {path}")
    for worker in workers:
        backend = worker.get("backend") or payload.get("backend") or "cmux"
        status = "-"
        if backend == "herdr":
            try:
                live_agent = agent_get(herdr_target(worker))
                status = live_agent.get("agent_status") or live_agent.get("status") or "-"
            except HerdrError:
                status = "unavailable"
        details = [
            f"backend={backend}",
            f"pane={worker.get('pane_id') or '-'}",
            f"terminal={worker.get('terminal_id') or '-'}",
            f"pid={worker.get('pid') or '-'}",
            f"thread={worker.get('thread_id') or '-'}",
            f"status={status}",
        ]
        print(f"{worker.get('name')}: " + " ".join(details))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read recent output from a Codex worker terminal."""

from __future__ import annotations

import argparse
import json
import os

from cmux_client import read_terminal
from fleet_state import herdr_target, load_fleet
from herdr_client import agent_read


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fleet", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--lines", type=int, default=120)
    parser.add_argument("--herdr-socket")
    args = parser.parse_args()
    if args.herdr_socket:
        os.environ["HERDR_SOCKET_PATH"] = args.herdr_socket

    payload, _ = load_fleet(args.fleet)
    worker = next(
        (item for item in payload.get("workers", []) if item.get("name") == args.name),
        None,
    )
    if not worker:
        raise SystemExit(f"worker not found: {args.name}")
    backend = worker.get("backend") or payload.get("backend") or "cmux"
    terminal_id = worker.get("terminal_id")
    if backend == "herdr":
        screen = agent_read(herdr_target(worker), args.lines)
    else:
        if not terminal_id:
            raise SystemExit(f"worker {args.name} has no terminal ID")
        screen = read_terminal(terminal_id)
    if args.json:
        print(
            json.dumps(
                {
                    "name": args.name,
                    "backend": backend,
                    "terminal": terminal_id,
                    "pane": worker.get("pane_id"),
                    "screen": screen,
                },
                indent=2,
            )
        )
    elif isinstance(screen, str):
        print(screen)
    else:
        print(json.dumps(screen, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

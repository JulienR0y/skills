#!/usr/bin/env python3
"""Send ordinary user input to a Codex worker terminal."""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

from cmux_client import CmuxError, press_enter, write_terminal
from fleet_events import append_event
from fleet_state import herdr_target, load_fleet, save_fleet
from herdr_client import HerdrError, pane_send_text, prompt_agent


def peer_message(sender: str, message: str) -> str:
    sender = sender.strip()
    if not sender or "\n" in sender or "\r" in sender:
        raise ValueError("sender must be one non-empty line")
    return f"Peer message from: {sender}\n\n{message}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fleet", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--sender", default="coordinator")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--message")
    group.add_argument("--message-file")
    parser.add_argument("--no-enter", action="store_true")
    parser.add_argument("--job-id")
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
    backend = worker.get("backend") or payload.get("backend") or "cmux"
    message = args.message
    if args.message_file:
        message = Path(args.message_file).read_text()
    try:
        message = peer_message(args.sender, message)
    except ValueError as error:
        parser.error(str(error))
    try:
        if backend == "herdr":
            if args.no_enter:
                pane_send_text(herdr_target(worker), message)
            else:
                job_id = args.job_id or uuid.uuid4().hex
                delivery = prompt_agent(herdr_target(worker), job_id, message)
                worker["last_job"] = {
                    "job_id": job_id,
                    "delivery_status": delivery["delivery_status"],
                    "collection_status": "pending",
                    "accepted_at": time.time(),
                }
                append_event(
                    payload,
                    "prompt-accepted",
                    "Herdr observed the turn enter working",
                    worker=worker,
                    job_id=job_id,
                    session_id=delivery.get("agent", {})
                    .get("agent_session", {})
                    .get("value"),
                    metadata_path=path,
                )
                save_fleet(path, payload)
        else:
            terminal_id = worker.get("terminal_id")
            if not terminal_id:
                raise SystemExit(f"worker {args.name} has no terminal ID")
            write_terminal(terminal_id, message)
            if not args.no_enter:
                press_enter(terminal_id)
    except (CmuxError, HerdrError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if backend == "herdr" and not args.no_enter:
        print(f"accepted job {job_id} by {args.name} via {backend}")
    else:
        print(f"sent to {args.name} via {backend}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Use Codex's app-server JSON-RPC protocol for persistent thread turns."""

from __future__ import annotations

import argparse
import json
import os
import queue
import select
import subprocess
import sys
import threading
import time
from typing import Any


class CodexRpcError(RuntimeError):
    """A Codex app-server request failed."""


class AppServer:
    def __init__(self) -> None:
        self.process = subprocess.Popen(
            ["codex", "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.pending: list[dict[str, Any]] = []
        self.next_id = 1
        self.output_queue: queue.Queue[str | None] | None = None
        if os.name == "nt":
            self.output_queue = queue.Queue()
            self.output_thread = threading.Thread(
                target=self._read_stdout,
                daemon=True,
            )
            self.output_thread.start()

    def _read_stdout(self) -> None:
        if self.process.stdout is None or self.output_queue is None:
            return
        for line in self.process.stdout:
            self.output_queue.put(line)
        self.output_queue.put(None)

    def send(self, payload: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise CodexRpcError("Codex app-server stdin is unavailable")
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()

    def read_event(self, timeout: float) -> dict[str, Any]:
        if self.process.stdout is None:
            raise CodexRpcError("Codex app-server stdout is unavailable")
        if self.output_queue is not None:
            try:
                line = self.output_queue.get(timeout=timeout)
            except queue.Empty as error:
                raise CodexRpcError(
                    "timed out waiting for Codex app-server"
                ) from error
        else:
            ready, _, _ = select.select([self.process.stdout], [], [], timeout)
            if not ready:
                raise CodexRpcError("timed out waiting for Codex app-server")
            line = self.process.stdout.readline()
        if not line:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise CodexRpcError(
                f"Codex app-server exited before replying{': ' + stderr.strip() if stderr.strip() else ''}"
            )
        try:
            return json.loads(line)
        except json.JSONDecodeError as error:
            raise CodexRpcError(f"invalid Codex app-server JSON: {line!r}") from error

    def request(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            event = self.read_event(max(0.01, deadline - time.monotonic()))
            if event.get("id") != request_id:
                self.pending.append(event)
                continue
            if "error" in event:
                raise CodexRpcError(json.dumps(event["error"], indent=2))
            return event.get("result", {})

    def initialize(self, timeout: float) -> None:
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex-peer-sessions",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
            timeout,
        )
        self.send({"method": "initialized", "params": {}})

    def wait_for_turn(
        self,
        thread_id: str,
        turn_id: str,
        timeout: float,
    ) -> tuple[str, dict[str, Any]]:
        deltas: list[str] = []
        deadline = time.monotonic() + timeout
        events = self.pending
        self.pending = []
        while True:
            if events:
                event = events.pop(0)
            else:
                event = self.read_event(max(0.01, deadline - time.monotonic()))
            method = event.get("method")
            params = event.get("params") or {}
            if params.get("threadId") != thread_id:
                continue
            if method == "item/agentMessage/delta":
                deltas.append(params.get("delta", ""))
            elif method == "turn/completed":
                turn = params.get("turn") or {}
                if turn.get("id") != turn_id:
                    continue
                if turn.get("status") != "completed":
                    raise CodexRpcError(json.dumps(turn, indent=2))
                return "".join(deltas), event
            elif method == "error":
                raise CodexRpcError(json.dumps(params, indent=2))
            elif method in {
                "item/commandExecution/requestApproval",
                "item/fileChange/requestApproval",
                "item/tool/requestUserInput",
            }:
                raise CodexRpcError(
                    "Codex requested user input while running headlessly: "
                    + json.dumps(params)
                )

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()


def thread_start_params(args: argparse.Namespace) -> dict[str, Any]:
    params: dict[str, Any] = {
        "cwd": os.path.abspath(os.path.expanduser(args.cwd)),
        "ephemeral": args.ephemeral,
        "approvalPolicy": args.approval_policy,
        "approvalsReviewer": "auto_review",
        "sandbox": args.sandbox,
    }
    if args.model:
        params["model"] = args.model
    return params


def set_name(server: AppServer, thread_id: str, name: str, timeout: float) -> None:
    server.request(
        "thread/name/set",
        {"threadId": thread_id, "name": name},
        timeout,
    )


def start_thread(args: argparse.Namespace) -> dict[str, Any]:
    server = AppServer()
    try:
        server.initialize(args.timeout)
        result = server.request(
            "thread/start",
            thread_start_params(args),
            args.timeout,
        )
        thread = result.get("thread", result)
        if args.name and not args.ephemeral:
            set_name(server, thread["id"], args.name, args.timeout)
            thread["name"] = args.name
        return thread
    finally:
        server.close()


def run_thread(args: argparse.Namespace) -> tuple[str, str, dict[str, Any]]:
    server = AppServer()
    try:
        server.initialize(args.timeout)
        if args.thread_id:
            result = server.request(
                "thread/resume",
                {"threadId": args.thread_id},
                args.timeout,
            )
            thread = result.get("thread", result)
            thread_id = args.thread_id
        else:
            result = server.request(
                "thread/start",
                thread_start_params(args),
                args.timeout,
            )
            thread = result.get("thread", result)
            thread_id = thread["id"]
        if args.name and not args.ephemeral:
            set_name(server, thread_id, args.name, args.timeout)
        turn_result = server.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": args.prompt}],
            },
            args.timeout,
        )
        turn = turn_result.get("turn", turn_result)
        turn_id = turn["id"]
        reply, completion = server.wait_for_turn(
            thread_id,
            turn_id,
            args.timeout,
        )
        return thread_id, reply, completion
    finally:
        server.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Operate Codex app-server threads.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_thread_options(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--cwd", default=os.getcwd())
        subparser.add_argument("--model")
        subparser.add_argument(
            "--sandbox",
            choices=("read-only", "workspace-write", "danger-full-access"),
            default="workspace-write",
        )
        subparser.add_argument(
            "--approval-policy",
            choices=("untrusted", "on-request", "never"),
            default="never",
        )
        subparser.add_argument("--ephemeral", action="store_true")
        subparser.add_argument("--timeout", type=float, default=600)

    start = subparsers.add_parser("start")
    add_thread_options(start)
    start.add_argument("--name")

    listing = subparsers.add_parser("list")
    listing.add_argument("--cwd")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--timeout", type=float, default=30)

    read = subparsers.add_parser("read")
    read.add_argument("--thread-id", required=True)
    read.add_argument("--include-turns", action="store_true")
    read.add_argument("--timeout", type=float, default=30)

    run = subparsers.add_parser("run")
    run.add_argument("--thread-id")
    run.add_argument("--prompt", required=True)
    run.add_argument("--cwd", default=os.getcwd())
    run.add_argument("--model")
    run.add_argument(
        "--sandbox",
        choices=("read-only", "workspace-write", "danger-full-access"),
        default="workspace-write",
    )
    run.add_argument(
        "--approval-policy",
        choices=("untrusted", "on-request", "never"),
        default="never",
    )
    run.add_argument("--ephemeral", action="store_true")
    run.add_argument("--name")
    run.add_argument("--timeout", type=float, default=600)

    args = parser.parse_args()
    try:
        if args.command == "start":
            print(json.dumps(start_thread(args), indent=2))
        elif args.command == "list":
            server = AppServer()
            try:
                server.initialize(args.timeout)
                params: dict[str, Any] = {"limit": args.limit}
                if args.cwd:
                    params["cwd"] = os.path.abspath(os.path.expanduser(args.cwd))
                result = server.request("thread/list", params, args.timeout)
            finally:
                server.close()
            print(json.dumps(result, indent=2))
        elif args.command == "read":
            server = AppServer()
            try:
                server.initialize(args.timeout)
                result = server.request(
                    "thread/read",
                    {"threadId": args.thread_id, "includeTurns": args.include_turns},
                    args.timeout,
                )
            finally:
                server.close()
            print(json.dumps(result, indent=2))
        else:
            thread_id, reply, completion = run_thread(args)
            print(
                json.dumps(
                    {"thread_id": thread_id, "reply": reply, "completion": completion},
                    indent=2,
                )
            )
    except (CodexRpcError, OSError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

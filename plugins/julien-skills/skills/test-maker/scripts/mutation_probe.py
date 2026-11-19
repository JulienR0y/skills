#!/usr/bin/env python3
"""Measure how many deliberate source mutations a test command catches.

Each mutant is a small text edit to a source file. The probe applies one mutant,
runs the test command, records whether it failed (mutant killed) or passed
(mutant survived), and restores the file before the next mutant.

Usage:
    python mutation_probe.py --mutants mutants.json --cmd "pytest tests/foo_test.py -q"
    python mutation_probe.py --mutants mutants.json --cmd "npx vitest run src/foo.test.ts" --fail-under 90

mutants.json is a list of objects:
    {"name": "to_dict swaps k and keyword_k",
     "file": "app/search_settings.py",
     "edits": [{"old": "\"k\": self._k,", "new": "\"k\": self._keyword_k,"}]}
A single edit may be written as top-level "old"/"new" instead of "edits".
Paths are relative to --cwd (default: current directory).

A run longer than --timeout counts as killed; the command's whole process tree is
stopped. If the probe itself is killed hard, restore the sources with git.

Exit codes: 0 done (and score >= --fail-under if given), 1 score below --fail-under,
2 bad input or a baseline that does not pass.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

FAILED_TEST = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)


class BadInput(Exception):
    """The mutants file or a mutant cannot be applied as written."""


def load_mutants(path: Path, cwd: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise BadInput(f"{path}: expected a non-empty JSON list of mutants")
    mutants = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise BadInput(f"mutant {index + 1}: expected a JSON object, got {item!r}")
        name = item.get("name") or f"mutant {index + 1}"
        edits = item.get("edits") or [{"old": item.get("old"), "new": item.get("new")}]
        target = cwd / item["file"]
        if not target.is_file():
            raise BadInput(f"{name}: file not found: {target}")
        source = target.read_bytes().decode("utf-8")
        # Edits apply in order, so each 'old' must match once in the text left by the previous edits.
        for edit in edits:
            old, new = edit.get("old"), edit.get("new")
            if not old or new is None or old == new:
                raise BadInput(f"{name}: each edit needs a non-empty 'old' and a different 'new'")
            count = source.count(old)
            if count != 1:
                raise BadInput(f"{name}: 'old' must match exactly once in {item['file']}, found {count}: {old!r}")
            source = source.replace(old, new, 1)
        mutants.append({"name": name, "file": target, "edits": edits})
    return mutants


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill the shell and everything it started; a surviving child keeps the pipes open."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run(cmd: str, cwd: Path, timeout: int) -> tuple[bool, str, float]:
    started = time.monotonic()
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **group,
    )
    try:
        output, _ = proc.communicate(timeout=timeout)
        passed = proc.returncode == 0
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        output, _ = proc.communicate()
        output = f"{output or ''}\ntimed out after {timeout}s"
        passed = False
    except BaseException:
        # The child runs in its own process group, so Ctrl+C never reaches it.
        kill_tree(proc)
        proc.wait()
        raise
    return passed, output, time.monotonic() - started


def last_line(output: str) -> str:
    lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
    return lines[-1][:160] if lines else ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mutants", required=True, type=Path, help="JSON list of mutants")
    parser.add_argument("--cmd", required=True, help="test command; exit code 0 means the tests passed")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(), help="repository root (default: current directory)")
    parser.add_argument("--timeout", type=int, default=900, help="seconds per test run (a timeout counts as killed)")
    parser.add_argument("--report", type=Path, help="write per-mutant results as JSON here")
    parser.add_argument("--fail-under", type=float, help="exit 1 if the kill percentage is below this")
    return parser.parse_args()


def write_with_mtime(path: Path, content: bytes, mtime_ns: int) -> None:
    path.write_bytes(content)
    os.utime(path, ns=(mtime_ns, mtime_ns))


def probe(mutants: list[dict], cmd: str, cwd: Path, timeout: int) -> list[dict]:
    """Run the tests once per mutant; every touched file is restored even on error.

    Caches such as Python's bytecode trust a file's size and whole-second mtime, so a
    same-length mutant written within a second would run stale code. Each mutant gets
    a unique mtime, and restoring puts back the original bytes and mtime.
    """
    originals = {m["file"]: (m["file"].read_bytes(), m["file"].stat().st_mtime_ns) for m in mutants}
    results = []
    try:
        for index, mutant in enumerate(mutants, start=1):
            content, mtime_ns = originals[mutant["file"]]
            source = content.decode("utf-8")
            for edit in mutant["edits"]:
                source = source.replace(edit["old"], edit["new"], 1)
            write_with_mtime(mutant["file"], source.encode("utf-8"), mtime_ns + index * 1_000_000_000)
            try:
                passed, output, _ = run(cmd, cwd, timeout)
            finally:
                write_with_mtime(mutant["file"], content, mtime_ns)
            killed_by = sorted(set(FAILED_TEST.findall(output)))
            results.append({"name": mutant["name"], "killed": not passed, "killed_by": killed_by[:5], "summary": last_line(output)})
            status = "KILLED  " if not passed else "SURVIVED"
            print(f"{status} {mutant['name']} :: {last_line(output)}", flush=True)
    finally:
        for path, (content, mtime_ns) in originals.items():
            write_with_mtime(path, content, mtime_ns)
    return results


def report(results: list[dict], report_path: Path | None) -> float:
    killed = sum(r["killed"] for r in results)
    score = 100.0 * killed / len(results)
    print(f"\n{killed}/{len(results)} mutants killed ({score:.0f}%)")
    survivors = [r["name"] for r in results if not r["killed"]]
    if survivors:
        print("Survivors:\n  - " + "\n  - ".join(survivors))
    if report_path:
        report_path.write_text(json.dumps({"killed": killed, "total": len(results), "results": results}, indent=2), encoding="utf-8")
    return score


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        # A piped Windows console uses a legacy code page; never crash on a test runner's symbols.
        stream.reconfigure(errors="replace")
    args = parse_args()
    cwd = args.cwd.resolve()
    try:
        mutants = load_mutants(args.mutants, cwd)
    except (BadInput, OSError, KeyError, ValueError, TypeError, AttributeError) as exc:
        print(f"Bad mutants file: {exc}", file=sys.stderr)
        return 2

    passed, output, seconds = run(args.cmd, cwd, args.timeout)
    if not passed:
        print(f"Baseline run failed ({seconds:.0f}s); fix the tests before probing.\n{output[-2000:]}")
        return 2
    print(f"Baseline passed in {seconds:.0f}s: {last_line(output)}", flush=True)

    score = report(probe(mutants, args.cmd, cwd, args.timeout), args.report)
    if args.fail_under is not None and score < args.fail_under:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Calibrate the Jev layer: decide which questions may block, and at what threshold.

  python jev_calibrate.py label <repo> <rev> <labels.json>   build a labelled set from a repo (no network)
  python jev_calibrate.py run <labels.json>                  ask Jev about each function (sends source to
                                                             api.typesafe.ai) and write jev_calibration.json

Labels come from measured syntax facts, not opinion: SRP positives are functions of 150+ lines with 15+ ifs;
OCP positives compare one string 3+ times; DIP positives import inside the function and construct a
capitalised class. Negatives are small pure helpers (8 to 25 lines, at most 2 ifs, no I/O, no construction).
The naming question has no automatic labels, so it never blocks. A question may block at the lowest
threshold in THRESHOLDS where precision is at least 90% over at least MIN_HITS hits. Its note threshold is
the lowest in NOTE_THRESHOLDS with the same precision that still finds at least half the positives;
otherwise the default note threshold stays.
"""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import jev_review
from smell_rules import functions, literal_compares, parse

THRESHOLDS = (0.9, 0.95, 0.98)
NOTE_THRESHOLDS = (0.5, 0.6, 0.7, 0.8)
NOTE_MIN_RECALL = 0.5
PRECISION = 0.9
MIN_HITS = 5
PER_QUESTION = 15
NEGATIVES = 20
IO_CALLS = {"open", "read_text", "write_text", "read_bytes", "write_bytes", "urlopen", "post", "put_object",
            "get_object", "invoke", "to_thread"}


def tracked_python(repo: str, rev: str) -> list[str]:
    out = subprocess.run(["git", "-C", repo, "ls-tree", "-r", "--name-only", rev], capture_output=True, text=True, check=True)
    return [p for p in out.stdout.splitlines() if p.endswith(".py") and not p.startswith("tests/")]


def file_at(repo: str, rev: str, path: str) -> str:
    return subprocess.run(["git", "-C", repo, "show", f"{rev}:{path}"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=True).stdout


def facts(fn: ast.AST) -> dict:
    """The syntax facts the labels are derived from."""
    calls = [ast.unparse(n.func).split(".")[-1] for n in ast.walk(fn) if isinstance(n, ast.Call)]
    module = ast.Module(body=[fn], type_ignores=[])
    repeated = [v for v, lines in literal_compares(module).items() if len(lines) >= 3]
    return {
        "local_import": any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(fn)),
        "constructs": any(c[:1].isupper() for c in calls),
        "io": any(c in IO_CALLS for c in calls),
        "dispatch": bool(repeated),
    }


def labels_for(f, fact: dict) -> dict[str, bool]:
    pure = 8 <= f.lines <= 25 and f.ifs <= 2 and not (fact["io"] or fact["constructs"] or fact["local_import"])
    found = {}
    if f.lines >= 150 and f.ifs >= 15:
        found["srp"] = True
    if fact["dispatch"]:
        found["ocp"] = True
    if fact["local_import"] and fact["constructs"]:
        found["dip"] = True
    if pure and not fact["dispatch"]:
        found.update(srp=False, ocp=False, dip=False)
    return found


def stable(item: dict) -> str:
    return hashlib.sha1(f"{item['file']}:{item['function']}".encode()).hexdigest()


def pick(pool: list[dict]) -> list[dict]:
    """A balanced, reproducible sample: PER_QUESTION positives per question plus NEGATIVES clean helpers."""
    chosen: dict[str, dict] = {}
    for question in ("srp", "ocp", "dip"):
        hits = sorted((i for i in pool if i["labels"].get(question) is True), key=stable)
        chosen.update({stable(i): i for i in hits[:PER_QUESTION]})
    clean = sorted((i for i in pool if i["labels"].get("srp") is False), key=stable)
    chosen.update({stable(i): i for i in clean[:NEGATIVES]})
    return list(chosen.values())


def label(repo: str, rev: str, out: str) -> int:
    pool = []
    for path in tracked_python(repo, rev):
        source = file_at(repo, rev, path)
        try:
            fns = functions(parse(source))
        except SyntaxError:
            continue
        lines = source.splitlines()
        for q, f in fns.items():
            found = labels_for(f, facts(f.node))
            if found:
                pool.append({"file": path, "function": q, "labels": found,
                             "source": "\n".join(lines[f.node.lineno - 1:f.node.end_lineno])})
    chosen = pick(pool)
    Path(out).write_text(json.dumps({"repo": repo, "rev": rev, "items": chosen}, indent=1), encoding="utf-8")
    counts = Counter((q, v) for i in chosen for q, v in i["labels"].items())
    print(f"{len(chosen)} functions labelled from {len(pool)} candidates: " + ", ".join(f"{q}={v}:{n}" for (q, v), n in sorted(counts.items())))
    return 0


def precision_table(rows: list[tuple[float, bool]]) -> dict[str, dict]:
    table = {}
    for t in NOTE_THRESHOLDS + THRESHOLDS:
        hits = [label for p, label in rows if p >= t]
        positives = sum(label for _, label in rows)
        table[str(t)] = {"hits": len(hits), "precision": sum(hits) / len(hits) if hits else None,
                         "recall": sum(hits) / positives if positives else None}
    return table


def precise(row: dict) -> bool:
    return row["hits"] >= MIN_HITS and row["precision"] is not None and row["precision"] >= PRECISION


def block_threshold(table: dict[str, dict]) -> float | None:
    return next((t for t in THRESHOLDS if precise(table[str(t)])), None)


def note_threshold(table: dict[str, dict]) -> float:
    found = (t for t in NOTE_THRESHOLDS if precise(table[str(t)]) and (table[str(t)]["recall"] or 0) >= NOTE_MIN_RECALL)
    return next(found, jev_review.DEFAULT_GATE["note"])


def run(labels_file: str) -> int:
    if not jev_review.enabled():
        print("Set CLEAN_CODE_JEV=1 and TYPESAFE_API_KEY first.", file=sys.stderr)
        return 2
    data = json.loads(Path(labels_file).read_text(encoding="utf-8"))
    cache, rows = jev_review.AnswerCache(), {name: [] for name in jev_review.QUESTIONS}
    answered = 0
    for item in data["items"]:
        answer = cache.ask(item["source"], item["function"]) or {}
        answered += bool(answer)
        for question, truth in item["labels"].items():
            if question in answer:
                rows[question].append((answer[question], truth))
    cache.save()
    if not answered:
        print("Jev answered none of the functions; calibration file left unchanged.", file=sys.stderr)
        return 1
    evidence = {q: precision_table(r) for q, r in rows.items() if r}
    gates = {q: {"note": note_threshold(t), "block": block_threshold(t)} for q, t in evidence.items()}
    # Counts and thresholds only: this file is committed, and the calibrated codebase may be private.
    report = {"model": jev_review.MODEL, "functions": len(data["items"]), "answered": answered,
              "gates": gates, "evidence": evidence}
    jev_review.CALIBRATION.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gates": gates, "evidence": evidence}, indent=2))
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["label"] and len(argv) == 4:
        return label(*argv[1:])
    if argv[:1] == ["run"] and len(argv) == 2:
        return run(argv[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Second layer of the clean-code guard: TypeSafe Jev judges design smells a syntax tree cannot see.

Off unless CLEAN_CODE_JEV=1 and TYPESAFE_API_KEY are both set. When on, it sends the source of each new
or changed function (at most MAX_STATE characters) to api.typesafe.ai and asks four yes/no questions.

A question can block only after calibration (jev_calibrate.py) showed at least 90% precision at its
threshold; jev_calibration.json records that. Until then every answer can only add a note. Network and
API errors never block: the layer just stays quiet.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
MAX_STATE = 12_000
MIN_LINES = 8
MAX_FUNCTIONS = 6   # ponytail: bounds hook latency; the --diff run before handoff sees the rest
TIMEOUT_SECONDS = 15
QUESTIONS_VERSION = 1  # bump when a question's wording changes, so cached answers are not reused
CALIBRATION = Path(__file__).with_name("jev_calibration.json")
CACHE = Path(tempfile.gettempdir()) / "code_smells" / "jev-cache.json"
DEFAULT_GATE = {"note": 0.6, "block": None}


@dataclass(frozen=True)
class Question:
    tag: str
    statement: str
    yes: str
    no: str
    fix: str


QUESTIONS = {
    "srp": Question(
        "Jev/SRP", "This function does more than one job.",
        "It mixes separate responsibilities, such as parsing, validation, I/O and orchestration, that would read better as separate functions.",
        "It does one coherent job, even when that job takes a few small steps.",
        "Split it into functions that each do one job."),
    "naming": Question(
        "Jev/Clean Code", "The function's name does not describe what its body does.",
        "A reader would be surprised by what the body does, given the name.",
        "The name tells a reader what the function does.",
        "Rename it for what it does, or split off the part the name does not cover."),
    "ocp": Question(
        "Jev/OCP", "The function branches on a string or type tag where a dispatch table or polymorphism should be used.",
        "It picks behaviour with if/elif or comparisons on a kind, status, mode or type value that new cases would have to edit.",
        "It has no such branching, or its branches test genuine conditions rather than a tag.",
        "Replace the branches with an Enum and a table of handlers, or one class per variant."),
    "dip": Question(
        "Jev/DIP", "The function constructs or imports concrete dependencies that it should receive instead.",
        "It creates clients, stores, sessions, clocks or file-system access inside its logic, or imports them inside the function.",
        "Its collaborators arrive as parameters or attributes, or it is a pure function.",
        "Pass the client, store or clock in as a parameter or constructor argument."),
}


@dataclass(frozen=True)
class Candidate:
    qualname: str
    line: int
    source: str
    old_source: str | None  # the same function before the change; None when it is new


@dataclass(frozen=True)
class Verdict:
    line: int
    qualname: str
    question: str
    probability: float
    blocks: bool


def enabled() -> bool:
    return os.environ.get("CLEAN_CODE_JEV") == "1" and bool(os.environ.get("TYPESAFE_API_KEY"))


def gates() -> dict[str, dict]:
    try:
        calibrated = json.loads(CALIBRATION.read_text(encoding="utf-8")).get("gates", {})
    except (OSError, ValueError):
        calibrated = {}
    return {name: {**DEFAULT_GATE, **calibrated.get(name, {})} for name in QUESTIONS}


def request_body(source: str, qualname: str) -> dict:
    questions = {name: {"type": "noul", "instructions": q.statement, "criteria": {"true": q.yes, "false": q.no}}
                 for name, q in QUESTIONS.items()}
    state = {"language": "python", "function": qualname, "source": source[:MAX_STATE]}
    return {"model": MODEL, "state": state, "questions": questions}


def post(body: dict) -> dict[str, float] | None:
    request = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            answers = json.loads(response.read()).get("answers", {})
    except (OSError, ValueError) as exc:  # URLError and timeouts are OSError
        print(f"clean-code-guard: Jev unavailable ({type(exc).__name__})", file=sys.stderr)
        return None
    return {name: answers[name]["noul"] for name in QUESTIONS if isinstance(answers.get(name, {}).get("noul"), (int, float))}


class AnswerCache:
    """Answers keyed by function source, so an unchanged function is never sent twice."""

    def __init__(self) -> None:
        try:
            self.entries = json.loads(CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.entries = {}
        self.dirty = False

    @staticmethod
    def key(source: str, qualname: str) -> str:
        return hashlib.sha1(f"v{QUESTIONS_VERSION}:{MODEL}:{qualname}:{source[:MAX_STATE]}".encode()).hexdigest()

    def ask(self, source: str, qualname: str) -> dict[str, float] | None:
        key = self.key(source, qualname)
        if key not in self.entries:
            answer = post(request_body(source, qualname))
            if answer is None:
                return None
            self.entries[key], self.dirty = answer, True
        return self.entries[key]

    def save(self) -> None:
        if self.dirty:
            try:
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                CACHE.write_text(json.dumps(self.entries), encoding="utf-8")
            except OSError:
                pass


def judge(candidate: Candidate, cache: AnswerCache, limits: dict[str, dict]) -> list[Verdict]:
    new = cache.ask(candidate.source, candidate.qualname)
    if not new:
        return []
    old = cache.ask(candidate.old_source, candidate.qualname) if candidate.old_source else {}
    verdicts = []
    for name, p in new.items():
        gate, before = limits[name], (old or {}).get(name, 0.0)
        level = gate["block"] if gate["block"] is not None and p >= gate["block"] else gate["note"]
        if p >= level and before < level:  # ratchet: only a function that crossed the line in this change
            verdicts.append(Verdict(candidate.line, candidate.qualname, name, p, level == gate["block"]))
    return verdicts


def assess(candidates: list[Candidate]) -> list[Verdict]:
    """Jev verdicts for new or changed functions; [] when the layer is off or the API is unreachable."""
    chosen = [c for c in candidates if c.source.count("\n") + 1 >= MIN_LINES][:MAX_FUNCTIONS]
    if not enabled() or not chosen:
        return []
    cache, limits = AnswerCache(), gates()
    with ThreadPoolExecutor(max_workers=4) as pool:
        verdicts = [v for found in pool.map(lambda c: judge(c, cache, limits), chosen) for v in found]
    cache.save()
    return verdicts

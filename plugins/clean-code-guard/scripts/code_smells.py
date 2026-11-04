#!/usr/bin/env python3
"""Clean Code, SOLID and DRY check for Python that an agent just wrote.

It reports only what a change introduced or made worse. Old smells the change left alone stay quiet,
and moved or renamed code is recognised by its shape, so a refactor is judged on what it adds.

  python code_smells.py --hook          PostToolUse hook for Claude Code, Codex and Copilot (hook JSON on stdin)
  python code_smells.py --diff [BASE]   changed .py files in the current repo against BASE (default HEAD);
                                        exits 1 when it finds a problem to fix
  python code_smells.py --self-test     runs test_code_smells.py

A finding is either a problem to fix (the hook blocks until the agent responds) or a note (a small
addition to something already oversized: reported, not blocking). Keep a problem on purpose with
`# smell-ok: <reason>` on the flagged line or the line above it.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import jev_review
from smell_rules import (DETECTORS, LIMIT, Func, Scopes, classes, functions, git_root, is_test_path,
                         line_smells, literal_compares, oversized, parse, parse_functions, repo_index,
                         same_code, shapes, windows)

SUPPRESS = re.compile(r"#\s*smell-ok:\s*\S")
COMMON_NAMES = {"main", "run", "cli", "setup", "teardown"}
FIX = {
    "long": "Split it into named steps and keep this function as the summary.",
    "ifs": "Use early returns, a lookup table, or one function per case.",
    "depth": "Use guard clauses or extract the inner block into a named function.",
    "params": "Group related values into a dataclass, or pass the object they come from.",
    "flag": "A flag means two behaviours: write two functions, or pass a strategy.",
    "terms": "Name the condition: extract a predicate function or named booleans.",
    "nested": "Promote the inner functions so each can be read and tested alone.",
    "class": "Move the new responsibility into its own class and inject it.",
    "file": "Put the new code in a new module named for its job.",
    "literal": "Define an Enum (or named constants) and dispatch through a dict of handlers.",
    "elif": "Use a dict of handlers keyed by the value.",
    "swallow": "Catch the specific exception, or log its type and context before converting it.",
    "local_import": "Import at module top. If that creates a cycle, move the shared code down a layer.",
    "private": "Test through the public API; private names lock today's layout in place.",
    "prose": "Assert on an error code or exception type; message text changes.",
}
GROWTH_FIX = "Put the new logic in its own named function instead of growing this one."
LINE_SMELLS = {
    "swallow": ("Errors", "This `except` catches everything and neither re-raises nor logs."),
    "local_import": ("DIP", "Import inside a function."),
    "terms": ("Clean Code", f"Condition with more than {LIMIT['terms']} and/or terms."),
    "elif": ("OCP", f"if/elif chain of {LIMIT['elif']} or more branches."),
    "private": ("Tests", "Test reaches into a private name."),
    "prose": ("Tests", "`pytest.raises(match=...)` pins English message text."),
}
# attribute, finding kind, principle, noun, growth that counts as "made it worse"
SIZE_CHECKS = (("lines", "long", "Clean Code/SRP", "lines", LIMIT["grow_lines"]),
               ("ifs", "ifs", "Clean Code", "if statements", LIMIT["grow_ifs"]),
               ("depth", "depth", "Clean Code", "levels of nesting", 1),
               ("nested", "nested", "SRP", "inner functions", 1),
               ("params", "params", "Clean Code", "parameters", 1))

Origins = dict[str, list[Func]]  # function name -> functions that left their file in this change


@dataclass(frozen=True)
class Finding:
    line: int
    kind: str
    tag: str
    text: str
    note: bool = False  # advisory: a small addition to something already oversized


@dataclass
class DiffContext:
    """What a multi-file diff knows beyond one file. Hook mode leaves it empty.

    `before_all`/`after_all` count function shapes across every changed file, so code moved between files
    is not reported as new; `exclude` lists files those counts already cover; `origins` lists functions
    that left other files, so a moved function edited in passing is compared with its old self."""
    before_all: Counter | None = None
    after_all: Counter | None = None
    exclude: frozenset[str] = frozenset()
    origins: Origins | None = None


class History:
    """Answers "what was this function before the change?": the same function, a moved or renamed one,
    or a copy of code that exists elsewhere."""

    def __init__(self, rel: str, root: Path | None, ctx: DiffContext, old_fns: dict[str, Func], new_fns: dict[str, Func]):
        self.rel, self.root, self.ctx = rel, root, ctx
        self.old_fns, self.new_fns = old_fns, new_fns
        self.before_all = ctx.before_all if ctx.before_all is not None else Counter(f.shape for f in old_fns.values())
        self.after_all = ctx.after_all if ctx.after_all is not None else Counter(f.shape for f in new_fns.values())
        self.reused: set[str] = set()  # moved, renamed or copied: judged by DRY or growth only
        self.copies: dict[str, list[str]] = {}
        self._index: dict[str, list[list]] | None = None
        self._parsed: dict[str, dict[str, Func]] = {}

    @property
    def index(self) -> dict[str, list[list]]:
        if self._index is None:
            self._index = repo_index(self.root) if self.root is not None else {}
        return self._index

    def previous(self, q: str, f: Func) -> Func | None:
        """The function's earlier self: same name in this file, or moved here and edited in passing."""
        if q in self.old_fns:
            return self.old_fns[q]
        if f.shape in self.before_all:
            return None
        origin = next((g for g in self.origin_candidates(q, f) if same_code(g, f)), None)
        if origin is not None:
            self.reused.add(q)
        return origin

    def origin_candidates(self, q: str, f: Func) -> list[Func]:
        name = q.split(".")[-1]
        found = list((self.ctx.origins or {}).get(name, []))
        found += [g for q2, g in self.old_fns.items() if q2.split(".")[-1] == name and q2 not in self.new_fns]
        if self.ctx.origins is None and self.root is not None and not f.top and not name.startswith("__"):
            files = [r for r, rows in self.index.items() if r != self.rel and any(row[0].split(".")[-1] == name for row in rows)]
            for r in files[:5]:  # ponytail: a common method name stops at 5 files; a move has one source
                found += [g for q2, g in self.parsed(r).items() if q2.split(".")[-1] == name]
        return found

    def parsed(self, rel: str) -> dict[str, Func]:
        if rel not in self._parsed:
            try:
                self._parsed[rel] = parse_functions((self.root / rel).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                self._parsed[rel] = {}
        return self._parsed[rel]

    def is_reuse(self, q: str, f: Func) -> bool:
        """Moved, renamed or copied code. Copies are collected per source for one DRY report each."""
        if f.shape in self.before_all and self.after_all[f.shape] <= self.before_all[f.shape]:
            self.reused.add(q)
            return True
        where = [f"{r}:{row[2]}" for r, rows in self.index.items() if r != self.rel and r not in self.ctx.exclude
                 for row in rows if row[1] == f.shape]
        if self.after_all[f.shape] > max(1, self.before_all[f.shape]):
            where += [f"`{q2}` in this file" for q2, g in self.new_fns.items() if q2 != q and g.shape == f.shape]
        if not where:
            return False
        self.reused.add(q)
        if f.substantial:
            self.copies.setdefault(where[0].split(":")[0], []).append(q)
        return True

    def name_clashes(self, q: str) -> list[str]:
        return [f"{r}:{row[2]}" for r, rows in self.index.items() if r != self.rel for row in rows if row[3] and row[0] == q][:3]


class Review:
    """Smells in `after` that `before` did not have. `before=None` means a new file."""

    def __init__(self, before: str | None, after: str, rel: str, root: Path | None, ctx: DiffContext):
        self.rel = rel
        self.new_tree = parse(after)
        try:
            self.old_tree = parse(before) if before is not None else None
        except SyntaxError:
            self.old_tree = None
        self.is_new_file = before is None
        self.old_text, self.new_text = (before or "").splitlines(), after.splitlines()
        self.old_line_set = set(self.old_text)
        self.is_test = is_test_path(rel)
        self.old_fns = functions(self.old_tree) if self.old_tree else {}
        self.new_fns = functions(self.new_tree)
        self.history = History(rel, root, ctx, self.old_fns, self.new_fns)
        self.out: list[Finding] = []
        self.jev_candidates: list[jev_review.Candidate] = []

    def run(self) -> list[Finding]:
        for step in (self.review_functions, self.report_copies, self.review_classes, self.review_file,
                     self.review_literals, self.review_line_smells, self.review_windows, self.review_with_jev):
            step()
        kept = [f for f in self.out if not suppressed(self.new_text, f.line)]
        return sorted(set(kept), key=lambda f: (f.line, f.kind))

    def add(self, line: int, kind: str, tag: str, text: str, note: bool = False, fix: str | None = None) -> None:  # smell-ok: severity is data, not a second behaviour
        self.out.append(Finding(line, kind, tag, f"{text} {fix or FIX.get(kind, '')}".strip(), note))

    def newest(self, lines: list[int]) -> int:
        """Prefer a line whose text is new, so the report points at the change."""
        return next((ln for ln in lines if self.new_text[ln - 1] not in self.old_line_set), lines[-1])

    def in_reused(self, line: int) -> bool:
        return any(f.node.lineno <= line <= f.node.end_lineno for q, f in self.new_fns.items() if q in self.history.reused)

    # -- functions --
    def review_functions(self) -> None:
        for q, f in self.new_fns.items():
            old = self.history.previous(q, f)
            if old is None and self.history.is_reuse(q, f):
                continue
            if old is None:
                self.review_new_name(q, f)
            self.review_size(q, f, old)
            self.review_flags(q, f, old)
            if q not in self.history.reused and (old is None or old.shape != f.shape):
                old_source = self.source_of(self.old_text, old) if q in self.old_fns else None
                self.jev_candidates.append(jev_review.Candidate(q, f.node.lineno, self.source_of(self.new_text, f), old_source))

    def review_new_name(self, q: str, f: Func) -> None:
        if not f.top or self.is_test or q in COMMON_NAMES or q.startswith("__"):
            return
        clash = self.history.name_clashes(q)
        if clash:
            self.add(f.node.lineno, "dup", "DRY", f"A function named `{q}` already exists in {', '.join(clash)}. "
                     "Reuse it, or name yours for what makes it different.")

    def review_size(self, q: str, f: Func, old: Func | None) -> None:
        # Tests take fixtures as parameters and define fakes inline; their length still counts.
        relaxed = {"params", "nested"} if self.is_test else set()
        for attr, kind, tag, noun, grow in SIZE_CHECKS:
            value, limit = getattr(f, attr), LIMIT[attr]
            if value <= limit or attr in relaxed:
                continue
            if old is None:
                self.add(f.node.lineno, kind, tag, f"`{q}` has {value} {noun} (limit {limit}).")
            elif value - getattr(old, attr) >= grow:
                fix = GROWTH_FIX if kind in ("long", "ifs") else None
                self.add(f.node.lineno, kind, tag, f"`{q}` grew from {getattr(old, attr)} to {value} {noun} (limit {limit}).", fix=fix)

    def review_flags(self, q: str, f: Func, old: Func | None) -> None:
        if self.is_test:
            return  # fixture builders take flags by convention
        for flag in f.flags:
            if old is None or flag not in old.flags:
                self.add(f.node.lineno, "flag", "Clean Code/SRP", f"`{q}` takes the boolean flag `{flag}`.")

    def report_copies(self) -> None:
        for source, names in self.history.copies.items():
            first = min(self.new_fns[n].node.lineno for n in names)
            listed = ", ".join(f"`{n}`" for n in names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "")
            verb = "has" if len(names) == 1 else "have"
            self.add(first, "dup", "DRY", f"{listed} {verb} the same code as {source}. "
                     "Reuse the existing code; if this is a move, delete the old copy.")

    # -- containers --
    def review_classes(self) -> None:
        old_classes = classes(self.old_tree) if self.old_tree else {}
        for q, cls in classes(self.new_tree).items():
            prev = old_classes.get(q)
            mostly_moved = sum(m in self.history.reused for m in cls[2]) * 2 >= len(cls[2])
            if not oversized(cls) or q.split(".")[-1].startswith("Test") or mostly_moved:
                continue
            added = len(cls[2]) - (len(prev[2]) if prev else 0)
            grew = cls[1] - (prev[1] if prev else 0)
            if prev is not None and added <= 0 and grew < LIMIT["grow_class"]:
                continue
            small = prev is not None and oversized(prev) and added < LIMIT["small_methods"] and grew < LIMIT["small_growth"]
            self.add(cls[0], "class", "SRP", f"class `{q}` is {cls[1]} lines with {len(cls[2])} methods "
                     f"(limits {LIMIT['class_lines']} / {LIMIT['class_methods']}), and this change added to it.", note=small)

    def review_file(self) -> None:
        size, grew = len(self.new_text), len(self.new_text) - len(self.old_text)
        moved_lines = sum(self.new_fns[q].lines for q in self.history.reused)
        if size <= LIMIT["file_lines"] or moved_lines * 2 >= max(grew, 1):
            return
        if not self.is_new_file and grew < LIMIT["grow_file"]:
            return
        small = not self.is_new_file and len(self.old_text) > LIMIT["file_lines"] and grew < LIMIT["small_growth"]
        growth = "." if self.is_new_file else f" and grew by {grew}."
        self.add(1, "file", "SRP", f"This file is {size} lines (limit {LIMIT['file_lines']}){growth}", note=small)

    # -- lines --
    def review_literals(self) -> None:
        if self.is_test:
            return  # tests compare against expected strings by design
        old_lits = literal_compares(self.old_tree) if self.old_tree else {}
        for value, lines in literal_compares(self.new_tree).items():
            own = [ln for ln in lines if not self.in_reused(ln)]
            added = len(lines) - len(old_lits.get(value, []))
            if len(lines) >= LIMIT["literal"] and own and added > len(lines) - len(own):
                self.add(self.newest(own), "literal", "OCP", f'"{value}" is now compared as a string {len(lines)} times in this file.')

    def review_line_smells(self) -> None:
        old_scopes, new_scopes = Scopes(self.old_fns), Scopes(self.new_fns)
        old = line_smells(self.old_tree, self.is_test) if self.old_tree else {k: [] for k in DETECTORS}
        for kind, lines in line_smells(self.new_tree, self.is_test).items():
            before = Counter(old_scopes.of(ln) for ln in old[kind])
            by_scope: dict[str, list[int]] = {}
            for ln in lines:
                by_scope.setdefault(new_scopes.of(ln), []).append(ln)
            for scope, scope_lines in by_scope.items():
                if scope not in self.history.reused and len(scope_lines) > before[scope]:
                    tag, text = LINE_SMELLS[kind]
                    self.add(self.newest(scope_lines), kind, tag, text)

    @staticmethod
    def source_of(text: list[str], f: Func) -> str:
        return "\n".join(text[f.node.lineno - 1:f.node.end_lineno])

    def review_with_jev(self) -> None:
        """Layer 2: design questions for new or changed functions (off unless CLEAN_CODE_JEV=1)."""
        for v in jev_review.assess(self.jev_candidates):
            q = jev_review.QUESTIONS[v.question]
            self.add(v.line, f"jev_{v.question}", q.tag, f"Jev rates `{v.qualname}` {v.probability:.2f} on: {q.statement}",
                     note=not v.blocks, fix=q.fix)

    def review_windows(self) -> None:
        old = windows(self.old_tree) if self.old_tree else {}
        reported: list[tuple[int, int]] = []
        for key, spans in sorted(windows(self.new_tree).items(), key=lambda kv: kv[1][0]):
            last = spans[-1]
            overlaps = any(a <= last[0] <= b for a, b in reported)
            if len(spans) <= len(old.get(key, [])) or self.in_reused(last[0]) or overlaps:
                continue
            reported.append(last)
            self.add(last[0], "dup", "DRY", f"These {LIMIT['window']}+ statements also appear at line {spans[0][0]}. "
                     "Extract one helper and call it from both places.")


def check(before: str | None, after: str, rel: str, root: Path | None, ctx: DiffContext | None = None) -> list[Finding]:
    try:
        return Review(before, after, rel, root, ctx or DiffContext()).run()
    except SyntaxError:
        return []  # a file mid-edit; the next edit is checked again


def suppressed(lines: list[str], line: int) -> bool:
    return any(0 < ln <= len(lines) and SUPPRESS.search(lines[ln - 1]) for ln in (line, line - 1))


def render(rel: str, findings: list[Finding]) -> str:
    fixes, notes = [f for f in findings if not f.note], [f for f in findings if f.note]
    lines = []
    if fixes:
        lines += [f"Clean Code / SOLID / DRY check on {rel}: {len(fixes)} problem(s) this change introduced.",
                  "Fix each one now, or keep it on purpose with `# smell-ok: <reason>` on its line and name it in your "
                  "handoff. Leave code this change did not touch alone; list it as a follow-up instead."]
        lines += [f"- L{f.line} [{f.tag}] {f.text}" for f in fixes[:LIMIT["report"]]]
        if len(fixes) > LIMIT["report"]:
            lines.append(f"- ...and {len(fixes) - LIMIT['report']} more.")
    if notes:
        lines.append(f"Notes on {rel} (no action needed for a small fix; mention them in your handoff):")
        lines += [f"- L{f.line} [{f.tag}] {f.text}" for f in notes]
    return "\n".join(lines)


# ---- entry points ------------------------------------------------------------------------------

def reverse(after: str, edits: list[tuple[str, str, bool]]) -> str | None:
    """Rebuild the file as it was before an Edit/MultiEdit by undoing the edits in reverse order."""
    text = after
    for old, new, replace_all in reversed(edits):
        if not new or new not in text:
            return None
        text = text.replace(new, old) if replace_all else text.replace(new, old, 1)
    return text


def git(root: Path, *args: str) -> str | None:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return done.stdout if done.returncode == 0 else None


def git_files(root: Path, rev: str, paths: list[str]) -> dict[str, str | None]:
    """`git show rev:path` for many paths in one process (each git call costs ~0.8 s on Windows)."""
    if not paths:
        return {}
    request = "".join(f"{rev}:{p}\n" for p in paths).encode()
    data = subprocess.run(["git", "-C", str(root), "cat-file", "--batch"], input=request, capture_output=True).stdout
    out, pos = {}, 0
    for p in paths:
        end = data.index(b"\n", pos)
        header, pos = data[pos:end].split(), end + 1
        if len(header) < 3:  # "<rev:path> missing"
            out[p] = None
            continue
        size = int(header[2])
        out[p], pos = data[pos:pos + size].decode("utf-8", "replace"), pos + size + 1
    return out


def before_edit(tool: str, given: dict, result: dict, after: str, root: Path, rel: str) -> str | None:
    """The file as it was before this tool call, or None for a new file."""
    if result.get("originalFile") is not None:
        return result["originalFile"]
    edits = {"Edit": [given], "MultiEdit": given.get("edits", [])}.get(tool)
    if edits is not None:
        undone = reverse(after, [(e.get("old_string", ""), e.get("new_string", ""), bool(e.get("replace_all"))) for e in edits])
        if undone is not None:
            return undone
    if tool == "Write" and result.get("type") == "create":
        return None
    return git(root, "show", f"HEAD:{rel}")


PATH_KEYS = {"file_path", "filePath", "path", "filePaths", "files"}
PATCH_FILE = re.compile(r"^\*\*\* (?:Add File|Update File|Move to): (.+)$", re.M)


def edited_paths(args: object) -> list[str]:
    """Paths named anywhere in a tool's input: path-like keys (Copilot) or apply_patch headers (Codex)."""
    found: list[str] = []
    stack = [args]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if key in PATH_KEYS and isinstance(value, str):
                    found.append(value)
                elif key in PATH_KEYS and isinstance(value, list):
                    found += [v for v in value if isinstance(v, str)]
                else:
                    stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, str):
            found += PATCH_FILE.findall(node)
    return sorted(set(found))


def hook_payload(data: dict) -> tuple[str, dict, dict, list[Path]]:
    """Tool name, input, response and edited files, from a Claude, Codex or Copilot PostToolUse payload."""
    tool = data.get("tool_name") or data.get("toolName") or ""
    given = data.get("tool_input", data.get("toolArgs")) or {}
    if isinstance(given, str):  # some Copilot builds send toolArgs as a JSON string
        try:
            given = json.loads(given)
        except json.JSONDecodeError:
            given = {"input": given}
    result = data.get("tool_response") if isinstance(data.get("tool_response"), dict) else {}
    named = given.get("file_path") or result.get("filePath") if isinstance(given, dict) else None
    cwd = Path(data.get("cwd") or ".")
    return tool, given, result, [cwd / p for p in ([named] if named else edited_paths(given))]


def hook() -> int:
    tool, given, result, paths = hook_payload(json.load(sys.stdin))
    messages, blocking = [], False
    for path in paths:
        root = git_root(path.resolve().parent) if path.suffix == ".py" and path.is_file() else None
        if root is None:
            continue  # not Python, gone, or a scratch file outside a repository
        rel = path.resolve().relative_to(root).as_posix()
        after = path.read_text(encoding="utf-8", errors="replace")
        before = before_edit(tool if len(paths) == 1 else "", given, result, after, root, rel)
        findings = check(before, after, rel, root)
        if findings:
            messages.append(render(rel, findings))
            blocking = blocking or any(not f.note for f in findings)
    if messages:
        print(json.dumps(hook_output("\n\n".join(messages), blocking)))
    return 0


def hook_output(message: str, blocking: bool) -> dict:
    """Claude and Codex read `decision`/`reason` or `hookSpecificOutput`; Copilot reads top-level `additionalContext`."""
    if blocking:
        return {"decision": "block", "reason": message, "additionalContext": message}
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message},
            "additionalContext": message}


def changed_files(root: Path, base: str) -> tuple[list[str], list[str]]:
    """Python files changed against `base` (including untracked ones) and files that left."""
    changed, gone = [], []
    for row in (git(root, "diff", "--name-status", "-M", base, "--", "*.py") or "").splitlines():
        parts = row.split("\t")
        if parts[0].startswith(("R", "D")):
            gone.append(parts[1])
        if not parts[0].startswith("D") and len(parts) > 1:
            changed.append(parts[-1])
    changed += (git(root, "ls-files", "--others", "--exclude-standard", "--", "*.py") or "").splitlines()
    return changed, gone


def diff_context(befores: dict[str, str | None], afters: dict[str, str], changed: list[str]) -> DiffContext:
    origins: Origins = {}
    for rel, src in befores.items():
        remaining = parse_functions(afters.get(rel))
        for q, f in parse_functions(src).items():
            if q not in remaining:
                origins.setdefault(q.split(".")[-1], []).append(f)
    return DiffContext(before_all=sum(map(shapes, befores.values()), Counter()),
                       after_all=sum(map(shapes, afters.values()), Counter()),
                       exclude=frozenset(changed), origins=origins)


def diff(base: str) -> int:
    root = git_root(Path.cwd().resolve())
    if root is None:
        print("Not inside a git repository.", file=sys.stderr)
        return 2
    changed, gone = changed_files(root, base)
    befores = git_files(root, base, changed + gone)
    afters = {rel: (root / rel).read_text(encoding="utf-8", errors="replace") for rel in changed if (root / rel).is_file()}
    ctx = diff_context(befores, afters, changed)
    problems = 0
    for rel, after in afters.items():
        findings = check(befores.get(rel), after, rel, root, ctx)
        problems += sum(not f.note for f in findings)
        if findings:
            print(render(rel, findings), end="\n\n")
    print(f"{problems} problem(s) to fix in {len(afters)} changed Python file(s) against {base}.")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--hook"]:
        try:
            return hook()
        except Exception as exc:  # smell-ok: a broken checker must never block an edit
            print(f"code_smells hook skipped: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 0
    if argv[:1] == ["--diff"]:
        return diff(argv[1] if len(argv) > 1 else "HEAD")
    if argv[:1] == ["--self-test"]:
        from test_code_smells import run_all  # smell-ok: tests load only when asked for
        return run_all()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

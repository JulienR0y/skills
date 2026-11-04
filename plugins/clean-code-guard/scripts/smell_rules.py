"""Measurements and detectors behind code_smells.py: pure functions over Python syntax trees."""
from __future__ import annotations

import ast
import bisect
import difflib
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

LIMIT = {
    "lines": 50, "ifs": 10, "depth": 4, "params": 6, "nested": 2, "terms": 5,
    "class_lines": 400, "class_methods": 20, "file_lines": 800,
    "literal": 3, "elif": 5, "grow_lines": 10, "grow_ifs": 3, "grow_class": 40, "grow_file": 20,
    "small_growth": 100, "small_methods": 3, "window": 4, "window_lines": 6, "big_statement": 30, "report": 15,
}
LOG_CALLS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log", "print", "emit"}
SKIP_DIRS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", "build", "dist", ".tox",
             ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages", ".worktrees", ".scratch"}
FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
BLOCK = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match,
         *((ast.TryStar,) if hasattr(ast, "TryStar") else ()))
INDEX_VERSION = 3  # bump when the cached row format or the shape digest changes


@dataclass
class Func:
    node: ast.AST
    top: bool
    lines: int
    ifs: int
    depth: int
    params: int
    nested: int
    flags: tuple[str, ...]
    shape: str          # arguments + body, without the name: finds moves, renames and copies
    substantial: bool   # worth a DRY report when copied


# ---- parsing and measurement -------------------------------------------------------------------

_TREES: dict[str, ast.Module] = {}  # source digest -> tree; keeps trees alive so their ids stay unique
_FUNCS: dict[int, dict[str, Func]] = {}


def parse(source: str) -> ast.Module:
    """ast.parse with a per-process cache: one diff reads the same file several times."""
    key = hashlib.sha1(source.encode("utf-8", "replace")).hexdigest()
    if key not in _TREES:
        _TREES[key] = ast.parse(source)
    return _TREES[key]


def digest(*nodes: ast.AST) -> str:
    return hashlib.sha1("|".join(ast.dump(n, annotate_fields=False) for n in nodes).encode()).hexdigest()


def is_elif_parent(node: ast.AST) -> bool:
    return isinstance(node, ast.If) and len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If)


def depth(node: ast.AST, d: int) -> int:
    """Block nesting below `node`; an elif stays on its if's level."""
    if isinstance(node, (*FUNC, ast.ClassDef, ast.Lambda)):
        return d
    if isinstance(node, BLOCK):
        d += 1
    best = d
    if is_elif_parent(node):
        best = max(best, depth(node.orelse[0], d - 1))
        children = list(node.body)
    else:
        children = list(ast.iter_child_nodes(node))
    for child in children:
        best = max(best, depth(child, d))
    return best


def without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    first = body[0] if body else None
    is_doc = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)
    return body[1:] if is_doc else body


def boolean_flags(a: ast.arguments) -> tuple[str, ...]:
    positional = a.posonlyargs + a.args
    defaults = dict(zip([x.arg for x in positional][len(positional) - len(a.defaults):], a.defaults))
    defaults.update({x.arg: d for x, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None})
    return tuple(k for k, d in defaults.items() if isinstance(d, ast.Constant) and isinstance(d.value, bool))


def parameter_count(a: ast.arguments) -> int:
    positional = a.posonlyargs + a.args
    bound = 1 if positional and positional[0].arg in ("self", "cls") else 0
    return len(positional) + len(a.kwonlyargs) - bound


def measure(fn: ast.AST, top: bool) -> Func:
    body = without_docstring(fn.body)
    kinds = Counter(type(x) for x in ast.walk(fn))
    return Func(
        node=fn, top=top, lines=fn.end_lineno - fn.lineno + 1, ifs=kinds[ast.If],
        depth=max((depth(c, 0) for c in fn.body), default=0), params=parameter_count(fn.args),
        nested=kinds[ast.FunctionDef] + kinds[ast.AsyncFunctionDef] - 1, flags=boolean_flags(fn.args),
        shape=digest(fn.args, ast.Module(body=body, type_ignores=[])),
        substantial=len(body) > 1 or any(isinstance(x, ast.Call) for s in body for x in ast.walk(s)),
    )


def functions(tree: ast.Module) -> dict[str, Func]:
    """Module functions and methods by qualified name; inner functions count as part of their parent.
    Call it only on trees from `parse` (or drop the cache entry), so a reused id never hits."""
    if id(tree) in _FUNCS:
        return _FUNCS[id(tree)]
    out: dict[str, Func] = _FUNCS.setdefault(id(tree), {})

    def visit(body: list[ast.stmt], prefix: str, top: bool) -> None:
        for n in body:
            if isinstance(n, ast.ClassDef):
                visit(n.body, f"{prefix}{n.name}.", False)
            elif isinstance(n, FUNC):
                out[prefix + n.name] = measure(n, top)

    visit(tree.body, "", True)
    return out


def parse_functions(source: str | None) -> dict[str, Func]:
    try:
        return functions(parse(source)) if source is not None else {}
    except SyntaxError:
        return {}


def shapes(source: str | None) -> Counter:
    return Counter(f.shape for f in parse_functions(source).values())


def classes(tree: ast.Module) -> dict[str, tuple[int, int, list[str]]]:
    """Class qualname -> (line, size in lines, method qualnames)."""
    out: dict[str, tuple[int, int, list[str]]] = {}

    def visit(body: list[ast.stmt], prefix: str) -> None:
        for n in body:
            if isinstance(n, ast.ClassDef):
                q = prefix + n.name
                out[q] = (n.lineno, n.end_lineno - n.lineno + 1, [f"{q}.{m.name}" for m in n.body if isinstance(m, FUNC)])
                visit(n.body, f"{q}.")

    visit(tree.body, "")
    return out


def oversized(cls: tuple[int, int, list[str]]) -> bool:
    return cls[1] > LIMIT["class_lines"] or len(cls[2]) > LIMIT["class_methods"]


def same_code(a: Func, b: Func) -> bool:
    """A move often edits a line or two (a class or module name); 90% of the lines must still match."""
    lines = [ast.unparse(ast.Module(body=f.node.body, type_ignores=[])).splitlines() for f in (a, b)]
    m = difflib.SequenceMatcher(None, *lines, autojunk=False)
    return m.real_quick_ratio() >= 0.9 and m.quick_ratio() >= 0.9 and m.ratio() >= 0.9


class Scopes:
    """Maps a line to the function that contains it, so line smells are counted per function."""

    def __init__(self, fns: dict[str, Func]):
        self.spans = sorted((f.node.lineno, f.node.end_lineno, q) for q, f in fns.items())
        self.starts = [s for s, _, _ in self.spans]

    def of(self, line: int) -> str:
        i = bisect.bisect_right(self.starts, line) - 1
        if i >= 0 and self.spans[i][0] <= line <= self.spans[i][1]:
            return self.spans[i][2]
        return "<module>"


# ---- line-level detectors ----------------------------------------------------------------------

@dataclass
class TreeContext:
    parents: dict[int, ast.AST]
    elifs: set[int]
    is_test: bool

    def ancestors(self, node: ast.AST):
        p = self.parents.get(id(node))
        while p is not None:
            yield p
            p = self.parents.get(id(p))


def is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(ast.unparse(t).split(".")[-1] in ("Exception", "BaseException") for t in types)


def is_log_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    name = ast.unparse(node.func).split(".")[-1].lower()
    return name in LOG_CALLS or "log" in name


def swallows(handler: ast.ExceptHandler) -> bool:
    body = ast.walk(ast.Module(body=handler.body, type_ignores=[]))
    return not any(isinstance(x, ast.Raise) or is_log_call(x) for x in body)


def catches_import_error(node: ast.AST) -> bool:
    if not isinstance(node, ast.Try):
        return False
    return any(h.type is not None and re.search(r"ImportError|ModuleNotFoundError", ast.unparse(h.type)) for h in node.handlers)


def optional_import(node: ast.AST, ctx: TreeContext) -> bool:
    """Imports that are optional by design: under `except ImportError` or `if TYPE_CHECKING`."""
    for p in ctx.ancestors(node):
        if catches_import_error(p) or (isinstance(p, ast.If) and "TYPE_CHECKING" in ast.unparse(p.test)):
            return True
    return False


def chain_length(node: ast.If) -> int:
    n = 1
    while is_elif_parent(node):
        node, n = node.orelse[0], n + 1
    return n


def leaf_terms(node: ast.AST) -> int:
    """Operands of an and/or condition, counted through nested and/or and `not`."""
    if isinstance(node, ast.BoolOp):
        return sum(leaf_terms(v) for v in node.values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return leaf_terms(node.operand)
    return 1


def is_outer_condition(n: ast.AST, ctx: TreeContext) -> bool:
    if not isinstance(n, ast.BoolOp):
        return False
    parent = ctx.parents.get(id(n))
    inside_not = isinstance(parent, ast.UnaryOp) and isinstance(ctx.parents.get(id(parent)), ast.BoolOp)
    return not isinstance(parent, ast.BoolOp) and not inside_not


def detect_swallow(n: ast.AST, ctx: TreeContext) -> bool:
    return isinstance(n, ast.ExceptHandler) and is_broad(n) and swallows(n)


def detect_local_import(n: ast.AST, ctx: TreeContext) -> bool:
    if ctx.is_test or not isinstance(n, (ast.Import, ast.ImportFrom)):
        return False  # tests import inside functions by convention
    return any(isinstance(p, FUNC) for p in ctx.ancestors(n)) and not optional_import(n, ctx)


def detect_terms(n: ast.AST, ctx: TreeContext) -> bool:
    return is_outer_condition(n, ctx) and leaf_terms(n) > LIMIT["terms"]


def detect_elif(n: ast.AST, ctx: TreeContext) -> bool:
    return isinstance(n, ast.If) and id(n) not in ctx.elifs and chain_length(n) >= LIMIT["elif"]


def detect_private(n: ast.AST, ctx: TreeContext) -> bool:
    if not (ctx.is_test and isinstance(n, ast.Attribute)):
        return False
    on_self = isinstance(n.value, ast.Name) and n.value.id in ("self", "cls")
    return n.attr.startswith("_") and not n.attr.startswith("__") and not on_self


def detect_prose(n: ast.AST, ctx: TreeContext) -> bool:
    if not (ctx.is_test and isinstance(n, ast.Call) and ast.unparse(n.func).endswith("raises")):
        return False
    return any(k.arg == "match" and isinstance(k.value, ast.Constant) and " " in str(k.value.value) for k in n.keywords)


DETECTORS = {"swallow": detect_swallow, "local_import": detect_local_import, "terms": detect_terms,
             "elif": detect_elif, "private": detect_private, "prose": detect_prose}


def line_smells(tree: ast.Module, is_test: bool) -> dict[str, list[int]]:
    ctx = TreeContext(parents={id(c): n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)},
                      elifs={id(n.orelse[0]) for n in ast.walk(tree) if is_elif_parent(n)}, is_test=is_test)
    found: dict[str, list[int]] = {k: [] for k in DETECTORS}
    for n in ast.walk(tree):
        kind = next((k for k, detect in DETECTORS.items() if detect(n, ctx)), None)
        if kind:
            found[kind].append(n.lineno)
    return found


def dispatch_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 1 \
        and not node.value.startswith("__")


def compared_sides(n: ast.Compare) -> list[ast.AST]:
    sides: list[ast.AST] = []
    for op, right in zip(n.ops, n.comparators):
        if isinstance(op, (ast.Eq, ast.NotEq)):
            sides += [n.left, right]
        elif isinstance(op, (ast.In, ast.NotIn)) and isinstance(right, (ast.Tuple, ast.Set, ast.List)):
            sides += right.elts
    return sides


def literal_compares(tree: ast.Module) -> dict[str, list[int]]:
    """String literals used as dispatch values (`x == "a"`, `x in ("a", "b")`), outside asserts."""
    asserted = {id(n.test) for n in ast.walk(tree) if isinstance(n, ast.Assert)}
    out: dict[str, list[int]] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare) and id(n) not in asserted:
            for s in filter(dispatch_literal, compared_sides(n)):
                out.setdefault(s.value, []).append(n.lineno)
    return out


def statement_runs(stmts: list[ast.stmt]):
    """Windows of consecutive statements worth comparing. Big compound statements are compared
    through their own inner runs only."""
    size = LIMIT["window"]
    for i in range(len(stmts) - size + 1):
        run = stmts[i:i + size]
        long_enough = run[-1].end_lineno - run[0].lineno + 1 >= LIMIT["window_lines"]
        if long_enough and all(s.end_lineno - s.lineno <= LIMIT["big_statement"] for s in run):
            yield run


def statement_lists(tree: ast.Module):
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef)):
            continue  # top-level definitions are compared as functions, not as statement runs
        for attr in ("body", "orelse", "finalbody"):
            stmts = getattr(n, attr, None)
            if isinstance(stmts, list) and len(stmts) >= LIMIT["window"] and isinstance(stmts[0], ast.stmt):
                yield stmts


def windows(tree: ast.Module) -> dict[str, list[tuple[int, int]]]:
    """Runs of statements that appear more than once in the file."""
    memo: dict[int, str] = {}
    seen: dict[str, list[tuple[int, int]]] = {}
    for stmts in statement_lists(tree):
        for run in statement_runs(stmts):
            key = hashlib.sha1("".join(memo.setdefault(id(s), digest(s)) for s in run).encode()).hexdigest()
            seen.setdefault(key, []).append((run[0].lineno, run[-1].end_lineno))
    return {k: v for k, v in seen.items() if len(v) > 1}


def is_test_path(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    return "tests" in parts or "test" in parts or parts[-1].startswith("test_") or parts[-1] == "conftest.py"


# ---- repository index for DRY across files -----------------------------------------------------

def git_root(path: Path) -> Path | None:
    return next((p for p in [path, *path.parents] if (p / ".git").exists()), None)


def python_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                full = os.path.join(dirpath, name)
                yield full, os.path.relpath(full, root).replace(os.sep, "/")


def index_row(full: str) -> list[list]:
    try:
        tree = ast.parse(Path(full).read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError):
        return []
    rows = [[q, f.shape, f.node.lineno, f.top, f.substantial] for q, f in functions(tree).items()]
    _FUNCS.pop(id(tree), None)  # this tree is not kept, so its id must not stay cached
    return rows


def repo_index(root: Path) -> dict[str, list[list]]:
    """Every function in the repo as [qualname, shape, line, top, substantial], cached by file mtime."""
    key = hashlib.sha1(f"v{INDEX_VERSION}:{root}".encode()).hexdigest()[:16]
    cache_file = Path(tempfile.gettempdir()) / "code_smells" / f"{key}.json"
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    fresh = {}
    for full, rel in python_files(root):
        st = os.stat(full)
        sig = [st.st_mtime_ns, st.st_size]
        fresh[rel] = cache[rel] if rel in cache and cache[rel][0] == sig else [sig, index_row(full)]
    if fresh != cache:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(fresh), encoding="utf-8")
        except OSError:
            pass
    return {rel: entry[1] for rel, entry in fresh.items()}

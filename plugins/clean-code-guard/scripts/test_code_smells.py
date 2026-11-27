"""Checks for code_smells.py. Run: python test_code_smells.py (or code_smells.py --self-test)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import jev_review
from pathlib import Path

from code_smells import check, hook_output, hook_payload, reverse

BASE = "def small(a):\n    return a + 1\n"
SCRIPT = Path(__file__).with_name("code_smells.py")
# How each agent names an edit call's fields: tool-name field, arguments field, then the path, old and new text.
EDIT_ARGS = {"Edit": ("tool_name", "tool_input", "file_path", "old_string", "new_string"),
             "edit": ("toolName", "toolArgs", "path", "old_str", "new_str"),
             "replace_string_in_file": ("toolName", "toolArgs", "filePath", "oldString", "newString")}


def edit_payload(tool: str, path: Path, old: str, new: str) -> dict:
    name, args, path_key, old_key, new_key = EDIT_ARGS[tool]
    return {name: tool, "cwd": str(path.parent), args: {path_key: str(path), old_key: old, new_key: new}}


def run_script(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def kinds(before: str | None, after: str, rel: str = "pkg/mod.py") -> set[str]:
    return {f.kind for f in check(before, after, rel, None)}


def big_function() -> str:
    big = ["def big(a, b, c, d, e, f, g, debug=False):", "    import json"]
    big += [f"    if a == {i}:\n        b += {i}" for i in range(11)]
    big += ["    if a:", "        if b:", "            if c:", "                if d:", "                    if e:", "                        g = 1"]
    big += ["    ok = a and b and c and d and e and f"]
    big += ["    def h1():\n        return 1", "    def h2():\n        return 2", "    def h3():\n        return 3"]
    big += ["    try:\n        g = json.dumps(a)\n    except Exception:\n        pass"]
    big += [f"    v{i} = {i}" for i in range(20)] + ["    return ok"]
    return "\n".join(big) + "\n"


def test_new_function_smells() -> None:
    assert check(BASE, BASE, "pkg/mod.py", None) == []
    found = kinds(BASE, BASE + "\n\n" + big_function())
    assert {"long", "ifs", "depth", "params", "flag", "terms", "nested", "swallow", "local_import"} <= found, found
    assert "long" not in kinds(BASE, BASE + "\n\n" + big_function().replace("debug=False):", "debug=False):  # smell-ok: table"))
    five = "def f(a, b, c, d, e):\n    return a and b and c and not (d and e)\n"
    assert "terms" not in kinds(BASE, BASE + five)  # five operands is the limit, `not` included


def test_moves_and_small_growth_stay_quiet() -> None:
    src = BASE + "\n\n" + big_function()
    assert kinds(src, src.replace("def big(", "def renamed(")) == set()
    eighty = "def legacy(a):\n" + "".join(f"    a += {i}\n" for i in range(80)) + "    return a\n"
    assert "long" not in kinds(eighty, eighty.replace("    return a\n", "    a += 1\n    a += 2\n    return a\n"))
    assert "long" in kinds(eighty, eighty.replace("    return a\n", "".join(f"    a -= {i}\n" for i in range(12)) + "    return a\n"))
    swallow = "def f(a):\n    try:\n        a()\n    except Exception:\n        pass\n"
    assert "swallow" not in kinds(swallow, swallow.replace("pass", "a = None"))


def test_dispatch_smells() -> None:
    route = ('def route(kind):\n    if kind == "pdf":\n        return 1\n'
             '    if kind == "pdf" or kind == "csv":\n        return 2\n    return kind != "pdf"\n')
    assert "literal" in kinds(BASE, BASE + route)
    asserts = 'def test_r(kind):\n    assert kind == "pdf"\n    assert kind != "pdf"\n    assert kind == "pdf"\n'
    assert "literal" not in kinds("", asserts, "tests/test_r.py")
    pick = "def pick(x):\n" + "".join(f"    {'if' if i == 1 else 'elif'} x == {i}:\n        return {i}\n" for i in range(1, 6)) + "    return 0\n"
    assert "elif" in kinds(BASE, BASE + pick)


def test_duplication() -> None:
    # `values`, not a one-letter name: "p:" followed by a newline escape looks like a Windows drive path to
    # repositories that scan their files for absolute paths.
    block = ('    total = 0\n    for item in values:\n        total += item\n    scaled = total * 2\n'
             '    result = {\n        "total": total,\n        "scaled": scaled,\n    }\n')
    three = "def three(values):\n    log = []\n" + block + "    log.append(result)\n    return log\n"
    four = "def four(values):\n" + block + "    return result\n"
    assert "dup" in kinds(BASE, BASE + three + four)
    assert "dup" in kinds(BASE + four, BASE + four + four.replace("def four", "def five"))


def test_test_file_and_container_smells() -> None:
    test_src = ('import pytest\n\ndef test_a(client):\n    client._send()\n'
                '    with pytest.raises(ValueError, match="bad thing happened"):\n        client.send()\n')
    assert {"private", "prose"} <= kinds("", test_src, "tests/test_x.py")
    wide = "class Wide:\n" + "".join(f"    def m{i}(self):\n        return {i}\n" for i in range(21))
    assert "class" in kinds(BASE, BASE + wide)
    grown = check(BASE + wide, BASE + wide + "    def m99(self):\n        return 99\n", "pkg/mod.py", None)
    assert [f.note for f in grown if f.kind == "class"] == [True]  # one more method on an oversized class is a note
    assert reverse("a = 2\n", [("a = 1\n", "a = 2\n", False)]) == "a = 1\n"


class FakeJevCache:
    """Answers by source text, so the ratchet logic runs without the network."""

    def __init__(self, answers: dict[str, dict[str, float]]):
        self.answers = answers

    def ask(self, source: str, qualname: str) -> dict[str, float] | None:
        return self.answers.get(source)


def test_jev_ratchet() -> None:
    limits = {name: dict(jev_review.DEFAULT_GATE) for name in jev_review.QUESTIONS}
    limits["srp"]["block"] = 0.9  # as if calibration had cleared SRP for blocking
    new = jev_review.Candidate("f", 3, "NEW", None)
    found = jev_review.judge(new, FakeJevCache({"NEW": {"srp": 0.95, "naming": 0.7, "ocp": 0.1}}), limits)
    assert {(v.question, v.blocks) for v in found} == {("srp", True), ("naming", False)}
    changed = jev_review.Candidate("f", 3, "NEW", "OLD")
    assert jev_review.judge(changed, FakeJevCache({"NEW": {"srp": 0.95}, "OLD": {"srp": 0.97}}), limits) == []



def test_jev_on_by_default_with_key_and_opt_out() -> None:
    saved = {name: os.environ.pop(name, None) for name in ("CLEAN_CODE_JEV", "TYPESAFE_API_KEY")}
    try:
        assert not jev_review.enabled()  # no key: nothing to send with
        os.environ["TYPESAFE_API_KEY"] = "synthetic-test-key"
        assert jev_review.enabled()  # a key alone turns it on
        os.environ["CLEAN_CODE_JEV"] = "0"
        assert not jev_review.enabled()
        assert jev_review.assess([jev_review.Candidate("f", 1, "x = 1\n" * 9, None)]) == []
    finally:
        for name, value in saved.items():
            os.environ.pop(name, None)
            if value is not None:
                os.environ[name] = value


def test_hook_payload_per_agent() -> None:
    claude = {"tool_name": "Edit", "cwd": "/r", "tool_input": {"file_path": "/r/a.py", "old_string": "x", "new_string": "y"}}
    assert hook_payload(claude)[3] == [Path("/r/a.py")]
    patch = "*** Begin Patch\n*** Update File: pkg/b.py\n@@\n-x\n+y\n*** Add File: pkg/c.py\n+z\n*** End Patch"
    codex = {"tool_name": "apply_patch", "cwd": "/r", "tool_input": {"command": ["apply_patch", patch]}}
    assert hook_payload(codex)[3] == [Path("/r/pkg/b.py"), Path("/r/pkg/c.py")]
    copilot = {"toolName": "replace_string_in_file", "cwd": "/r", "toolArgs": '{"filePath": "/r/d.py"}'}
    assert hook_payload(copilot)[3] == [Path("/r/d.py")]
    assert hook_output("m", True)["decision"] == "block" and hook_output("m", False)["additionalContext"] == "m"


def test_checks_code_outside_any_repository() -> None:
    with tempfile.TemporaryDirectory() as tmp:  # the system temp folder is not inside a git repository
        smelly, clean = Path(tmp) / "scratch.py", Path(tmp) / "clean.py"
        smelly.write_text(BASE + "\n\n" + big_function(), encoding="utf-8", newline="\n")
        clean.write_text(BASE, encoding="utf-8", newline="\n")
        payload = {"tool_name": "Write", "cwd": tmp, "tool_input": {"file_path": str(smelly)},
                   "tool_response": {"type": "create"}}
        hooked = run_script("--hook", stdin=json.dumps(payload))
        assert hooked.stdout and json.loads(hooked.stdout)["decision"] == "block", hooked.stderr
        assert run_script(str(smelly)).returncode == 1
        assert run_script(str(clean)).returncode == 0


def test_hook_checks_edits_not_reads() -> None:
    with tempfile.TemporaryDirectory() as tmp:  # outside git, so a checked file is judged whole
        smelly = Path(tmp) / "scratch.py"
        smelly.write_text(BASE + "\n\n" + big_function(), encoding="utf-8", newline="\n")
        reads = [{"toolName": "view", "toolArgs": {"path": str(smelly), "view_range": [1, 5]}},
                 {"toolName": "read_file", "toolArgs": json.dumps({"filePath": str(smelly)})}]
        for read in reads:
            assert run_script("--hook", stdin=json.dumps({"cwd": tmp, **read})).stdout == "", read["toolName"]
        create = {"toolName": "create", "cwd": tmp, "toolArgs": {"path": str(smelly), "file_text": smelly.read_text()}}
        assert json.loads(run_script("--hook", stdin=json.dumps(create)).stdout)["decision"] == "block"


def test_hook_judges_an_edit_on_what_it_added() -> None:
    with tempfile.TemporaryDirectory() as tmp:  # outside git, only the edit call shows what was there before
        smelly = Path(tmp) / "scratch.py"
        for tool in EDIT_ARGS:
            smelly.write_text(BASE.replace("a + 1", "a + 2") + "\n\n" + big_function(), encoding="utf-8", newline="\n")
            quiet = run_script("--hook", stdin=json.dumps(edit_payload(tool, smelly, "a + 1", "a + 2")))
            assert quiet.stdout == "", tool
            added = "import json\n    return json.dumps(a)"
            smelly.write_text(BASE.replace("return a + 1", added) + "\n\n" + big_function(), encoding="utf-8", newline="\n")
            hooked = run_script("--hook", stdin=json.dumps(edit_payload(tool, smelly, "return a + 1", added)))
            assert ": 1 problem(s)" in json.loads(hooked.stdout)["reason"], tool


def run_all() -> int:
    for test in (test_new_function_smells, test_moves_and_small_growth_stay_quiet, test_dispatch_smells,
                 test_duplication, test_test_file_and_container_smells, test_jev_ratchet,
                 test_jev_on_by_default_with_key_and_opt_out, test_hook_payload_per_agent,
                 test_checks_code_outside_any_repository, test_hook_checks_edits_not_reads,
                 test_hook_judges_an_edit_on_what_it_added):
        test()
    print("code_smells self-test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(run_all())

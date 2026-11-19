#!/usr/bin/env python3
"""Behaviour tests for the test-maker mutation probe.

Each test builds a tiny real project (a module, a check script and a mutants file)
in a temporary directory and runs the probe on it as a user would.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
PROBE = SKILL_ROOT / "scripts" / "mutation_probe.py"
EXAMPLES = SKILL_ROOT / "examples"
EXAMPLE_MUTANTS = EXAMPLES / "mutants.json"

CALC = "def add(a, b):\n    return a + b\n\n\ndef sign(x):\n    if x < 0:\n        return -1\n    return 1\n"
# Checks add and the negative branch of sign, but never sign(0): the boundary is a known gap.
CHECK = "import calc\n\nassert calc.add(2, 3) == 5\nassert calc.sign(-4) == -1\nprint('2 checks passed')\n"
ADD_SUBTRACTS = {"name": "add subtracts", "file": "calc.py", "old": "return a + b", "new": "return a - b"}
SIGN_BOUNDARY = {"name": "sign boundary", "file": "calc.py", "old": "if x < 0:", "new": "if x <= 0:"}
SIGN_FLIPPED = {"name": "sign flipped", "file": "calc.py", "old": "return -1", "new": "return 1"}
# A second module the check never reads: mutating it must not change the outcome.
LABELS = 'TITLE = "Calculator"\n'
TITLE_CHANGED = {"name": "title changed", "file": "labels.py", "old": "Calculator", "new": "Calc"}


class ProbeProject:
    """A throwaway project with a module under test and a check command."""

    def __init__(self, directory: Path, check: str = CHECK):
        self.dir = directory
        (directory / "calc.py").write_text(CALC, encoding="utf-8", newline="\n")
        (directory / "check.py").write_text(check, encoding="utf-8", newline="\n")
        (directory / "labels.py").write_text(LABELS, encoding="utf-8", newline="\n")
        self.cmd = f'"{sys.executable}" check.py'

    def run_probe(self, mutants, *extra: str) -> subprocess.CompletedProcess:
        mutants_file = self.dir / "mutants.json"
        mutants_file.write_text(json.dumps(mutants), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(PROBE), "--mutants", str(mutants_file), "--cmd", self.cmd, "--cwd", str(self.dir), *extra],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def source(self) -> str:
        return (self.dir / "calc.py").read_text(encoding="utf-8")


class ProbeTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = ProbeProject(Path(tmp.name))


class ScoringTests(ProbeTestCase):
    def test_reports_killed_and_surviving_mutants(self):
        result = self.project.run_probe([ADD_SUBTRACTS, SIGN_BOUNDARY])

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("2 checks passed", result.stdout)
        self.assertIn("1/2 mutants killed (50%)", result.stdout)
        self.assertIn("Survivors:\n  - sign boundary", result.stdout)

    def test_report_file_records_each_mutant(self):
        report_file = self.project.dir / "report.json"

        self.project.run_probe([ADD_SUBTRACTS, SIGN_FLIPPED, SIGN_BOUNDARY], "--report", str(report_file))

        report = json.loads(report_file.read_text(encoding="utf-8"))
        self.assertEqual((report["killed"], report["total"]), (2, 3))
        self.assertEqual(
            [(r["name"], r["killed"]) for r in report["results"]],
            [("add subtracts", True), ("sign flipped", True), ("sign boundary", False)],
        )

    def test_applies_every_edit_of_a_multi_edit_mutant_together(self):
        # Alone, each edit leaves add(2, 3) == 5; only together do they make it 6.
        both = {
            "name": "offset defined and used",
            "file": "calc.py",
            "edits": [
                {"old": "def add(a, b):", "new": "OFFSET = 1\n\n\ndef add(a, b):"},
                {"old": "return a + b", "new": 'return a + b + globals().get("OFFSET", 0)'},
            ],
        }

        result = self.project.run_probe([both])

        self.assertIn("KILLED   offset defined and used", result.stdout)

    def test_fail_under_exits_1_when_the_score_is_too_low(self):
        result = self.project.run_probe([ADD_SUBTRACTS, SIGN_BOUNDARY], "--fail-under", "51")

        self.assertEqual(result.returncode, 1)

    def test_fail_under_passes_when_the_score_meets_it(self):
        result = self.project.run_probe([ADD_SUBTRACTS, SIGN_BOUNDARY], "--fail-under", "50")

        self.assertEqual(result.returncode, 0)

    def test_a_mutant_that_hangs_counts_as_killed_and_is_restored(self):
        hang = {"name": "add never returns", "file": "calc.py", "old": "return a + b", "new": "while True:\n        pass"}

        result = self.project.run_probe([hang], "--timeout", "3")

        self.assertIn("KILLED   add never returns", result.stdout)
        self.assertIn("timed out after 3s", result.stdout)
        self.assertEqual(self.project.source(), CALC)


class RestorationTests(ProbeTestCase):
    def test_restores_the_source_after_every_mutant(self):
        self.project.run_probe([ADD_SUBTRACTS, SIGN_BOUNDARY])

        self.assertEqual(self.project.source(), CALC)

    def test_a_mutant_in_one_file_is_gone_before_the_next_file_is_mutated(self):
        # If add-subtracts were still in calc.py, the harmless labels.py mutant would be killed too.
        result = self.project.run_probe([ADD_SUBTRACTS, TITLE_CHANGED])

        self.assertIn("KILLED   add subtracts", result.stdout)
        self.assertIn("SURVIVED title changed", result.stdout)
        self.assertEqual((self.project.dir / "labels.py").read_text(encoding="utf-8"), LABELS)


class InputErrorTests(ProbeTestCase):
    def assert_rejected(self, mutants, message: str):
        result = self.project.run_probe(mutants)

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(message, result.stderr)
        self.assertEqual(self.project.source(), CALC)

    def test_rejects_an_edit_that_matches_nowhere(self):
        self.assert_rejected([{**ADD_SUBTRACTS, "old": "return a * b"}], "found 0")

    def test_rejects_an_edit_that_matches_more_than_once(self):
        self.assert_rejected([{**ADD_SUBTRACTS, "old": "return"}], "found 3")

    def test_rejects_an_edit_that_changes_nothing(self):
        self.assert_rejected([{**ADD_SUBTRACTS, "new": "return a + b"}], "different 'new'")

    def test_rejects_a_missing_source_file(self):
        self.assert_rejected([{**ADD_SUBTRACTS, "file": "nowhere.py"}], "file not found")

    def test_rejects_an_empty_mutants_list(self):
        self.assert_rejected([], "non-empty JSON list")

    def test_rejects_a_mutant_that_is_not_an_object(self):
        self.assert_rejected(["calc.py"], "expected a JSON object")

    def test_rejects_a_later_edit_that_an_earlier_edit_removed(self):
        # Both edits match the original once, but after the first, "a + b" no longer exists.
        overlapping = {
            "name": "overlapping edits",
            "file": "calc.py",
            "edits": [{"old": "return a + b", "new": "return a - b"}, {"old": "a + b", "new": "a * b"}],
        }

        self.assert_rejected([overlapping], "found 0")

    def test_rejects_a_missing_mutants_file(self):
        result = subprocess.run(
            [sys.executable, str(PROBE), "--mutants", str(self.project.dir / "absent.json"), "--cmd", self.project.cmd],
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Bad mutants file", result.stderr)

    def test_reports_a_failing_baseline_that_prints_non_ascii_output(self):
        # Test runners print symbols such as jest's "●"; the probe's own output is piped here.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        noisy = ProbeProject(
            Path(tmp.name),
            check='import sys\nsys.stdout.buffer.write("\\u25cf \\u274c failed\\n".encode("utf-8"))\nraise SystemExit(1)\n',
        )

        result = noisy.run_probe([ADD_SUBTRACTS])

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Baseline run failed", result.stdout)

    def test_refuses_to_probe_when_the_baseline_fails(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        failing = ProbeProject(Path(tmp.name), check="raise SystemExit(1)\n")

        result = failing.run_probe([ADD_SUBTRACTS])

        self.assertEqual(result.returncode, 2)
        self.assertIn("Baseline run failed", result.stdout)
        self.assertNotIn("KILLED", result.stdout)


@unittest.skipUnless(importlib.util.find_spec("pytest"), "the examples need pytest")
class ExampleTests(unittest.TestCase):
    """The examples/ demo: the weak test file misses what the rewrite catches."""

    def probe_example(self, test_file: str) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = Path(tmp.name)
        for item in EXAMPLES.glob("*.*"):
            shutil.copy(item, work / item.name)
        result = subprocess.run(
            [
                sys.executable,
                str(PROBE),
                "--mutants",
                str(work / "mutants.json"),
                "--cwd",
                str(work),
                "--cmd",
                f'"{sys.executable}" -m pytest {test_file} -q -p no:cacheprovider',
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_the_weak_tests_catch_only_the_date_format_change(self):
        output = self.probe_example("test_search_settings_weak.py")

        self.assertIn("1/10 mutants killed (10%)", output)
        self.assertIn("KILLED   prompt: date format changed", output)

    def test_the_rewritten_tests_catch_every_mutant(self):
        output = self.probe_example("test_search_settings.py")

        self.assertIn("10/10 mutants killed (100%)", output)


if __name__ == "__main__":
    unittest.main()

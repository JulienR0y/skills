# Case study: a test file that passed but caught nothing

The `examples/` folder holds a small module, the kind of test file agents often write for it, and the rewrite this skill
produces. Both test files pass. The probe shows the difference:

```bash
cd <skill dir>/examples
python ../scripts/mutation_probe.py --mutants mutants.json --cmd "python -m pytest test_search_settings_weak.py -q"
python ../scripts/mutation_probe.py --mutants mutants.json --cmd "python -m pytest test_search_settings.py -q"
```

| Test file | Mutants killed |
|---|---|
| `test_search_settings_weak.py` (before) | 1 / 10 |
| `test_search_settings.py` (after) | 10 / 10 |

The same pattern showed up in a real rewrite of a chat agent's test file: 11 of 26 mutants killed before, 26 of 26
after.

## Before

| Problem | Effect |
|---|---|
| The test data equals every default (`k=20`, `keyword_k=20`, `rerank_n=5`, ...). | `from_dict` can read `k` from the wrong key, ignore `rerank_n`, or `to_dict` can swap two keys, and the round trip still passes. Changing a default passes too. |
| The expected date is computed with the same `strftime` call as the code. | The check is tautological, and a run crossing midnight can fail. It only caught the date-format mutant because the format string happened to be written out twice. |
| No test passes tools or documents. | The tool list, document de-duplication and one/many-document guidance never run. |
| No error case. | Removing the `k < 1` validation goes unnoticed. |

In the real rewrite, two more problems appeared:

- **A mocked factory.** The model client was patched with a mock whose `name` was hard-coded, so the model name
  survived a round trip whatever the code did.
- **Inconsistent types.** One test compared a mode to the enum and another to its string value, which enshrined an
  inconsistency in the type returned.

## After

- **Data that differs from every default**: a `stored` fixture with `large-model`, `12/8/3` and `True`. A swapped or
  dropped field now changes the result.
- **Defaults pinned separately**: one test builds from an empty dict and compares with literal defaults.
- **Error path**: `pytest.raises(ValueError, match=...)` for `k=0` and `k=-3`, as named parameters.
- **A fixed date**: `TODAY = date(2026, 1, 15)` and literal expected text, instead of recomputing the format.
- **Every prompt branch**: tools in order, one document listed twice, two documents. Each case also asserts that the
  other branch's text is absent.
- **Tests grouped by seam** (`TestSettings`, `TestSystemPrompt`), each one Arrange, Act, Assert.

In the real rewrite, the mock was replaced by the real model client built offline (a fake API key, no request sent),
and the tests asserted on the settings that client actually received. Two defects found along the way became strict
`xfail` tests, each logged as a follow-up rather than fixed in the test-only change.

## What the review added

Three independent reviewers looked at correctness, design, and idioms with CI fit. They confirmed that each test got
a fresh copy of the factory's mutable data, and that each `xfail`'s `raises=` matched the real failure. One optional
fix (a shared fixture instead of three inline constructions) went in; one issue that predated the change was logged.

## Operational notes

- The suite's shared `conftest.py` needed a database for every test. The fast local loop skipped it (`--noconftest`)
  with database settings pointing at an unreachable host. CI, with the real setup, confirmed the same result.
- pre-commit stashes unstaged changes, so commits waited until no probe was running.

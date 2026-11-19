---
name: test-maker
description: >-
  Writes and refactors automated tests so they catch real regressions: happy path,
  error handling and mutation resistance, real objects before mocks, factories for
  test data, framework idioms taken from the official docs, and a structure that
  supports test-driven development. Measures test strength with a mutation probe
  that runs before and after the change. Use when rewriting or refactoring a test
  file, when tests seem to "test nothing", when adding tests while working on a
  ticket or bug fix, or when asked about test quality, mutation testing, pytest
  idioms, or replacing mocks.
---

# Test maker

Two modes:

- **Refactor a test file**: rewrite an existing file so it fails on real regressions. Follow [Workflow A](#workflow-a-refactor-a-test-file).
- **Tests for a ticket**: build tests test-first while implementing a change. Follow [Workflow B](#workflow-b-tests-while-working-on-a-ticket).

Both modes use the same quality bar and the same measure: a mutation probe (`scripts/mutation_probe.py`). It breaks the source one small edit at a time and records which breakages the tests catch.

## Quality bar

A test file is done when all of these hold:

1. **Happy path, error handling, mutation resistance.** Every behaviour has a test that fails when that behaviour breaks: each error path is covered, and the probe kills every non-equivalent mutant.
2. **Real objects first.** Mocks are a last resort; see the [mock policy](#mock-policy).
3. **Factories keep tests clean.** Test data comes from factories and fixtures, not from dicts copied between tests.
4. **Framework idioms come from the official docs.** Look them up on the web for the framework and version in use, and cite them in the MR. For pytest, start from [pytest-idioms.md](references/pytest-idioms.md).
5. **TDD-ready.** A new behaviour can be added as one red test using the existing fixtures, with no new scaffolding.

## Rules that make tests able to fail

These come from real rewrites; each one caught a class of silent passes.

- **Test data must differ from the defaults.** If a fixture's values equal the defaults, a mapping that drops or swaps a field still passes. Give every optional field a distinct, non-default value.
- **Never recompute the expected value the way the code does.** Use literals from an independent source, such as the spec, a worked example or a shipped config. Freeze clocks and seed randomness so the expected value can be a literal.
- **Don't assert what a mock returns.** If a mocked factory returns an object with a hard-coded `name`, a round trip through that name passes whatever the code does.
- **One contract, every entry point.** When two entry points promise the same thing (a constructor and `from_dict`, the sync and async paths), parametrize one fixture over both rather than copying tests.
- **Error paths use the real exception type and a message match**, for example `pytest.raises(ValueError, match="unknown model")`. Cover unknown values, missing required fields and unknown fields.
- **Known defects become strict expected failures, not expected behaviour.** Use `xfail(strict=True, raises=<exact type>, reason=...)`, and name the consumer that hits the defect. When someone fixes it, the test passes unexpectedly and strict mode forces them to remove the marker. In a test-only change, don't fix the source; log a follow-up instead.
- **Code that returns inconsistent types:** assert the value in a type-tolerant way, for example `Mode(x) is Mode.SEMANTIC`, and pin the inconsistency in its own expected-failure test.
- **Test at public seams.** If a private method is the only practical seam, route every call through one helper, explain why in the module docstring, and name the public alternative.
- **Each test names one behaviour** and follows Arrange, Act, Assert with blank lines between them.

## Mock policy

Pick the first option that works:

1. **The real object, built offline.** For example, a real LLM client built with a fake API key, which never sends a request.
2. **The real object with only its boundary replaced:** an environment variable, the clock, the HTTP transport, or a filesystem in a temporary directory.
3. **A hand-written fake for a narrow interface,** for example a recording tools manager that counts its calls, or an index exposing only `as_tool()`.
4. **A mock,** only for something you cannot build. Use autospec, and never patch a collaborator just to get a handle you can assert on.

## Workflow A: refactor a test file

Copy this checklist into the task notes and tick it off:

```
- [ ] 1. Read the code under test, its production callers and shipped configs
- [ ] 2. Look up the framework's official idioms (web) and note the links
- [ ] 3. Write mutants and run the baseline probe on the current file
- [ ] 4. Choose and state the seams
- [ ] 5. Build factories and fixtures
- [ ] 6. Rewrite one seam at a time, running after each slice
- [ ] 7. Re-run the probe and resolve every survivor
- [ ] 8. Run linters, the formatter and the suite the way CI runs it
- [ ] 9. Independent review, then an MR with before/after scores
```

1. **Read.** Find how production builds and calls the code. Shipped configs and fixtures give realistic values; for example, the production config may use a different model than the test does.
2. **Idioms.** Search the official docs for the framework in use: fixtures, parametrization, exception assertions, expected failures, patching. Record the URLs for the MR.
3. **Baseline.** Write 15 to 30 single-edit mutants covering each behaviour: defaults, field mappings in both directions, each branch, each error path, and the order and format of composed output. Run the probe against the existing file. The survivors are the list of gaps. See [mutation-testing.md](references/mutation-testing.md).
4. **Seams.** List the public interfaces you will test through. When the user is present, confirm them. Otherwise state them in the MR.
5. **Factories.** Prefer the repository's existing factory library, for example a factory_boy `Trait`. Data must differ from the defaults, and every build must get a fresh copy of mutable values (`factory.Dict`, not a plain dict).
6. **Rewrite in vertical slices.** Do one seam at a time: write its tests, run them, then move on. Group tests by seam.
7. **Survivors.** For each survivor, decide:
   - it is a gap: add a test that tells the mutant from the real code;
   - it is equivalent (no input can tell them apart): document it;
   - it is unreachable: drop it.
   The target is that every non-equivalent mutant is killed.
8. **Verify the way CI does.** Run the linter and the formatter. A local run may skip heavy suite setup, but the pipeline must pass with the real suite configuration.
9. **Review and MR.** Use three independent reviewers with different focus: correctness of the tests, design and seams, and idioms and CI fit. List each finding as fixed, deferred or dismissed. The MR states the before/after mutation score, the seams, the expected-failure tests and the follow-ups, and stays test-only.

## Workflow B: tests while working on a ticket

1. Turn each acceptance criterion and error case into a behaviour at an agreed seam.
2. **Red:** write one failing test for one behaviour and check that it fails for the right reason.
3. **Green:** write only enough code to pass it. Repeat for the next behaviour.
4. **Before review:** write 5 to 10 mutants of the new or changed logic only, then run the probe on the tests you touched. Each survivor is a missing test; add it.
5. In the MR, map each criterion to its test and report the mutation result.

## Mutation probe

The probe lives in this skill's `scripts/` directory. Resolve that path relative to this `SKILL.md`, not the repository under test. It needs Python 3.10 or later and has no third-party dependencies.

```bash
python <skill dir>/scripts/mutation_probe.py \
  --mutants mutants.json \
  --cmd "python -m pytest tests/test_settings.py -q" \
  --report mutation-report.json --fail-under 100
```

- It works with any test command that exits 0 on success, including pytest, vitest and jest.
- It refuses to start unless the baseline run passes, and it checks that each mutant's text matches exactly once.
- It restores every file, even after an error.
- `examples/` is a runnable before/after demo: see the [case study](references/case-study.md).

## Pitfalls seen in practice

- **A suite-wide setup file that needs a database or other services** (for example a pytest `conftest.py` that runs migrations for every test): for fast local runs of pure unit tests, skip it (`--noconftest`) and point any database settings at an unreachable placeholder host. CI still runs the full suite, so check the pipeline result.
- **Never commit while the probe is running.** The probe mutates source on disk. Git hooks such as pre-commit stash unstaged changes, which can capture or disturb a mutant. Run `git status` after every probe; if a probe was killed hard, restore the sources with git.
- **Count assertions need data that tells the counts apart.** With 1 killed and 1 survived, a report that counts survivors instead of kills still shows 1; use, for example, 2 killed and 1 survived.
- **Lint hooks may flag private access.** Confine it to the one documented seam helper rather than suppressing each line.
- **Shared mutable factory defaults** (a plain `dict` attribute on a factory) leak between tests that mutate them.

## MR template

```markdown
## Goal
Why the old tests missed regressions (one paragraph).

| Test file | Mutants killed |
|---|---|
| before | X / N |
| after | N / N |

## What changed
- Real objects / fakes used; what is still patched and why
- Factories added
- Seams tested; the private seam, if any, and why
- Error paths covered
- Known defects as strict xfail (one line each, with the consumer)

## Verification
Local run, linters, mutation probe, pipeline.

## Review process
Tools used; reviewers; findings fixed / deferred / kept.
```

## Additional resources

- [pytest-idioms.md](references/pytest-idioms.md): pytest and factory_boy idioms with links to the official docs.
- [mutation-testing.md](references/mutation-testing.md): choosing mutants, judging survivors, limits.
- [case-study.md](references/case-study.md): a weak test file and its rewrite, scored with the probe (1/10 against 10/10), runnable from `examples/`.

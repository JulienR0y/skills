# Mutation testing with the probe

A mutant is one small, deliberate break in the source. If the tests still pass with the break in place, they cannot see that behaviour. The probe (`scripts/mutation_probe.py`) applies mutants one at a time and records which ones the tests kill.

## Choosing mutants

Write 15 to 30 mutants for a test-file refactor, or 5 to 10 for new ticket logic. Each mutant is one plausible bug, not random noise. Cover each category that applies:

| Category | Example edit |
|---|---|
| Default value | `k: int = 20` → `k: int = 10` |
| Field mapping, read side | `config.get("k")` → `config.get("keyword_k")`, or remove the line |
| Field mapping, write side | swap two keys in `to_dict` |
| Forwarded argument | `reasoning_effort=self._config.reasoning_effort` → `reasoning_effort=None` |
| Constant | `output_token_limit=32768` → `4096` |
| Branch condition | `== 1` → `> 1`; `if flag:` → `if False:` |
| Precedence | swap `if tools: ... elif manager:` |
| Collection handling | remove a de-duplication guard; `append` → `insert(0, ...)` |
| Output format and order | change a separator, a date format, or drop one section |
| Error path | remove a validation `raise` |

Keep each edit to a single line or a small block. Each mutant's `old` text must match exactly once, which the probe checks.

## mutants.json

```json
[
  {
    "name": "to_dict: swaps k and keyword_k",
    "file": "app/search_settings.py",
    "edits": [
      {"old": "\"k\": self.k,", "new": "\"k\": self.keyword_k,"},
      {"old": "\"keyword_k\": self.keyword_k,", "new": "\"keyword_k\": self.k,"}
    ]
  },
  {"name": "default: k changed", "file": "app/search_settings.py",
   "old": "    k: int = 20\n", "new": "    k: int = 10\n"}
]
```

`examples/mutants.json` holds a runnable set of 10; see the [case study](case-study.md).

## Running

```bash
python <skill dir>/scripts/mutation_probe.py --mutants mutants.json --cmd "<test command>" [--cwd <repo root>] [--report out.json] [--fail-under 100]
```

- Use the narrowest test command that should catch the mutants, usually one test file. Each mutant costs one full run of it.
- Run the probe on the old file and on the new file to get the before/after score for the MR.
- A run longer than `--timeout` counts as killed (a mutant that loops forever), and the command's whole process tree is stopped.
- Each mutant gets a unique file timestamp, and restoring puts the original timestamp back. Without that, a same-length mutant written within the same second as the last run can hit a stale cache, such as Python's bytecode, and falsely survive.
- Two worktrees can be probed in parallel. Two probes in the same worktree cannot, since both mutate the same files.
- Don't commit, rebase or switch branches while a probe runs; afterwards, check `git status`.

## Judging survivors

| Survivor kind | Test | Action |
|---|---|---|
| **Gap** | Some input makes the mutant behave differently, and no test uses it. | Add a test with that input. |
| **Equivalent** | No input can tell the mutant from the real code. | Drop it and note why. |
| **Masked by test data** | The test data happens to match both versions, for example values equal to the defaults. | Change the factory data, not the assertion. |

Worked example: a mutant that made `to_dict` report the model name from the stored config instead of from the model object survived. Whenever a model name was stored, both versions returned the same value. They differ only when none is stored and the default applies, so one test for that case killed it. It was a real gap, not an equivalent mutant.

## Limits

- The probe only tests the mutants you write. A high score shows that those behaviours are protected, not that coverage is complete. State this in the MR.
- For broad automated mutation, use a dedicated tool if the repository adopts one: mutmut or cosmic-ray for Python, Stryker for JavaScript and TypeScript. Adding such a tool is a separate decision, not part of a test refactor.

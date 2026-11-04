---
name: clean-code-guard
description: Clean Code, SOLID and DRY rules for any code you write, edit or review, in any language and any repository. Use it whenever you write or change code, add a function, class, module or test, before handing off a change, and every time a "Clean Code / SOLID / DRY check" hook message reports a finding. Also use it when the user asks about code smells, refactoring or code quality.
---

# Clean Code guard

Follow Clean Code, SOLID and DRY in every change. Keep functions small and name them for what they do. Give each
function and class one job. Do not copy code. Do not dispatch on strings. Do not swallow errors. Test behaviour,
not internals.

The hook checks each Python file you write. Layer 1 measures the syntax tree. Layer 2 asks TypeSafe's Jev model
design questions about new or changed functions, when it is turned on. Both report only what your change added.
For other languages, apply the same limits yourself.

## Before you write

1. Look for an existing helper first. Search for the operation and for the name you would give it, for example
   `rg "def _canonical|json.dumps\(.*sort_keys"`. Reuse what you find. If two places need it, move it to a shared
   module. (DRY)
2. Put new behaviour in the module or class named for that job. If the class or file you would extend is already
   over the limits below, write a new collaborator and pass it in. (SRP, DIP)
3. Give values a type. A fixed set of strings, such as a status, kind, workflow or phase, is an Enum. A dict with
   known keys is a dataclass or TypedDict. Parse raw input once at the boundary, then trust the types. (OCP)

## Limits

Layer 1 enforces these for Python. Hold other languages to the same numbers.

| Unit | Limit |
|---|---|
| Function | 50 lines, 10 `if` statements, 4 levels of nesting, 6 parameters, 2 inner functions |
| Condition | 5 `and`/`or` terms. Name a longer one as a predicate function. |
| Class | 400 lines, 20 methods |
| File | 800 lines |
| Dispatch | A string compared 3 or more times in a file becomes an Enum. An `if`/`elif` chain of 5 or more branches becomes a dict of handlers. |
| Always | No boolean flag parameters. No broad `except` that neither re-raises nor logs. No imports inside functions. No copied blocks. No tests that call private methods or match message text. |

## Principle, smell and fix

| Principle | Smell | Fix |
|---|---|---|
| SRP | A function that does several steps. A class or file that keeps growing. | Split the steps into named functions. Put a new job in a new class and inject it. |
| OCP | `if kind == "a"` and `elif kind == "b"` repeated across files. | Use an Enum and a table of handlers, or one class per variant behind one interface. |
| LSP | A subclass that refuses, ignores or narrows a base method. Callers that check `isinstance` on subtypes. | Use composition, or a smaller interface that the subtype can honour in full. |
| ISP | A mixin that reads attributes it never declares. A caller that needs one method of a wide object. | Define a small protocol per caller. Inject exactly what is used. |
| DIP | An import inside a function. Logic that builds its own HTTP, cloud, database or browser client. | Import at module top. Pass clients in. Break an import cycle by moving the shared code down a layer. |
| DRY | A copied block. A re-implemented helper. The same check pasted in several places. | Write one helper or constant and import it. Loop over a table for repeated checks. |
| Errors | `except Exception` that returns a default. Many causes mapped to one error code. Error codes that are English sentences. | Catch the specific exception, or log its type and context before converting it. Use one code per cause, from a closed set. |
| Names and comments | Names that describe mechanics. Comments that carry ticket or incident IDs. | Name things for what they do. Use comments to say why. Put the incident story in the commit message. |
| Tests | Calls to private methods. `match=` on message text. A fake copied into every test file. | Test public behaviour. Assert on error codes and exception types. Keep one shared fake in `conftest.py`. |

## When the hook reports

- A problem blocks your edit. It lists only problems this edit added. Fix them in your next edit. Each line says
  how.
- A note does not block. It appears for a small change to a class or file that is already too large, and for a Jev
  question that is not yet calibrated to block. Make the change you were asked for and mention the note in your
  handoff.
- If the flagged code is right on purpose, add `# smell-ok: <reason>` on the flagged line or the line above it, and
  name it in your handoff. Examples are an external API's required shape, a generated table, or a boundary that
  must catch every error. A `# smell-ok` without a reason does not count.
- A move or rename reports nothing. A move that also edits a line is compared with its old version. While a move is
  half done, with the new copy written and the old one not yet deleted, the hook reports the same code in two
  places. Finish the move.
- Do not refactor code your task did not touch to make the hook quiet. Record it as a follow-up.

## The Jev layer

Layer 2 is off by default. Each user turns it on with their own TypeSafe API key. No key ships with the plugin. It
runs when `CLEAN_CODE_JEV=1` and `TYPESAFE_API_KEY` are both set.

When it is on, it sends each new or changed function of 8 or more lines to `api.typesafe.ai`, at most 6 per edit
and at most 12,000 characters each. It asks four questions:

- Does the function do more than one job? (SRP)
- Does its name fail to describe what it does?
- Does it branch on a string or type tag that a table should replace? (OCP)
- Does it build dependencies that it should receive instead? (DIP)

A question can block only after `scripts/jev_calibrate.py` showed at least 90% precision at its threshold. The
result is stored in `scripts/jev_calibration.json`. Until then its answers are notes. If the API cannot be
reached, the check is skipped.

## Before you hand off a branch

From the repository root, run the checker against the target branch of the merge request. Fix every problem. Put
the notes in the merge request description.

The checker is `scripts/code_smells.py` in this plugin's folder, `${CLAUDE_PLUGIN_ROOT}`. That folder is two levels
above this skill's folder.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/code_smells.py" --diff origin/main
```

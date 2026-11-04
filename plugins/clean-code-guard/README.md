# clean-code-guard

clean-code-guard checks the Python code that a coding agent writes. It runs after each file edit. It reports the
Clean Code, SOLID and DRY problems that the edit added. Problems that were already in the file are not reported,
so a small fix in a large old file is judged only on the fix.

It works in Claude Code and in VS Code with GitHub Copilot. For other languages, the skill gives the agent the same
rules to follow by hand.

## What it checks

The checker has two layers.

Layer 1 reads the Python syntax tree. It needs no network. It reports these problems when an edit adds them:

| Problem | Limit |
|---|---|
| Long function | 50 lines |
| Too many `if` statements in a function | 10 |
| Deep nesting | 4 levels |
| Too many parameters | 6 |
| Long condition | 5 `and`/`or` terms |
| Too many inner functions | 2 |
| Large class | 400 lines or 20 methods |
| Large file | 800 lines |
| The same string compared again and again | 3 times in a file |
| Long `if`/`elif` chain | 5 branches |
| Boolean flag parameter | any new one |
| `except Exception` that neither re-raises nor logs | any new one |
| Import inside a function | any new one |
| Copied code, or a helper that already exists elsewhere in the repository | any new one |
| Test that calls a private method, or matches an error's message text | any new one |

Layer 2 is optional. It sends each new or changed function to TypeSafe's Jev model and asks four questions. Does the
function do more than one job? Does its name fail to describe what it does? Does it branch on a string or type tag
that a table should replace? Does it build dependencies that it should receive instead? See "Turn on the Jev layer"
below.

Each finding is either a problem or a note. A problem blocks the agent in Claude Code until it fixes it or explains
it. A note does not block. A small addition to a class or file that is already too large gives a note.

Moved and renamed code is recognised and not reported again.

## Files

| File | What it does |
|---|---|
| `hooks/hooks.json` | Runs the checker after each file edit in Claude Code, Codex and the Copilot CLI. |
| `skills/clean-code-guard/SKILL.md` | Tells the agent the rules, the limits and how to answer a finding. |
| `scripts/code_smells.py` | The checker: hook mode, `--diff` mode and `--self-test`. |
| `scripts/smell_rules.py` | The measurements behind layer 1. |
| `scripts/jev_review.py` | Layer 2, the Jev questions. Off by default. |
| `scripts/jev_calibrate.py` | Measures how precise each Jev question is, to decide which ones may block. |
| `scripts/test_code_smells.py` | Tests for the checker. |
| `scripts/install_copilot.py` | Installs the checker as a user-level VS Code Copilot hook. |

The scripts use only the Python standard library. They need Python 3.10 or later.

## Install

In Claude Code:

```
/plugin install clean-code-guard --marketplace JulienR0y/skills
```

For Codex, Copilot and other agents, see the [repository README](../../README.md). `python3` must be on your PATH.

If you registered `code_smells.py` yourself in `~/.claude/settings.json` before, remove that entry. Otherwise every
edit is checked twice.

## What each agent does with a finding

| Agent | Problem | Note |
|---|---|---|
| Claude Code | Blocks until the agent fixes it or keeps it with `# smell-ok` | Added to the agent's context |
| Codex | Same as Claude Code. Approve the hook once after you install the plugin. | Added to the agent's context |
| Copilot (CLI and VS Code) | Advice only: a Copilot `postToolUse` hook cannot block an edit | Added to the agent's context |

To add the hook to VS Code Copilot without a plugin, run `python3 scripts/install_copilot.py` from a clone. It copies
the checker to `~/.copilot/hooks/clean-code-guard/` and writes `~/.copilot/hooks/clean-code-guard.json`. Reload VS
Code afterwards and run it again after each update.

## Run it from the command line

```bash
python3 <plugin>/scripts/code_smells.py --diff origin/main
python3 <plugin>/scripts/code_smells.py --self-test
```

`--diff` checks the Python files that changed against a branch or commit. Run it from the root of the repository you are checking. `<plugin>` is this plugin's folder. It exits
with code 1 when it finds a problem, so it can run in CI or before a commit.

## Keep a finding on purpose

Sometimes the flagged code is right, for example a broad `except` at a boundary that must catch everything. Add
`# smell-ok: <reason>` on the flagged line or the line above it. A `# smell-ok` without a reason does not count.

## Turn on the Jev layer

The Jev layer is off by default. No API key ships with this plugin. Each user who wants it needs their own TypeSafe
API key from https://typesafe.ai.

When it is on, it sends the source of each new or changed function to `https://api.typesafe.ai/v1/systemone`.
Check that you are allowed to send that code to a third-party service before you turn it on.

To turn it on, set two environment variables:

```bash
export CLEAN_CODE_JEV=1
export TYPESAFE_API_KEY=<your own key>
```

Do not put the key in this repository or in any committed file.

It sends at most 6 functions per edit. It skips functions shorter than 8 lines and cuts each function at 12,000
characters. It remembers answers, so an unchanged function is not sent twice. If the API cannot be reached, the
check is skipped and nothing is blocked.

A changed function is reported only when its answer crossed a threshold that its old version stayed under.

## Calibrate the Jev layer

A Jev question only gives notes until calibration shows that it is precise enough to block. Calibration needs a
codebase you know well.

```bash
python3 <plugin>/scripts/jev_calibrate.py label <repo> <commit> labels.json
python3 <plugin>/scripts/jev_calibrate.py run labels.json
```

`label` works offline. It picks functions from the repository and labels them from measured facts:

- SRP: a function of 150 or more lines with 15 or more `if` statements does more than one job.
- OCP: a function that compares the same string 3 or more times branches on a tag.
- DIP: a function that imports inside itself and constructs a class builds its own dependencies.
- Small pure helpers of 8 to 25 lines are the clean examples.

`run` sends those functions to TypeSafe. It writes `scripts/jev_calibration.json` with the thresholds and counts. A
question may block at the lowest threshold of 0.9, 0.95 or 0.98 where at least 90% of its hits are correct, with
at least 5 hits. The naming question has no automatic labels, so it never blocks.

The label file contains the source code of the calibrated repository. `.gitignore` keeps `*labels*.json` out of
commits. Commit only `jev_calibration.json`.

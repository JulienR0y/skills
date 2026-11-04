---
name: adversarial-review
description: "Adversarial code review of a change before opening or on a merge/pull request. Run three review lenses (silent failures, test-coverage gaps, line-by-line \"what breaks this\"), verify every finding against the actual code, and produce a severity-ranked will-fix / skipped / dismissed consolidation. Trigger on: review my changes, review this MR or PR, check before I open an MR, peer review, find bugs, silent failures, missing tests, what could break this."
---

# Adversarial Review

A disciplined, self-verifying review pass over a code change. Two modes share
one engine:

- **Self-review** — you are about to open your own MR. Findings feed your own
  fixes; nothing is posted.
- **Peer review** — you are reviewing a teammate's MR. The consolidated findings
  are posted as a review note with an AI-disclosure footer.

The mode only changes the final step. The review itself is identical.

## 1. Build the review context

Before hunting for problems, assemble what you are reviewing so every later
claim is anchored to real code:

- The diff and its base (e.g. `git diff <base>...HEAD`, or the MR's changes).
- The branch and the commit SHA you are reviewing at.
- The *intent* of the change — what it is meant to do and why. Read the MR
  description, the commits, or ask. A review that does not know the goal cannot
  tell a bug from intended behavior.

## 2. Review across three independent lenses

Work through all three. If your harness can run them as parallel subtasks, do
so; otherwise run them sequentially. Keep them independent — each lens hunts its
own class of problem without being distracted by the others.

- **Silent-failure lens.** Swallowed exceptions, bare `except`/`catch` that hide
  errors, fallbacks that mask a failure as success, ignored return values and
  error codes, defaults that paper over missing data. Ask: if this fails at
  runtime, does anyone find out?
- **Test-coverage lens.** Where does the change add behavior that no test
  exercises? Focus on realistic gaps — error paths, boundaries, the new branch
  that only the happy path covers. For each gap, name one concrete test case
  (input to expected outcome), not "add more tests".
- **Adversarial line-by-line.** For every non-trivial expression, ask "what
  input or state would break this?" — null/empty, zero, negative, overflow,
  concurrent access, wrong type, unescaped input, off-by-one, timezone, encoding.

## 3. Verify every finding before it counts

This is the core discipline. Treat each finding — including your own — as a
**hypothesis, not a fact**, and confirm it against reality before it enters the
review:

- File/line claim -> open the file at the reviewed SHA and confirm the code
  actually reads that way.
- Schema/data claim -> check the actual model, migration, or type definition.
- CI/pipeline claim -> read the pipeline config and the job log; do not assume.
- Library/API-shape claim -> check the library at the version the project pins.

**A finding you cannot verify is dropped, not softened.** A plausible-but-wrong
comment costs the reader more than a missed nit. Better to ship five confirmed
findings than fifteen guesses.

## 4. Consolidate

- Keep only findings you would rate **confidence >= 7/10**. No stylistic nits.
- Order by severity: correctness / data-loss / security first, then robustness,
  then maintainability.
- Bucket every surviving finding into exactly one of:
  - **Will fix** — with the evidence and the concrete change.
  - **Deliberately skipped** — with the reasoning for not acting.
  - **Checked and dismissed** — a hypothesis you investigated and refuted, with
    the refuting evidence, so the reader knows it was considered.

## 5. Finish — by mode

- **Self-review:** apply the will-fix items, then you are ready to open the MR
  or PR. Nothing is posted and no disclosure is needed — the findings only
  shaped your own code.
- **Peer review:** post the consolidated findings as an MR or PR review note
  (`glab` for GitLab, `gh` for GitHub). Frame findings as suggestions, back each
  with file/line evidence, and lead with one genuine positive observation. End
  the note with the AI-disclosure footer, naming the agent that ran the review:

  > *This review was produced with <agent name>, an AI coding agent: the three
  > lenses were run, each finding was verified against the code, and unverified
  > findings were dropped. A human reviewed and approved it before posting.*

## Non-negotiables

- Verify before you assert. An unverified finding does not ship.
- Confidence >= 7/10, severity-ordered, no nits.
- Peer-review notes always carry the AI-disclosure footer.

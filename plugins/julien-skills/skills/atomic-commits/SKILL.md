---
name: atomic-commits
description: Use whenever you commit, from the first green slice of a task to the branch handoff - commit each logical change as it passes, split a mixed working tree, write commit messages, check every commit builds, and rework unpushed history. Especially when the tree mixes code with plans/artifacts/local files, when commit history must read as a reviewable timeline, or when a fix belongs in an earlier commit.
---

# Atomic Commits

## Overview

One commit = one logical change that compiles and passes tests on top of the previous commit. The series reads bottom-up — a reviewer replaying the timeline watches the feature assemble itself.

## What makes a commit atomic

- **One change.** The subject says what it does in one sentence without "and". A bug fix, a refactor, a dependency bump and a reformat are four commits.
- **Complete.** It carries everything the change needs to work: the code, its tests, the config or migration it reads, the doc line it makes true.
- **Green.** The project builds and its tests pass at this commit, not only at the tip, so `git bisect` can stop on it and `git revert` can remove it alone.
- **Revert test.** Reverting it removes exactly that change and nothing else.

Logical, not small: renaming a function across 80 files is one commit, because splitting it leaves commits that don't build. A five-line diff that changes a rule and reformats a log line is two.

Keep apart, each in its own commit: moving or renaming code vs changing it; formatting vs behavior; refactoring vs a feature or fix; one bug fix vs another.

## Commit as the work goes

The branch history is the record a person reads later. Build it while you work, not at the end.

- Slice → test → commit → next slice. Commit each logical change as soon as its tests pass; never hold a task's work for one commit at handoff.
- Test-first: the failing test and the code that makes it pass go in one commit. Keep the red run as evidence in your notes, not as a commit. Only when a CI gate must show the red pipeline before the fix may a test-only commit go first, and its body says so.
- Before every handoff, review, push or MR: all task work is in atomic commits and `git status --short` shows none of it left over.
- A squash merge doesn't change this. The branch commits are what a reviewer and a later reader replay; the squash commit's message (the MR title and description) follows the same format.

## Before the first commit

1. **Detect the team convention from evidence, not one example.** `git log --oneline -30` for message style; `git branch -r` for branch naming. Match what the majority does (freeform imperative vs Conventional Commits differ per repo — a single branch/commit is not a convention; survey 20+). If a plan prescribes a style that contradicts history, flag it and follow history.
2. **Identity check:** `git config user.name` / `user.email`. If empty, set them (repo-local) before committing — Windows auto-derives a wrong short name from the username.
3. **Never commit on main/master.** `git branch --show-current` first.

## Staging

- Stage by **explicit file list** — never `git add .` / `-A` / `-u` / `:/`, and never `git commit -a`. This is what keeps plan docs, rendered PNGs, `.env` backups, and scratch files out of the feature branch. Some agent setups refuse these commands with a pre-tool hook; list the files instead of working around it.
- One file holds two changes: stage only this change's hunks, without interactive tools. `git diff -- <file> > <scratch>/full.patch`, copy this change's hunks (with the `diff --git` and `---`/`+++` header) into `<scratch>/part.patch`, run `git apply --cached --check <scratch>/part.patch`, then `git apply --cached <scratch>/part.patch`. The other hunks stay in the working tree for the next commit.
- After staging, `git diff --cached --stat`: only the files of this change.
- Local-only files (editor config, personal notes, conventions drafts): add to `.git/info/exclude` (per-clone, unshared), not the team's `.gitignore`.

## Ordering (dependency order, each commit green)

1. Contracts / models / schemas
2. Independent building blocks, each with its tests
3. The integration piece that wires them, with its tests
4. Docs

Tests live in the **same commit** as the code they pin. Run tests + lint before each commit, not once at the end.

## Message format

- **Subject:** imperative mood, ≤50 chars, capitalized, no trailing period ("Add X", "Fix Y" — test: "If applied, this commit will <subject>").
- **Body:** wrap ~72 cols; explain **why** and what breaks without the change — never restate the diff. Longer bodies are good when they carry reviewer context (tradeoffs, root cause, what was rejected).
- **Trailers:** ticket ref (e.g. `Refs: RAA-1234`) plus the tool's attribution trailer.
- Multi-line messages: bash heredoc `git commit -F - <<'EOF' ... EOF`; PowerShell single-quoted here-string `@'...'@`.

## Reworking unpushed history

- Fix belongs in the last commit → `git add <files> && git commit --amend --no-edit`.
- Fix belongs deeper → `git reset <base-or-parent>` then restage and recommit the series in order. **No interactive rebase** in agent harnesses.
- Wrong author on existing commits → set `git config`, then replay the series the same way. Only while unpushed.
- Already pushed → don't rewrite or force-push a shared branch. Add the fix as its own atomic commit whose subject names what it fixes ("Fix empty-list crash in parse_rows"), never "Address review comments".

## Verify after

- `git log --oneline <base>..HEAD`: does the order tell the story, and does each subject pass the one-sentence, no-"and" test?
- `git status --short`: nothing unintended staged or left behind.
- Every commit green, not only HEAD: `git rebase --exec "<targeted test command>" $(git merge-base HEAD <target-branch>)`. With the merge-base as upstream it rewrites nothing and opens no editor; it runs the command at each commit (through Git's `sh`) and stops at the first that fails. Then `git rebase --abort` and fix that commit.

## Common mistakes

| Mistake | Fix |
|---|---|
| `git add .` sweeps artifacts in | Explicit file lists, always |
| One blob commit for the feature | Split by dependency order |
| Everything committed once, at handoff | Commit each logical change when its tests pass |
| Reformat or move mixed into a behavior change | Separate commit for the reformat or move |
| Tests green only at HEAD | `git rebase --exec` over the series |
| Convention inferred from one branch | Survey history/branches, follow the majority |
| "fixed stuff" / diff-restating messages | Imperative subject + why-body |
| "Address review comments" noise commits | Fold the fix into the commit that introduced the code (while unpushed) |
| Committing without identity configured | Check `git config user.name/email` first |

Sources: the Linux kernel's [Separate your changes](https://www.kernel.org/doc/html/latest/process/submitting-patches.html#separate-your-changes) (one logical change per patch, each builds, moves apart from edits) and Git's [SubmittingPatches](https://git-scm.com/docs/SubmittingPatches) (present the series as a clean logical progression).

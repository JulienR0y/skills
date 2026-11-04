---
name: atomic-commits
description: Use when committing work, splitting a working tree into commits, writing commit messages, or preparing a branch for review — especially when the tree mixes code with plans/artifacts/local files, when commit history must read as a reviewable timeline, or when unpushed commits need reworking (wrong author, fix belongs in an earlier commit).
---

# Atomic Commits

## Overview

One commit = one logical change that compiles and passes tests on top of the previous commit. The series reads bottom-up — a reviewer replaying the timeline watches the feature assemble itself.

## Before the first commit

1. **Detect the team convention from evidence, not one example.** `git log --oneline -30` for message style; `git branch -r` for branch naming. Match what the majority does (freeform imperative vs Conventional Commits differ per repo — a single branch/commit is not a convention; survey 20+). If a plan prescribes a style that contradicts history, flag it and follow history.
2. **Identity check:** `git config user.name` / `user.email`. If empty, set them (repo-local) before committing — Windows auto-derives a wrong short name from the username.
3. **Never commit on main/master.** `git branch --show-current` first.

## Staging

- Stage by **explicit file list** — never `git add .` / `-A` / `-u`. This is what keeps plan docs, rendered PNGs, `.env` backups, and scratch files out of the feature branch.
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

## Verify after

`git log --oneline` (does the order tell the story?), `git status --short` (nothing unintended staged or left behind), tests green at HEAD.

## Common mistakes

| Mistake | Fix |
|---|---|
| `git add .` sweeps artifacts in | Explicit file lists, always |
| One blob commit for the feature | Split by dependency order |
| Convention inferred from one branch | Survey history/branches, follow the majority |
| "fixed stuff" / diff-restating messages | Imperative subject + why-body |
| "Address review comments" noise commits | Fold the fix into the commit that introduced the code (while unpushed) |
| Committing without identity configured | Check `git config user.name/email` first |

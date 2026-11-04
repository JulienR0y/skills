---
name: ultraplan-local
description: Use when a user mentions ultraplan, asks for a deep implementation plan, wants parallel codebase analysis before planning, starts from a Jira ticket or feature brief, or needs a critique-reviewed plan for non-trivial codebase changes.
---

# Ultraplan Local

Produce a deep implementation plan by exploring the codebase from multiple independent angles, synthesizing the findings, and stress-testing the plan before presenting it.

Announce at start: `Using ultraplan-local: I will gather ticket/context, run parallel exploration where useful, then synthesize and critique the plan.`

## Runtime Adaptation

- Treat explicit requests for `ultraplan` or `ultraplan-local` as permission to use parallel read-only agents for planning exploration.
- In Codex, use the collaboration agent tools with `agent_type: "explorer"`; use `update_plan` for substantial workflows and present the final plan in the response.
- In Claude Code, use parallel `Agent` calls with the `Explore` subagent; use `ExitPlanMode` only when the session is actually in plan mode, otherwise present the plan normally.
- When agents are unavailable or unnecessary, parallelize independent local reads and searches with the runtime's native tool support.
- If the task starts from Jira, fetch it through `jira` or read-only `jira-advisor`. Never print PATs or authorization headers.

## Phase 0: Gather Source Context

Before codebase exploration, collect the task source:

- Jira ticket, issue URL, product brief, bug report, or user-provided requirements.
- Relevant repository root, branch, and dirty worktree constraints.
- Any explicit acceptance criteria, linked tickets, screenshots, or diagrams.

If a Jira URL is provided, extract the issue key and fetch:

- Summary, type, status, priority.
- Description and acceptance criteria.
- Comments if needed for requirements.
- Linked issues if they materially affect scope.
- Transitions only if the user asks to move or update the ticket.

## Phase 1: Parallel Exploration

Spawn these three explorer agents in parallel when the codebase is non-trivial and the user has invoked ultraplan explicitly. Replace `[TASK]` with the real task and include any ticket summary gathered in Phase 0.

### Architecture And Patterns Explorer

Ask:

```text
Investigate the codebase architecture relevant to: [TASK]

Focus on:
- Similar existing features and the closest analogue.
- Key abstractions, patterns, conventions, and module boundaries.
- Dependency flow between relevant components.
- Testing patterns and test infrastructure.
- Configuration, environment setup, and build pipeline.

Report exact file paths, symbols, patterns found, architectural constraints, and conventions new code must follow.
```

### File Impact Mapper

Ask:

```text
For this task: [TASK]

Find all files that likely need to be created or modified:
- Source files, routes, services, UI components, jobs, migrations, schemas, or config.
- Dependency registration, imports, feature flags, build/test configuration.
- Tests that need creation or updates.

For each file, report:
- Current purpose.
- Specific change needed.
- Dependencies on other files.
- Confidence level and reason.
```

### Risk And Edge Case Scout

Ask:

```text
Analyze risks and edge cases for implementing: [TASK]

Investigate:
- Functional edge cases and backwards compatibility.
- Shared state, concurrency, ordering, or data consistency risks.
- External service dependencies and API contracts.
- Database migrations or data model impacts.
- Feature flags, rollout, or operational concerns.
- Security, privacy, validation, and data exposure.
- Performance implications on hot paths.

Classify each risk as BLOCKING, IMPORTANT, or ADVISORY and include a concrete mitigation.
```

## Phase 2: Synthesize The Plan

Use the exploration results as source of truth. Do not guess when exact paths or symbols were found.

Required structure:

```markdown
# [Feature Name] Implementation Plan

**Goal:** [One sentence]

**Source Context:** [Jira ticket or requirement summary]

**Approach:** [2-3 sentences grounded in codebase findings]

## Codebase Context
[Architecture and pattern findings with exact paths and symbols.]

## Files To Create Or Modify
| Action | File | What Changes | Depends On |
|--------|------|--------------|------------|
| Modify | `path/to/file` | [specific change] | [dependency] |

## Risks And Mitigations
| Risk | Severity | Mitigation |
|------|----------|------------|
| [risk] | BLOCKING | [mitigation] |

## Implementation Steps
### Step N: [Description]
- **What:** [specific work]
- **Where:** [exact file paths and symbols when known]
- **Why:** [rationale]
- **Depends on:** [prior steps]
- **Verify:** [specific command or manual check]

## Testing And Verification
[Test cases, commands, and expected outcomes.]

## Rollback Strategy
[Safe revert, config rollback, data rollback, or deployment rollback.]
```

## Phase 3: Critique

Before presenting the plan, run a critique pass. Prefer a separate explorer/default agent when available; otherwise do a local self-review.

Critique prompt:

```text
You are a senior engineer reviewing this implementation plan. Find what is missing. Do not praise.

[INSERT FULL PLAN]

Check for:
- Missing steps that would leave an engineer stuck.
- Ordering errors.
- Untested code paths.
- Vague instructions without exact files or symbols.
- Risks identified but not addressed in implementation steps.
- Integration gaps between components.
- Missing verification steps.
- Incomplete rollback strategy.

For each issue, provide:
1. What is wrong.
2. Why it matters.
3. Suggested fix.
```

Incorporate valid critique before presenting the final plan. If critique finds structural gaps, fix the plan instead of listing the gaps as caveats.

## Phase 4: Present Or Execute

- If the user asked for a plan, present the critique-reviewed plan and stop. In Claude Code plan mode, submit it through `ExitPlanMode`.
- If the user explicitly asked to implement, execute the plan after synthesis and keep `update_plan` current.
- If the user asks to update Jira, ask for confirmation before comments, transitions, or ticket mutations.
- If Jira or codebase access fails, state exactly what was reachable and what remains blocked.

## Common Mistakes

- Do not write a plan before gathering ticket/source context.
- Do not use broad placeholders like "update config" when a real file path can be found.
- Do not skip critique for non-trivial changes.
- Do not mutate Jira or repository state during planning unless the user explicitly requested it.
- Do not expose secrets while proving Jira access.

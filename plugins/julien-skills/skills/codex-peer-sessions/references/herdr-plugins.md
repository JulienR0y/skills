# Optional Herdr companions

## Decision

Use these plugins as optional companions to `codex-peer-sessions`. Do not make
them required dependencies and do not install them without explicit user
approval.

The ranking prioritizes visible Codex peer-session problems: unrelated agents
mixed across spaces, ambiguous worker identity, poor pane layout, missed
blocked agents, weak fleet visibility, and review friction.

## Top 10

| Rank | Plugin | Use it for | Authority and limits |
|---:|---|---|---|
| 1 | [Space-Scoped Agents](https://github.com/ShankyJS/herdr-space-scoped-agents) | Show only the focused space's agents in the agent panel. | Changes the local Herdr agent view and persists the selected scope. It does not move panes or control agents. |
| 2 | [Agent Repo Header](https://github.com/khatriafaz/herdr-plugin-agent-repo) | Show the agent, repository, and Git branch in pane headers and sidebar metadata. | Reads local Herdr and Git metadata. It does not provide task summaries or recovery. |
| 3 | [Herdr Triage](https://github.com/natori-hrj/herdr-triage) | Rank blocked, done, working, and idle agents by operator attention. | Read-only. Its time-in-status starts when the plugin observes the state. |
| 4 | [drovr](https://github.com/AVGVSTVS96/herdr-drovr) | Move live panes or complete tabs without restarting their processes. | Mutates Herdr layout. Moves are verified but a multi-pane tab move is not atomic. Requires Node.js and `fzf`. |
| 5 | [Herdr Agent Board](https://github.com/MartinBspheroid/herdr-agent-dash) | Show agent state, activity, location, Git context, and stale or unknown evidence in one board. | Reads local state and uses Bun. Treat displayed evidence as status, not task completion proof. |
| 6 | [reviewr](https://github.com/persiyanov/herdr-reviewr) | Review worktree, last-turn, branch, or pull-request diffs beside an agent and send line comments back. | Pull-request views use an authenticated forge CLI. Sending comments writes agent input. |
| 7 | [Herdr File Viewer](https://github.com/smarzban/herdr-file-viewer) | Browse a Git-aware read-only tree, diffs, rendered Markdown, and source beside a worker. | Read-only by design and explicitly supports Linux and WSL. Optional renderers add local dependencies. |
| 8 | [strays](https://github.com/aleslanger/herdr-strays) | Review changed files and branch diffs across repositories and worktrees. | Git inspection is read-only. Agent handoff sends selected evidence as agent input. |
| 9 | [Sessionizer](https://github.com/andrewchng/herdr-sessionizer) | Open projects and worktrees with deterministic workspace, tab, and pane layouts. | Creates or focuses workspaces and can run configured layout commands. Review every template before use. |
| 10 | [Switchboard](https://github.com/crafts69guy/herdr-switchboard) | Search agents, workspaces, repositories, worktrees, commands, ports, and Git views from one palette. | Broadest authority in this list: optional actions can run commands, signal processes, clone repositories, stage or commit, and update the plugin. Expose only the required mode. |

## Selection rules

- For unrelated agents mixed across spaces, suggest Space-Scoped Agents.
- For ambiguous worker labels, suggest Agent Repo Header. Keep explicit
  responsibility names from `spawn-fleet.py`; metadata is supplementary.
- For an unusable live layout, fix `spawn-fleet.py` first. Suggest drovr for
  deliberate operator moves, not as a workaround for a launcher defect.
- For missed blocked workers, suggest Herdr Triage. Suggest Herdr Agent Board
  when the operator also needs Git and evidence context.
- For review, choose one primary surface. Use reviewr for line comments, Herdr
  File Viewer for read-only browsing, or strays for cross-worktree changes.
- For repeatable project layouts, suggest Sessionizer. Do not run an unreviewed
  layout command.
- Suggest Switchboard only when the operator wants a broad command palette and
  accepts its larger command and repository authority.

## Evidence boundary

The catalog was selected on 2026-08-12 from a complete metadata review of 599
non-fork, non-archived GitHub repositories carrying the self-declared
`herdr-plugin` topic. Six independent batches produced one disposition per
repository with no missing, extra, or duplicate rows. The coordinator then
checked the current README and `herdr-plugin.toml` for every finalist.

The Herdr marketplace is not a reviewed catalog. No finalist above was
installed or executed during the catalog review. Before installation, recheck
the current manifest, platform support, release provenance, license, build
steps, event hooks, external network use, and command authority. Use an
isolated pilot and verify the live behavior before recommending broader use.

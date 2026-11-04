# Julien Roy's skills

Skills and hooks for coding agents. They install as plugins in Claude Code, Codex and GitHub Copilot, and as plain
skills in any agent that reads `SKILL.md` files.

## What's in it

| Plugin | What it gives the agent |
|---|---|
| `julien-skills` | Nine skills: see the table below. |
| `clean-code-guard` | A hook that checks each Python file the agent edits for Clean Code, SOLID and DRY problems the edit added, plus a skill with the rules. See [its README](plugins/clean-code-guard/README.md). |
| `jev-skill-suggestion` | TypeSafe's Jev picks at most one skill per prompt and the skill list stays out of the context window. Claude Code and VS Code Copilot only. See [its README](plugins/jev-skill-suggestion/README.md). |

Skills in `julien-skills`:

| Skill | Use it to |
|---|---|
| `adversarial-review` | Review a change through three lenses (silent failures, test gaps, what input breaks it), verify each finding against the code, and sort them into will fix, skipped and dismissed. |
| `atomic-commits` | Split a working tree into small commits with clear messages. |
| `codex-peer-sessions` | Run and message Codex sessions next to the current one. |
| `peer-sessions` | Run and message other Claude Code sessions on the same machine. |
| `resolving-merge-conflicts` | Resolve a merge or rebase in progress. |
| `teams-reader` | Read Microsoft Teams chats through the signed-in web app. Needs Node.js and Chrome. |
| `ultraplan-local` | Write a deep implementation plan from parallel codebase analysis. |
| `vscode-extension-test` | Test a VS Code extension in your own VS Code: install a build, run its commands, answer its dialogs, and check what the window shows. Windows only. |
| `vscode-unblock` | Find and press the hidden VS Code dialog that blocks an agent. Windows only. |

## Install

Use one method per agent. Installing the same skills twice in one agent gives you every skill twice.

### Claude Code (CLI, desktop app, VS Code extension)

```
/plugin install julien-skills --marketplace JulienR0y/skills
/plugin install clean-code-guard --marketplace JulienR0y/skills
/plugin install jev-skill-suggestion --marketplace JulienR0y/skills
```

Install only the plugins you want. This one-step form needs Claude Code 2.1.275 or later. On an older version, run
`/plugin marketplace add JulienR0y/skills` first, then `/plugin install <plugin>@julienr0y`. Start a new session
afterwards, because hooks load when a session starts.

### Codex

```
codex plugin marketplace add JulienR0y/skills
codex plugin add julien-skills@julienr0y
codex plugin add clean-code-guard@julienr0y
```

Codex asks you to approve a plugin's hook before it runs it. `jev-skill-suggestion` does not work in Codex.

### GitHub Copilot CLI

```
copilot plugin marketplace add JulienR0y/skills
copilot plugin install julien-skills@julienr0y
copilot plugin install clean-code-guard@julienr0y
```

### VS Code with GitHub Copilot

Run **Chat: Install Plugin From Source** and enter `https://github.com/JulienR0y/skills`.

For `jev-skill-suggestion` in Copilot, run this from a clone of the repository:

```bash
node plugins/jev-skill-suggestion/copilot/install.mjs
```

Reload VS Code afterwards. Run it again after each update.

### Any other agent

```bash
npx skills@latest add JulienR0y/skills -a <agent>
```

This copies the skills only. Hooks are not installed this way, so `clean-code-guard` gives the rules but does not
check edits.

## API keys

No API key ships with this repository. Two features call TypeSafe's API, and each user brings their own key from
https://typesafe.ai:

| Feature | Where the key goes |
|---|---|
| `jev-skill-suggestion` in Claude Code | The plugin's `typesafeApiKey` setting, which Claude Code asks for at install and stores as sensitive. |
| `jev-skill-suggestion` in VS Code Copilot | The `TYPESAFE_API_KEY` environment variable. |
| `clean-code-guard` Jev layer (off by default) | The `TYPESAFE_API_KEY` environment variable, plus `CLEAN_CODE_JEV=1` to turn it on. |

Both features send text to TypeSafe: `jev-skill-suggestion` sends your prompt and skill descriptions, and the
`clean-code-guard` Jev layer sends the source of functions you change. Check that you are allowed to send that before
you add a key. Never commit a key.

## Credits

Some skills started in other people's repositories, all under the MIT license. Each keeps its license file.

| Skill | Original author | Changes here |
|---|---|---|
| `peer-sessions`, `codex-peer-sessions` | Ray Amjad | Adapted for this setup |
| `jev-skill-suggestion` | Daniel (San) Ávila, [davila7/claude-code-templates](https://github.com/davila7/claude-code-templates) | A VS Code Copilot port |

## Checks

```bash
python3 plugins/clean-code-guard/scripts/code_smells.py --self-test
claude plugin validate .
```

# demo-video

demo-video lets a coding agent film a polished demo of real software. The agent plans a storyboard. It records the
screen while an operator agent clicks through a real run. Then it edits the take into an MP4 with eased zooms,
callouts, step captions, a smooth pointer, time-lapses with an elapsed-time counter, title cards and blurs, plus
stills and notes.

Ask for it in plain words, for example "make a 60-second demo video of the export feature for the release deck".

## What you need

- Python 3.10 or later and [uv](https://docs.astral.sh/uv/). On first use, uv fetches Pillow, NumPy and an ffmpeg
  binary through imageio-ffmpeg; nothing is installed globally.
- An agent that can act on the screen. In Claude Code: computer use for desktop apps, Claude in Chrome or
  Playwright MCP for web apps. In GitHub Copilot: Playwright MCP for web apps (see below); desktop apps need a
  desktop-automation MCP server, which is untested.
- Windows for recording, which is tested. macOS (avfoundation) and Linux (x11grab) recording is written but untested;
  install `pynput` there for the cursor log. Editing works everywhere.

## Files

| File | What it does |
|---|---|
| `skills/demo-video/SKILL.md` | The workflow: plan, stage, record, log, edit, review, deliver. |
| `skills/demo-video/references/edit-list.md` | The edit-list format the renderer reads. |
| `skills/demo-video/references/operator-brief.md` | The brief template for the operator agent. |
| `skills/demo-video/references/pitfalls.md` | Problems seen in real shoots and their fixes. |
| `skills/demo-video/scripts/record.py` | Screen recorder with a cursor log, resilient to screen locks. |
| `skills/demo-video/scripts/mark.py` | Timeline marks during a take. |
| `skills/demo-video/scripts/frames.py` | Stills and contact sheets. |
| `skills/demo-video/scripts/deglow.py` | Removes an agent app's coloured edge glow from the footage. |
| `skills/demo-video/scripts/render.py` | Renders an edit list into the finished video. |
| `skills/demo-video/scripts/test_render.py` | Tests for the scripts. |

## Install

In Claude Code:

```
/plugin install demo-video --marketplace JulienR0y/skills
```

For other agents, see the [repository README](../../README.md).

## Use it in GitHub Copilot

Install the plugin:

- Copilot CLI: `copilot plugin marketplace add JulienR0y/skills`, then `copilot plugin install demo-video@julienr0y`.
- VS Code: run **Chat: Install Plugin From Source** and enter `https://github.com/JulienR0y/skills`.

Copilot has no built-in screen control, so add Playwright MCP for web-app demos.

Copilot CLI, in `~/.copilot/mcp-config.json`:

```json
{
  "mcpServers": {
    "playwright": { "type": "local", "command": "npx", "args": ["-y", "@playwright/mcp@0.0.84"], "tools": ["*"] }
  }
}
```

VS Code, in `.vscode/mcp.json` or your user MCP configuration:

```json
{
  "servers": {
    "playwright": { "command": "npx", "args": ["-y", "@playwright/mcp@0.0.84"] }
  }
}
```

Then ask in agent mode, for example "Make a 30-second demo video of the checkout flow at http://localhost:3000".

Tested with Copilot CLI 1.0.105 and Playwright MCP 0.0.84 on Windows: Copilot picked the skill from a plain request
and delivered a 29-second web-app demo. The VS Code setup above uses the same server but has not been run yet.

## Check it

```bash
uv run --no-project --with pillow --with numpy --with imageio-ffmpeg --with pytest python -m pytest plugins/demo-video/skills/demo-video/scripts
```

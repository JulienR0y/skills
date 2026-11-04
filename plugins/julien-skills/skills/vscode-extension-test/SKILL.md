---
name: vscode-extension-test
description: Test a VS Code extension end to end in the user's own VS Code on Windows, the way a user would - install a build, open a folder, run its commands, answer its dialogs, and judge the result from what the window shows. Sees one window through screenshots and Windows UI Automation and drives it through the Command Palette, keys and named controls, without taking over the screen except where a step must type. Use it when asked to try, test, verify, check or reproduce an extension's behavior on this machine, to check a release before or after shipping, or when a test needs "computer use" of VS Code. Windows only.
---

# Test a VS Code extension in the user's VS Code

This skill tests an extension in the user's real VS Code, with their sign-in, settings and folders, so a slip
touches their work. Every test opens its own window, changes only what its plan names, and puts everything back.

The scripts are in `scripts/` in this skill's folder and need PowerShell 7 (`pwsh -NoProfile -NonInteractive -File`).
Dialogs are handled by the `vscode-unblock` skill's `vscode-windows.ps1`.

| Tool | What it does | Takes focus |
|---|---|---|
| `shot.ps1 -Window <folder> -Out <png> [-Width 1600]` | Takes a screenshot of one VS Code window, even when other windows cover it. View the PNG to see it. `-List` lists windows. | No |
| `ui.ps1 -Window <folder> -List [-Filter <text>]` | Lists the named controls the window shows: buttons, links, tree items, tabs. | No |
| `ui.ps1 -Window <folder> -Press <exact name> [-Index n]` | Presses a control through its own action. `-AllowMouse` clicks a control that has none. | No (mouse: yes) |
| `ui.ps1 -Window <folder> -Command '<palette title>'` | Runs a Command Palette command: F1, the title, Enter. | Yes |
| `ui.ps1 -Window <folder> -Keys <SendKeys> \| -Type <text>` | Sends keys (`^+p`, `{ENTER}`, `{ESC}`) or types literal text. | Yes |
| `ui.ps1 -Window <folder> -Close` | Closes the window, as its close button does. | No |
| `vscode-windows.ps1` (vscode-unblock) | Shows the text and buttons of every dialog. `-Dialog <text> -Press <button>` answers one. | No |
| `logs.ps1 -Match <channel or extension id> [-Minutes 30] [-Tail 40]` | Prints the end of each matching Output channel written recently. | No |

`-Window` is the folder name as the window title shows it: for "Welcome - my-project - Visual Studio Code" it is
`my-project`. A name that matches no window, or more than one, fails and lists the open titles.

If the extension's repository has its own test driver (for example a helper extension that sends chat messages), use
that for what it covers, and these tools for everything else.

## Ground rules

- **Ask the user first** before you do any of these:
  - install or replace an extension build;
  - change environment variables, a `.env`, settings or other files in their folders;
  - confirm something the plan did not name;
  - act outside the machine (push, comment, start a remote job);
  - close or reload a window you did not open.
- **Say before you take focus.** `-Command`, `-Keys`, `-Type` and mouse clicks bring the window to the front and type
  into it. Tell the user just before, and keep these steps short. Typing stops when the window loses focus.
- **Read before you confirm.** Never press a button that sets up, installs, deletes or overwrites unless the plan says
  so. To back out of a dialog, press `Cancel`.
- **No secrets or personal data in output.** Do not print `.env` values, tokens or personal data. Say whether a
  value is set, or whether a path exists, instead.
- **Put everything back.** Back up any file before you change it, restore it from the backup and check the hash.
  Close the windows you opened, and say which build is installed when you finish.

## Workflow

1. **Plan.** Write down:
   - the behavior under test, the build and the folder;
   - the steps, and what you expect each one to show;
   - what you will change and how you will restore it.

   Get the user's agreement for anything the ground rules list.
2. **Preflight.** `shot.ps1 -List` shows the open windows; they belong to the user. Run `git status` on the folder so
   you can tell your changes from theirs. A window already open on your folder keeps its old environment, and
   `code -n` only brings it forward, so use another folder or ask the user to close it.
3. **Install the build**, if the test needs one. Run `code --install-extension <vsix> --force`, then confirm the
   version with `code --list-extensions --show-versions`. The install applies to every window; open windows pick it
   up when they reload.
4. **Open your window** with `code -n <folder>`. A window opened this way gets the environment of the shell that ran
   `code`, even when VS Code is already running. So to test environment variables, set or clear them in that shell
   rather than in the user's settings. The window takes 10 to 20 seconds to load its extensions.
5. **Drive it.** Use `ui.ps1 -Command` for commands, `ui.ps1 -Press` for buttons and links, and the project's own
   driver for anything it covers.
6. **Observe** with these tools:
   - `vscode-windows.ps1` prints each dialog's full text;
   - `shot.ps1`, then view the PNG, shows what the window displays;
   - `ui.ps1 -List` lists the controls;
   - `logs.ps1` shows what the extension logged.
7. **Judge** each expectation against what you observed, quoting the text or screenshot. If a step showed nothing,
   look for the cause before concluding: a hidden dialog, a picker waiting for input, or a menu left open.
8. **Restore** what step 1 named and close your windows. Check the result with `git status` and `shot.ps1 -List`.
9. **Report** in the format below.

## Report

```
Tested: <behavior>, build <version>, folder <name>, <date>.
Result: PASS | FAIL | BLOCKED - <one sentence>.
Steps:
1. <step> -> <what was observed, quoted> (expected <...>) PASS/FAIL
Evidence: <screenshots, quoted dialog text, log lines>
Not tested: <what this run did not cover, and why>
Restored: <files, windows>; installed build left: <version>.
```

Keep what you observed apart from what you inferred. "The report showed `TOOL_HOME: <path>`" is observed. "So the
build step will find the tool" stays inferred until a run of that step shows it.

## Gotchas

- **The first UI Automation query of a window returns only its frame.** Chromium builds the page's accessibility
  tree only when a client first asks. `ui.ps1` asks again; any raw query should too.
- **A native dialog is a separate window.** It is not in the main window's screenshot or `-List` output, and keys
  sent to the window do not reach it. `vscode-windows.ps1` reads it, and presses its buttons even when they are
  command links (a `CCPushButton` pane with no Invoke action).
- **A stray Alt opens the menu bar.** If a screenshot shows a menu open, send `{ESC}` before the next step.
- **Quick picks and notifications are not dialogs.** A step that seems stuck is often waiting on a picker, so take a
  screenshot.
- **The palette title must match.** `-Command` runs the palette's first match, so a wrong title can run another
  command. Check what appeared.
- **Run commands from PowerShell, not Git Bash.** Git Bash rewrites an argument that starts with `/` into a path.
- **Several windows share one `Code.exe` process,** so process ids do not tell windows apart; their titles do.
- **Insiders writes logs elsewhere.** Pass `-LogRoot "$env:APPDATA\Code - Insiders\logs"` to `logs.ps1`.

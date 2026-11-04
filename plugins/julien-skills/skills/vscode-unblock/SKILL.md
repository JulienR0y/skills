---
name: vscode-unblock
description: Find and clear what blocks VS Code on Windows when an agent's command to it seems to do nothing - a reload that never happens, an extension still on its old version after an install, a `code -n` window that never appears to a driver, or a chat-driver call that hangs or returns 409. Reads VS Code's dialogs and their buttons through Windows UI Automation, with no screenshots, and presses one named button. Use it before asking the user to restart VS Code or look at their screen.
---

# Unblock VS Code without screenshots

VS Code on Windows runs as one `Code.exe` process with several windows. When a command to VS Code "succeeds" but
nothing changes, a window is usually waiting on a dialog nobody can see. `scripts/vscode-windows.ps1` in this skill's
folder lists every VS Code window and, under each, any dialog with its text and buttons. It reads native message boxes
and VS Code's own in-page dialogs through UI Automation, so it needs no screenshot and does not take over the user's
screen. It needs PowerShell 7 (`pwsh`).

## Look

```powershell
pwsh -NoProfile -NonInteractive -File <this skill's folder>/scripts/vscode-windows.ps1
```

A full scan takes about a minute, because it walks each window's accessibility tree. Each `window` line has the
title, and each `dialog` block shows the text and the `buttons:` list.

## Decide, then press

Pressing a button acts in the user's VS Code, so first find out what the button ends.

- **"A session is in progress. Are you sure you want to reload the window?"** A chat session in that window is still
  open, and VS Code holds every reload until someone answers. Read that chat first. If its last turn has ended (a final
  answer, "Done", or a failure) and no other session said it is using that window, `Yes` loses nothing: the session's
  history reopens. If a turn is still running or another session owns the window, ask that session or the user first.
- **Anything else:** `Cancel` or `Close Dialog` only backs out the action that raised it. A button that confirms
  something you did not start (terminate a process, discard changes, trust a folder) is the user's call.

```powershell
pwsh -NoProfile -NonInteractive -File <this skill's folder>/scripts/vscode-windows.ps1 -Dialog "A session is in progress" -Press Yes
```

`-Dialog` matches the dialog's title or text, and `-Press` is the exact button name from the scan. The script presses
one button on the first matching dialog and prints `pressed: <name>`. It exits 1 when nothing matches.

## After pressing

- A reloaded window takes some seconds to come back. A driver that tracks windows may not see it until then; check
  again before assuming it failed.
- A reload queued twice asks twice. Scan again after the first press.
- A new `code -n` window can take a minute or more to appear.

## Traps that look like a blocked window

- **Git Bash rewrites a leading `/`.** An argument such as `"/approvals autopilot"` sent from Git Bash arrives as
  `C:/.../Git/approvals autopilot`. A chat command sent that way can leave VS Code waiting on a picker. Send chat
  commands from PowerShell.
- **A quick pick or notification is not a dialog.** The scan does not show it. A command stuck with no dialog is
  usually waiting on a picker.

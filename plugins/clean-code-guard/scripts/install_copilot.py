"""Install the clean-code-guard check as a user-level VS Code Copilot hook.

Copies the checker to ~/.copilot/hooks/clean-code-guard/
(Copilot cannot see Claude's plugin folder, whose path changes on every update)
and writes ~/.copilot/hooks/clean-code-guard.json pointing at this Python.
If ~/.copilot/hooks/tool-dispatch.json exists, that dispatcher already runs the checker:
only the scripts are copied, and clean-code-guard.json is removed.
Re-run it after updating the plugin. Reload VS Code afterwards.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path(os.environ.get("COPILOT_HOME", Path.home() / ".copilot"))


def main() -> int:
    target = HOME / "hooks" / "clean-code-guard"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("code_smells.py", "smell_rules.py", "jev_review.py", "jev_calibration.json"):
        shutil.copy2(HERE / name, target / name)
    (target / "code_smells_copilot.py").unlink(missing_ok=True)  # the adapter older versions installed
    hook_file = HOME / "hooks" / "clean-code-guard.json"
    if (HOME / "hooks" / "tool-dispatch.json").exists():
        hook_file.unlink(missing_ok=True)  # tool-dispatch steps aside for any check registered on its own
        print(f"Scripts:   {target}\ntool-dispatch runs the checker, so no separate hook is registered.")
        return 0
    config = {"version": 1, "hooks": {"postToolUse": [{
        "type": "command", "exec": sys.executable,
        "args": [str(target / "code_smells.py"), "--hook"], "timeoutSec": 60,
    }]}}
    hook_file.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"Installed: {hook_file}\nScripts:   {target}\nReload VS Code to load the hook.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

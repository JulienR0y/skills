#!/usr/bin/env python3
"""Small stdlib-only check for fleet metadata behavior."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fleet_state import herdr_target, load_fleet, save_fleet


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        old_home = os.environ.get("CODEX_HOME")
        os.environ["CODEX_HOME"] = directory
        try:
            path = Path(directory) / "peer-sessions" / "check.json"
            payload = {
                "fleet_id": "check",
                "workers": [{"name": "reviewer", "thread_id": "thread-1"}],
            }
            save_fleet("check", payload)
            loaded, loaded_path = load_fleet("check")
            assert loaded == payload
            assert loaded_path == path
            assert json.loads(path.read_text())["workers"][0]["name"] == "reviewer"
            assert herdr_target({"name": "reviewer", "pane_id": "w1:p2"}) == "w1:p2"
            assert herdr_target({"name": "reviewer"}) == "reviewer"
        finally:
            if old_home is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = old_home
    print("codex-peer-sessions self-check: OK")


if __name__ == "__main__":
    main()

"""The recorder's side files next to a take (standard library only, so mark.py runs with plain Python)."""
from pathlib import Path


def start_time(video):
    """Wall-clock time (unix seconds) when the recorder started this take, from <video>.start.txt, or None."""
    path = Path(f"{video}.start.txt")
    return int(path.read_text().strip()) / 1000 if path.exists() else None

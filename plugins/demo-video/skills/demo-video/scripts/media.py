"""Shared video helpers: the ffmpeg binary, a video's frame size and length, and one decoded frame."""
import re
import subprocess
from functools import lru_cache

import imageio_ffmpeg
import numpy as np

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()  # set IMAGEIO_FFMPEG_EXE to use another ffmpeg


@lru_cache(maxsize=None)
def stream_info(video):
    """ffmpeg's description of the file (its stderr for `ffmpeg -i`)."""
    return subprocess.run([FFMPEG, "-hide_banner", "-i", str(video)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stderr


def probe_size(video):
    """(width, height) of the video's first video stream."""
    match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", stream_info(video))
    if not match:
        raise ValueError(f"{video}: no video stream found")
    return int(match.group(1)), int(match.group(2))


def duration(video):
    """Length in seconds."""
    match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", stream_info(video))
    if not match:
        raise ValueError(f"{video}: no duration found")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def grab(video, t):
    """The frame at `t` seconds as an HxWx3 uint8 array."""
    w, h = probe_size(video)
    raw = subprocess.run([FFMPEG, "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    if len(raw) < w * h * 3:
        raise ValueError(f"{video}: no frame at {t:.2f} s")
    return np.frombuffer(raw[:w * h * 3], np.uint8).reshape(h, w, 3)

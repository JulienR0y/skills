"""Records the screen for post-production: a window or a rectangle, full quality, with the real mouse pointer left
out, plus a cursor log so render.py can draw a smooth pointer afterwards.

usage: uv run --no-project --with pillow --with numpy --with imageio-ffmpeg python record.py --out take.mp4
           [--window "<text in the window title>" [--pad 40] | --rect X,Y,W,H] [--fps 30] [--stop-file take.stop]
       python record.py --list            # visible windows: x, y, width, height and title (Windows)

Writes take.mp4, take.mp4.start.txt (unix ms when capture started) and take.mp4.cursor.csv (ms since start, x, y,
left button; x and y relative to the recorded area). Stops when the stop file exists or on Ctrl+C. When capture
drops (Windows: the screen locked), it waits until the screen can be captured again and continues in a new
segment, take-002.mp4, with its own start and cursor files.

It records a screen area, so whatever is in front of the window is filmed too. With --window it prints a line
whenever another window covers the target, and when the target is clear again, with the time in the take.
--pad adds a margin around the window, for menus and flyouts that open past its edges.

Windows is tested. macOS (avfoundation) and Linux (x11grab) capture is best effort: pass --rect in screen pixels,
and install pynput for the cursor log (uv run --with pynput).
"""
import argparse
import ctypes
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from subprocess import PIPE, Popen, run

from media import FFMPEG

try:
    from pynput import mouse as pynput_mouse
except ImportError:
    pynput_mouse = None

WINDOWS = sys.platform == "win32"
if WINDOWS:
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # physical pixels, as gdigrab captures
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.restype = wintypes.HWND


@dataclass(frozen=True)
class Target:
    """The screen area to record, and the window in it when one was named."""
    area: tuple  # x, y, w, h
    handle: int = None


# ---------------------------------------------------------------- windows (Windows only)
def window_title(handle):
    length = user32.GetWindowTextLengthW(handle)
    text = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(handle, text, length + 1)
    return text.value


def is_cloaked(handle):
    """True for windows DWM keeps hidden though they report visible (the shadow copies of Store apps)."""
    cloaked = ctypes.c_int(0)
    ctypes.windll.dwmapi.DwmGetWindowAttribute(handle, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return cloaked.value != 0


def visible_windows():
    """[(handle, title)] of the titled top-level windows actually on screen: visible, not minimised, not cloaked."""
    found = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def collect(handle, _):
        if user32.IsWindowVisible(handle) and not user32.IsIconic(handle) and not is_cloaked(handle):
            title = window_title(handle)
            if title:
                found.append((handle, title))
        return True

    user32.EnumWindows(proc(collect), 0)
    return found


def window_rect(handle):
    """(x, y, w, h) of the window as drawn, without its invisible resize border."""
    r = wintypes.RECT()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(handle, 9, ctypes.byref(r), ctypes.sizeof(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def find_window(text):
    """The frontmost window whose title contains `text` (EnumWindows lists windows front to back)."""
    matches = [(h, t) for h, t in visible_windows() if text.lower() in t.lower()]
    if not matches:
        rows = "\n  ".join(f"{window_rect(h)}  {t}" for h, t in visible_windows())
        raise SystemExit(f"no window title contains '{text}'. Windows on screen:\n  {rows}")
    handle, title = matches[0]
    note = f" (frontmost of {len(matches)} matches; close the others or bring this one to the front)" if len(matches) > 1 else ""
    print(f"window: {title} at {window_rect(handle)}{note}", flush=True)
    return handle


def padded(area, pad):
    """The area grown by `pad` pixels on each side, kept on the desktop."""
    x, y, w, h = area
    vx, vy, vw, vh = (user32.GetSystemMetrics(i) for i in (76, 77, 78, 79))
    x0, y0 = max(x - pad, vx), max(y - pad, vy)
    x1, y1 = min(x + w + pad, vx + vw), min(y + h + pad, vy + vh)
    return x0, y0, x1 - x0, y1 - y0


def capture_target(args):
    """What to record, with even sizes (H.264 needs them)."""
    handle = None
    if args.window:
        if not WINDOWS:
            raise SystemExit("--window works on Windows only; pass --rect X,Y,W,H")
        handle = find_window(args.window)
        area = padded(window_rect(handle), args.pad)
    elif args.rect:
        area = tuple(int(v) for v in args.rect.split(","))
    elif WINDOWS:
        area = (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    else:
        raise SystemExit("pass --rect X,Y,W,H (the screen area in pixels)")
    x, y, w, h = area
    return Target((x, y, w - w % 2, h - h % 2), handle)


class CoverWatch:
    """Prints when another window comes in front of the target window, and when it is clear again."""

    SPOTS = [(0.5, 0.5), (0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)]

    def __init__(self, handle, started):
        self.handle, self.started, self.cover = handle, started, None

    def covering(self):
        """Title of a window in front of the target at one of the SPOTS, or None."""
        x, y, w, h = window_rect(self.handle)
        for fx, fy in self.SPOTS:
            top = user32.GetAncestor(user32.WindowFromPoint(wintypes.POINT(int(x + w * fx), int(y + h * fy))), 2)
            if top and top != self.handle:
                return window_title(top) or "an untitled window"
        return None

    def check(self):
        if self.handle is None:
            return
        cover = self.covering()
        if cover != self.cover:
            note = f"COVERED by '{cover}'" if cover else "target clear again"
            print(f"{time.monotonic() - self.started:7.1f} s  {note}", flush=True)
            self.cover = cover


# ---------------------------------------------------------------- ffmpeg
def input_args(area, fps):
    x, y, w, h = area
    if WINDOWS:
        return ["-f", "gdigrab", "-draw_mouse", "0", "-framerate", str(fps), "-offset_x", str(x), "-offset_y", str(y),
                "-video_size", f"{w}x{h}", "-i", "desktop"]
    if sys.platform == "darwin":  # screen device "1" is usually "Capture screen 0"; list with -list_devices
        return ["-f", "avfoundation", "-capture_cursor", "0", "-framerate", str(fps), "-i", "1:none",
                "-vf", f"crop={w}:{h}:{x}:{y}"]
    return ["-f", "x11grab", "-draw_mouse", "0", "-framerate", str(fps), "-video_size", f"{w}x{h}",
            "-i", f":0.0+{x},{y}"]


def can_capture(area, fps):
    """True when one frame of the area can be captured now (a locked Windows desktop refuses it)."""
    return run([FFMPEG, "-v", "quiet", *input_args(area, fps), "-frames:v", "1", "-f", "null", "-"]).returncode == 0


# ---------------------------------------------------------------- cursor
def pointer():
    """(x, y, left button down) on screen, or None where it cannot be read."""
    if WINDOWS:
        p = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(p))
        # 0x8000: down now; 0x0001: pressed since the last poll (synthetic clicks go down and up within one poll)
        return p.x, p.y, int(bool(user32.GetAsyncKeyState(0x01) & 0x8001))
    return PynputPointer.read()


class PynputPointer:
    """Pointer state from pynput (macOS and Linux), when it is installed."""
    state = None

    @classmethod
    def read(cls):
        if pynput_mouse is None:
            return None
        if cls.state is None:
            cls.state = [0, 0, 0]
            pynput_mouse.Listener(on_click=lambda x, y, b, down: cls.state.__setitem__(2, int(down))).start()
        x, y = pynput_mouse.Controller().position
        return int(x), int(y), cls.state[2]


class CursorLog(threading.Thread):
    """Writes a line whenever the pointer moves or the left button changes, until stopped."""

    def __init__(self, path, origin, started):
        super().__init__(daemon=True)
        self.path, self.origin, self.started = path, origin, started
        self.stopped = threading.Event()

    def run(self):
        last = None
        with open(self.path, "w", encoding="utf-8", newline="\n") as log:
            log.write("ms,x,y,down\n")
            while not self.stopped.is_set():
                now = pointer()
                if now is None:
                    return
                if now != last:
                    ms = int((time.monotonic() - self.started) * 1000)
                    log.write(f"{ms},{now[0] - self.origin[0]},{now[1] - self.origin[1]},{now[2]}\n")
                    log.flush()
                    last = now
                time.sleep(0.004)


# ---------------------------------------------------------------- takes
def segment_path(out, n):
    out = Path(out)
    return out if n == 1 else out.with_name(f"{out.stem}-{n:03d}{out.suffix}")


def start_capture(out, area, fps, log):
    """ffmpeg recording `area` into `out` at full quality; its errors go to the open file `log`."""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", *input_args(area, fps), "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-y", str(out)]
    return Popen(cmd, stdin=PIPE, stderr=log)


def wait_for_stop(proc, stop_file, watch):
    """Returns when the stop file exists, ffmpeg exits, or Ctrl+C (which creates the stop file)."""
    try:
        while proc.poll() is None and not stop_file.exists():
            watch.check()
            time.sleep(0.25)
    except KeyboardInterrupt:
        stop_file.touch()


def finish_capture(proc):
    """Lets ffmpeg finish the file cleanly ('q' on its input) if it is still running."""
    if proc.poll() is None:
        proc.communicate(b"q", timeout=60)


def record_segment(out, target, fps, stop_file):
    """Records until the stop file exists (returns True) or capture fails (returns False)."""
    x, y, w, h = target.area
    log_path = Path(f"{out}.ffmpeg.log")
    with open(log_path, "w", encoding="utf-8") as log:
        proc = start_capture(out, target.area, fps, log)
        Path(f"{out}.start.txt").write_text(str(int(time.time() * 1000)))
        started = time.monotonic()
        cursor = CursorLog(f"{out}.cursor.csv", (x, y), started)
        cursor.start()
        print(f"recording {w}x{h} at {x},{y} to {out}; create {stop_file} to stop", flush=True)
        wait_for_stop(proc, stop_file, CoverWatch(target.handle, started))
        cursor.stopped.set()
        finish_capture(proc)
    if log_path.stat().st_size == 0:
        log_path.unlink()
    print(f"recorded {out} (ffmpeg exit {proc.returncode})", flush=True)
    return stop_file.exists()


def record(out, target, fps, stop_file):
    stop_file.unlink(missing_ok=True)
    n = 1
    while not record_segment(segment_path(out, n), target, fps, stop_file):
        print("capture dropped; waiting until the screen can be captured again", flush=True)
        while not stop_file.exists() and not can_capture(target.area, fps):
            time.sleep(10)
        if stop_file.exists():
            break
        n += 1
    stop_file.unlink(missing_ok=True)
    print(f"stopped after {n} segment(s)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out")
    ap.add_argument("--window", help="text in the title of the window to record (Windows)")
    ap.add_argument("--pad", type=int, default=0, help="margin in pixels around --window")
    ap.add_argument("--rect", help="X,Y,W,H screen area in pixels")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--stop-file", help="default: <out>.stop")
    ap.add_argument("--list", action="store_true", help="list windows on screen and their bounds")
    args = ap.parse_args()
    if args.list:
        print("x, y, width, height  title")
        for handle, title in visible_windows():
            print(", ".join(str(v) for v in window_rect(handle)), " ", title)
        return
    if not args.out:
        ap.error("--out is required")
    if not WINDOWS and pynput_mouse is None:
        print("no cursor log: install pynput (uv run --with pynput) or render with no_cursor", flush=True)
    record(args.out, capture_target(args), args.fps, Path(args.stop_file or f"{args.out}.stop"))


if __name__ == "__main__":
    main()

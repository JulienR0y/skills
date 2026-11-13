"""Checks for the demo-video scripts: a full render of a generated clip through every edit-list feature, and the
pure helpers.

run: uv run --no-project --with pillow --with numpy --with imageio-ffmpeg --with pytest python -m pytest <this folder>
"""
import json
import subprocess
import time

import numpy as np

from deglow import Deglow, edge_strength, fit_alpha, fit_colour
from mark import locate, presses
from record import CoverWatch
from media import FFMPEG, duration, probe_size
from render import Cursor, Style, elapsed_text, load_edl, render_video


def make_take(folder, seconds=4, size="640x384"):
    """A generated test clip with the recorder's side files: start time and a cursor log with two clicks."""
    take = folder / "take.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}",
                    "-pix_fmt", "yuv420p", str(take)], check=True)
    (folder / "take.mp4.start.txt").write_text(str(int(time.time() * 1000)))
    rows = ["ms,x,y,down", "0,100,100,0", "900,400,250,0", "1000,400,250,1", "1100,400,250,0", "2500,120,300,1"]
    (folder / "take.mp4.cursor.csv").write_text("\n".join(rows) + "\n")
    return take


def edit_list(take):
    zero = int((take.parent / "take.mp4.start.txt").read_text()) / 1000
    return {
        "source": str(take), "out": [480, 288], "cursor_lag_s": 0.1,
        "shots": [
            {"in": 0.5, "out": 0.5, "dur": 1.0, "title": ["Title", "Subtitle"]},
            {"in": 0.5, "out": 2.0, "fade": 0.2, "caption": "1  Zoom in", "zoom": [[0, 0, 640, 384], [200, 100, 520, 292]],
             "spot": [300, 200, 500, 300], "callouts": [{"text": "A callout", "sub": "with a pointer", "box": [20, 180],
                                                         "to": [400, 250], "t": [0.1, 1.4]}]},
            {"in": 2.0, "out": 4.0, "dur": 0.5, "fade": 0.2, "caption": "2  Time-lapse", "caption_bottom": True,
             "counter": "{clock} in", "counter_zero": zero, "blur": [[10, 10, 110, 60]], "patch": [[300, 0, 340, 20]],
             "blur_track": [[2.0, 0, 300, 80, 340], [4.0, 200, 300, 280, 340]], "no_cursor": True},
        ],
    }


def test_render_writes_every_frame(tmp_path):
    take = make_take(tmp_path)
    edl_path = tmp_path / "edl.json"
    edl_path.write_text(json.dumps(edit_list(take)))
    out = tmp_path / "out.mp4"
    frames = render_video(load_edl(edl_path), out)
    assert frames == 30 + 45 + 15
    assert probe_size(out) == (480, 288)
    assert abs(duration(out) - 3.0) < 0.1


def test_cursor_glides_into_a_far_move_and_lands_on_time():
    c = Cursor([(0.0, 0, 0, 0), (1.0, 100, 0, 0), (2.0, 100, 0, 1)])
    assert c.at(-0.1) is None
    assert c.at(0.2) == (0, 0)
    assert 0 < c.at(0.8)[0] < 100
    assert c.at(1.0) == (100, 0)
    assert c.ripple(2.1) is not None and c.ripple(2.6) is None


def test_design_pixels_scale_with_the_output_area_and_keep_their_sign():
    style = Style(w=800, h=480, fps=30, accent=(0, 0, 0), ink=(0, 0, 0), regular=None, bold=None)
    assert style.px(-70) == -35
    assert style.px(48) == 24
    assert style.px(1) == 1
    portrait = Style(w=960, h=1600, fps=30, accent=(0, 0, 0), ink=(0, 0, 0), regular=None, bold=None)
    assert portrait.px(48) == 48


def test_elapsed_text_formats():
    assert elapsed_text("{min} min", 125.9) == "2 min"
    assert elapsed_text("{clock}", 65) == "1:05"
    assert elapsed_text("{sec}s", -3) == "0s"


def test_deglow_takes_a_known_glow_back_out(tmp_path):
    rng = np.random.default_rng(1)
    src = rng.integers(40, 220, (200, 300, 3)).astype(np.float32)
    shape = np.zeros((200, 300), np.float32)
    shape[:, :20] = shape[:, -20:] = 0.5
    colour = np.array([204, 104, 80], np.float32)
    obs = src * (1 - shape[..., None]) + colour * shape[..., None]
    assert np.allclose(fit_colour(obs, src), colour, atol=2)
    model = {"alpha": fit_alpha(obs, src, colour, 40), "colour": colour, "ref": edge_strength(obs)}
    np.savez(tmp_path / "glow.npz", **model)
    fixed = Deglow(tmp_path / "glow.npz")(obs).astype(np.float32)
    assert np.abs(fixed[:, 5:15] - src[:, 5:15]).mean() < 4


def test_clicks_are_read_from_button_presses_only():
    rows = [{"ms": "0", "x": "1", "y": "1", "down": "0"}, {"ms": "500", "x": "5", "y": "6", "down": "1"},
            {"ms": "520", "x": "6", "y": "6", "down": "1"}, {"ms": "600", "x": "6", "y": "6", "down": "0"},
            {"ms": "1500", "x": "9", "y": "9", "down": "1"}]
    assert presses(rows) == [(0.5, 5, 6), (1.5, 9, 9)]


def test_cover_watch_reports_each_change_once(capsys):
    watch = CoverWatch(handle=1, started=0.0)
    states = iter([None, "Chat", "Chat", None, None])
    watch.covering = lambda: next(states)
    for _ in range(5):
        watch.check()
    out = capsys.readouterr().out
    assert out.count("COVERED by 'Chat'") == 1
    assert out.count("target clear again") == 1


def test_marks_are_placed_in_the_take_that_was_running():
    starts = [(100.0, "a.mp4"), (200.0, "b.mp4")]
    assert locate(50.0, starts) == "before every take"
    assert locate(150.0, starts).startswith("a.mp4 @")
    assert locate(250.5, starts) == "b.mp4 @    50.5 s"

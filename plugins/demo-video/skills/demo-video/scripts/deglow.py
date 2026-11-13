"""Removes the coloured edge glow an agent app draws on screen while it acts (Claude's computer use, a browser
extension), so it does not end up in the video.

The glow is an overlay obs = src * (1 - a) + C * a with a fixed colour C, a fixed shape a(x, y) and a pulsing
strength. One frame pair with the same content, glowing and glow-free, gives C and the shape at a reference
strength; every frame is then corrected with its own strength, read from the red-minus-blue of its edges. The glow
usually vanishes for an instant whenever the agent takes a screenshot: those frames are the clean ones.

  python deglow.py scan  <take.mp4> [start] [seconds]               # edge strength over time: find a pair
  python deglow.py fit   <take.mp4> <t_glow> <t_clean> <model.npz>  # [--colour R,G,B] [--everywhere]
  python deglow.py check <take.mp4> <model.npz> <t> <out.png>       # before | after, side by side
--colour gives the glow colour when the edges are too uniform to fit it (Claude's is about 204,104,80).
--everywhere fits the whole frame, not only a band along the edges (a glow drawn inside a browser page).
"""
import argparse
import subprocess

import numpy as np
from PIL import Image

from media import FFMPEG, grab, probe_size

BAND = 140  # the glow lives within this many pixels of an edge


def edge_strength(frame):
    """Mean red minus blue in 3-pixel strips along the left and right edges, middle half of the height."""
    h = frame.shape[0]
    rows = slice(h // 4, 3 * h // 4)
    e = np.concatenate([frame[rows, :3].reshape(-1, 3), frame[rows, -3:].reshape(-1, 3)]).astype(np.float32)
    return float((e[:, 0] - e[:, 2]).mean())


def box_blur(a, r):
    """Mean over a (2r+1)^2 window, edges padded by reflection."""
    c = np.pad(np.pad(a, r, mode="reflect").cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    k = 2 * r + 1
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def fit_colour(obs, src):
    """Glow colour from the outermost columns, where a is nearly constant: d = a*C - a*src is linear in src."""
    rim = np.zeros(obs.shape[:2], bool)
    rim[:, :2] = rim[:, -2:] = True
    xs, ys = src[rim], (obs - src)[rim]
    slope = np.array([np.polyfit(xs[:, c], ys[:, c], 1) for c in range(3)])
    return slope[:, 1] / -slope[:, 0].mean()


def fit_alpha(obs, src, colour, band):
    """Per-pixel glow strength a = d / (C - src), weighted over channels, kept within `band` px of an edge
    (band None: everywhere, minus the faint values that are noise or content changes)."""
    gap = colour[None, None, :] - src
    a = ((obs - src) * gap).sum(2) / np.maximum((gap * gap).sum(2), 1.0)
    if band is not None:
        near = np.zeros(a.shape, bool)
        near[:, :band] = near[:, -band:] = near[:band, :] = near[-band:, :] = True
        a = np.where(near, a, 0.0)
    a = box_blur(np.clip(a, 0.0, 0.95), 4)  # the glow is a soft border; compression noise is not
    if band is None:
        a[a < 0.03] = 0.0
    return a


def fit(take, t_glow, t_clean, out, colour=None, band=BAND):
    obs, src = grab(take, t_glow).astype(np.float32), grab(take, t_clean).astype(np.float32)
    colour = np.array(colour, np.float32) if colour else fit_colour(obs, src)
    a = fit_alpha(obs, src, colour, band)
    np.savez_compressed(out, alpha=a.astype(np.float32), colour=colour.astype(np.float32), ref=edge_strength(obs))
    profile = [round(float(a[a.shape[0] // 2, k]), 3) for k in (0, 10, 30, 60, 100)]
    print(f"{out}: colour {colour.round(1)}, strength {edge_strength(obs):.1f}, alpha at 0/10/30/60/100 px: {profile}")


class Deglow:
    """Takes the fitted glow out of frames of the same size."""

    def __init__(self, path):
        m = np.load(path)
        self.alpha, self.colour, self.ref = m["alpha"], m["colour"], float(m["ref"])

    def __call__(self, frame):
        """frame: HxWx3 array; returns uint8 with the glow taken out (unchanged when no glow is on)."""
        f = frame.astype(np.float32)
        s = max(0.0, edge_strength(f) / self.ref)
        if s < 0.05:
            return frame.astype(np.uint8)
        a = np.clip(self.alpha * s, 0, 0.95)[..., None]
        return ((f - self.colour * a) / (1 - a)).clip(0, 255).astype(np.uint8)


def scan(take, start, length, fps=2):
    """Prints the edge strength every 1/fps s: high = glowing, near 0 = clean. Pick a close pair with the same
    content for `fit`."""
    w, h = probe_size(take)
    raw = subprocess.run([FFMPEG, "-v", "error", "-ss", str(start), "-i", str(take), "-t", str(length),
                          "-vf", f"fps={fps}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    frames = np.frombuffer(raw, np.uint8)[:len(raw) // (w * h * 3) * w * h * 3].reshape(-1, h, w, 3)
    for i, f in enumerate(frames):
        print(f"{start + i / fps:8.1f} s  {edge_strength(f):6.1f}")


def before_after(take, model, t, out):
    before = grab(take, t)
    after = Deglow(model)(before)
    both = Image.fromarray(np.concatenate([before, after], 1))
    both.thumbnail((2400, 2400))
    both.save(out)
    print(f"{out}: strength {edge_strength(before):.1f} -> {edge_strength(after):.1f}")


def run_fit(a):
    colour = [float(v) for v in a.colour.split(",")] if a.colour else None
    fit(a.take, a.t_glow, a.t_clean, a.model, colour, None if a.everywhere else BAND)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(required=True)
    p = sub.add_parser("scan", help="edge strength over time")
    p.add_argument("take")
    p.add_argument("start", type=float, nargs="?", default=0.0)
    p.add_argument("seconds", type=float, nargs="?", default=60.0)
    p.set_defaults(run=lambda a: scan(a.take, a.start, a.seconds))
    p = sub.add_parser("fit", help="build a glow model from a glowing and a clean frame")
    for name, kind in [("take", str), ("t_glow", float), ("t_clean", float), ("model", str)]:
        p.add_argument(name, type=kind)
    p.add_argument("--colour", help="R,G,B of the glow, when it cannot be fitted")
    p.add_argument("--everywhere", action="store_true", help="fit the whole frame, not only an edge band")
    p.set_defaults(run=run_fit)
    p = sub.add_parser("check", help="one frame before and after")
    for name, kind in [("take", str), ("model", str), ("t", float), ("out", str)]:
        p.add_argument(name, type=kind)
    p.set_defaults(run=lambda a: before_after(a.take, a.model, a.t, a.out))
    args = ap.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()

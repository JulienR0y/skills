"""Renders a product-style demo video from raw takes and an edit list (JSON): cuts, speed-ups and holds, eased
zooms, a spotlight, callout boxes, step captions, title cards, blurs, an elapsed-time counter and a smooth pointer
redrawn from the take's cursor log.

usage: uv run --no-project --with pillow --with numpy --with imageio-ffmpeg python render.py <edl.json> <out.mp4>
           [--only N]     # render shot N alone, to check it
The edit list format is in references/edit-list.md. An .mkv output is lossless RGB (a GIF source); .mp4 is the
delivery encode (H.264, yuv420p, faststart). It prints where each shot starts in the output, for stills and notes.
"""
import argparse
import bisect
import csv
import json
import math
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from deglow import Deglow
from media import FFMPEG, probe_size
from sidecar import start_time

FONTS = {
    "regular": ["C:/Windows/Fonts/segoeui.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "bold": ["C:/Windows/Fonts/segoeuib.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
}


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def lerp(a, b, t):
    return [p + (q - p) * t for p, q in zip(a, b)]


def fade_alpha(t, t0, t1, ramp=0.3):
    return min(ease((t - t0) / ramp), ease((t1 - t) / ramp)) if t0 <= t <= t1 else 0.0


def shot_duration(shot):
    return shot.get("dur", shot["out"] - shot["in"])


def first_font(kind, override):
    return override or next((p for p in FONTS[kind] if Path(p).exists()), None)


@lru_cache(maxsize=None)
def load_font(path, size):
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)


@dataclass(frozen=True)
class Style:
    """Output size and the look of every overlay; sizes are designed for 1600x960 and scale with the output's area,
    so a portrait or small frame gets overlays of the same weight."""
    w: int
    h: int
    fps: int
    accent: tuple
    ink: tuple
    regular: str
    bold: str

    def px(self, n):
        """n design pixels in output pixels: same sign, at least 1 in size."""
        scale = math.sqrt(self.w * self.h / (1600 * 960))
        return int(math.copysign(max(1, round(abs(n) * scale)), n))

    def regular_font(self, size):
        return load_font(self.regular, self.px(size))

    def bold_font(self, size):
        return load_font(self.bold, self.px(size))


# ---------------------------------------------------------------- cursor
class Cursor:
    """The logged pointer, with each jump turned into an eased glide that lands when the real pointer did."""

    GLIDE = 0.55

    def __init__(self, rows):
        """rows: (seconds, x, y, button down) in take time, in order."""
        self.moves, self.clicks = [], []
        for t, x, y, down in rows:
            if not self.moves or (x, y) != self.moves[-1][1:]:
                self.moves.append((t, x, y))
            if down and (not self.clicks or t - self.clicks[-1] > 0.15):
                self.clicks.append(t)
        self.times = [m[0] for m in self.moves]

    @classmethod
    def from_csv(cls, path, lag):
        """The recorder's cursor log, shifted `lag` seconds earlier (capture starts a little after the log)."""
        with open(path, encoding="utf-8") as f:
            return cls([(int(r["ms"]) / 1000 - lag, int(r["x"]), int(r["y"]), int(r["down"])) for r in csv.DictReader(f)])

    def at(self, s):
        """Pointer position at take time s, or None before the log starts."""
        i = bisect.bisect_right(self.times, s)
        if i == 0:
            return None
        prev = self.moves[i - 1]
        if i == len(self.moves):
            return prev[1:]
        nxt = self.moves[i]
        gap = nxt[0] - prev[0]
        glide = min(self.GLIDE, gap * 0.8)
        if math.dist(prev[1:], nxt[1:]) > 30 and gap > 0.3 and s > nxt[0] - glide:
            return tuple(lerp(prev[1:], nxt[1:], ease((s - (nxt[0] - glide)) / glide)))
        return prev[1:]

    def ripple(self, s):
        """Seconds since the latest click, if it was under 0.45 s ago."""
        past = [s - t for t in self.clicks if 0 <= s - t < 0.45]
        return min(past) if past else None


@lru_cache(maxsize=None)
def cursor_sprite(height):
    """A white arrow pointer with a dark outline and a soft shadow, drawn at 4x and reduced."""
    k, h = 4, height * 4
    pts = [(0, 0), (0, 0.78), (0.2, 0.62), (0.34, 0.95), (0.47, 0.9), (0.33, 0.58), (0.58, 0.58)]
    poly = [(2 * k + x * h * 0.62, 2 * k + y * h) for x, y in pts]
    img = Image.new("RGBA", (int(h * 0.62) + 8 * k, h + 8 * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(x + 2 * k, y + 3 * k) for x, y in poly], fill=(0, 0, 0, 70))
    d.polygon(poly, fill=(255, 255, 255, 255), outline=(20, 20, 20, 255), width=int(1.6 * k))
    return img.resize((img.width // k, img.height // k), Image.LANCZOS)


# ---------------------------------------------------------------- overlays
def rounded(layer, rect, radius, fill=None, outline=None, width=1):
    ImageDraw.Draw(layer).rounded_rectangle(rect, radius, fill=fill, outline=outline, width=width)


def draw_callout(layer, style, c, alpha, to_point=None):
    """A dark card with a bold title, an optional subtitle and an optional pointer line to `to_point`."""
    px, title, sub = style.px, c["text"], c.get("sub", "")
    d = ImageDraw.Draw(layer)
    ft, fs = style.bold_font(27), style.regular_font(21)
    w = int(max(d.textlength(title, font=ft), d.textlength(sub, font=fs) if sub else 0)) + px(48)
    h = px(62) + (px(32) if sub else 0)
    x, y = c["box"]
    a = int(255 * alpha)
    if to_point:
        tx, ty = to_point
        bx, by = min(max(tx, x + px(16)), x + w - px(16)), (y + h if ty > y + h else y)
        d.line([(bx, by), (tx, ty)], fill=style.accent + (a,), width=px(3))
        d.ellipse([tx - px(7), ty - px(7), tx + px(7), ty + px(7)], fill=style.accent + (a,), outline=(255, 255, 255, a))
    rounded(layer, [x + px(3), y + px(5), x + w + px(3), y + h + px(5)], px(14), fill=(0, 0, 0, int(90 * alpha)))
    rounded(layer, [x, y, x + w, y + h], px(14), fill=style.ink + (int(252 * alpha),))
    rounded(layer, [x, y, x + px(7), y + h], px(3), fill=style.accent + (a,))
    d.text((x + px(26), y + px(13)), title, font=ft, fill=(255, 255, 255, a))
    if sub:
        d.text((x + px(26), y + px(50)), sub, font=fs, fill=(196, 210, 230, a))


def draw_caption(layer, style, text, bottom):
    """The step caption: an accent pill at the top left (or bottom left)."""
    px, f = style.px, style.bold_font(22)
    d = ImageDraw.Draw(layer)
    w = int(d.textlength(text, font=f)) + px(40)
    x, y = px(28), (style.h - px(70) if bottom else px(24))
    rounded(layer, [x, y, x + w, y + px(44)], px(22), fill=style.accent + (235,))
    d.text((x + px(20), y + px(8)), text, font=f, fill=(255, 255, 255, 255))


def draw_title(layer, style, lines, alpha):
    """A title card: the frame under a dark veil, a big title and a subtitle, centred."""
    veil = Image.new("RGBA", (style.w, style.h), style.ink + (int(200 * alpha),))
    layer = Image.alpha_composite(veil, layer)
    d = ImageDraw.Draw(layer)
    rows = [(lines[0], style.bold_font(64), -70, (255, 255, 255))]
    if len(lines) > 1:
        rows.append((lines[1], style.regular_font(32), 20, (190, 205, 228)))
    for text, f, dy, col in rows:
        d.text(((style.w - d.textlength(text, font=f)) / 2, style.h / 2 + style.px(dy)), text, font=f,
               fill=col + (int(255 * alpha),))
    return layer


def elapsed_text(fmt, seconds):
    """Formats a counter: {min} whole minutes, {sec} whole seconds, {clock} m:ss."""
    s = max(0, int(seconds))
    return fmt.format(min=s // 60, sec=s, clock=f"{s // 60}:{s % 60:02d}")


# ---------------------------------------------------------------- hiding
@lru_cache(maxsize=None)
def template(path):
    return np.asarray(Image.open(path).convert("L"), np.float32)


def find_row(frame, path, x, limit=18.0):
    """Top y where the template best matches the frame's column strip at x, or None when nothing matches well
    (mean absolute difference over the template above `limit`)."""
    tmpl = template(path)
    h, w = tmpl.shape
    strip = np.asarray(frame.crop((x, 0, x + w, frame.height)).convert("L"), np.float32)
    diff = np.abs(sliding_window_view(strip, (h, w))[:, 0] - tmpl).mean(axis=(1, 2))
    y = int(diff.argmin())
    return y if diff[y] < limit else None


def tracked_rect(keys, s):
    """A moving rect from [[take_s, x0, y0, x1, y1], ...] keys, linear between them."""
    keys = sorted(keys)
    a = ([k for k in keys if k[0] <= s] or keys[:1])[-1]
    b = ([k for k in keys if k[0] >= s] or keys[-1:])[0]
    return lerp(a[1:], b[1:], 0 if b[0] == a[0] else (s - a[0]) / (b[0] - a[0]))


def found_rects(frame, finds):
    """Rects around each template match: {"template": png, "x": left, "box": [dx0, dy0, dx1, dy1]}."""
    rects = []
    for find in finds:
        y = find_row(frame, find["template"], find["x"])
        if y is not None:
            dx0, dy0, dx1, dy1 = find["box"]
            rects.append([find["x"] + dx0, y + dy0, find["x"] + dx1, y + dy1])
    return rects


def patch(frame, rects):
    """Paints each rect with the colour just left of it (hides a badge on a flat bar)."""
    d = ImageDraw.Draw(frame)
    for x0, y0, x1, y1 in rects:
        d.rectangle([x0, y0, x1, y1], fill=frame.getpixel((max(0, x0 - 4), (y0 + y1) // 2)))
    return frame


def blur(frame, rects):
    for rect in rects:
        box = tuple(int(v) for v in rect)
        frame.paste(frame.crop(box).filter(ImageFilter.GaussianBlur(14)), box[:2])
    return frame


# ---------------------------------------------------------------- one shot
def as_rects(zoom):
    """A zoom as a list of rects: one rect [x0, y0, x1, y1] (a fixed crop) or a list of one or two (a move)."""
    return [zoom] if isinstance(zoom[0], (int, float)) else zoom


class ShotRenderer:
    """Turns source frames of one shot into output frames."""

    def __init__(self, shot, style, cursor, take):
        self.shot, self.style, self.cursor = shot, style, cursor
        self.src_w, self.src_h = probe_size(take)
        self.take_start = start_time(take)
        self.dur = shot_duration(shot)
        self.view = shot.get("view") or [0, 0, self.src_w, self.src_h]
        self.zooms = [self.fit_aspect(z) for z in as_rects(shot.get("zoom", self.view))]

    def fit_aspect(self, rect):
        """Grows a crop rect to the output's aspect, kept inside the shot's view."""
        vx0, vy0, vx1, vy1 = self.view
        x0, y0, x1, y1 = rect
        cx, cy, w, h = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0
        out_aspect = self.style.w / self.style.h
        w, h = (w, w / out_aspect) if w / h > out_aspect else (h * out_aspect, h)
        w, h = min(w, vx1 - vx0), min(h, vy1 - vy0)
        cx, cy = min(max(cx, vx0 + w / 2), vx1 - w / 2), min(max(cy, vy0 + h / 2), vy1 - h / 2)
        return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]

    def crop_at(self, local):
        e0, e1 = self.shot.get("ease", [0, 1])
        p = ease((local / self.dur - e0) / max(1e-6, e1 - e0))
        return lerp(self.zooms[0], self.zooms[-1], p)

    def to_output(self, point, crop):
        sx, sy = self.style.w / (crop[2] - crop[0]), self.style.h / (crop[3] - crop[1])
        return (point[0] - crop[0]) * sx, (point[1] - crop[1]) * sy

    def hide(self, frame, s):
        """Patches and blurs, in source pixels, before any crop."""
        shot = self.shot
        if not any(shot.get(k) for k in ("patch", "blur", "blur_track", "blur_find")):
            return frame
        frame = patch(frame.copy(), shot.get("patch", []))
        rects = list(shot.get("blur", [])) + found_rects(frame, shot.get("blur_find", []))
        if shot.get("blur_track"):
            rects.append(tracked_rect(shot["blur_track"], s))
        return blur(frame, rects)

    def draw_spot(self, layer, crop, local):
        """Dims everything outside the spot rect and rings it."""
        t0, t1 = self.shot.get("spot_t", [0.2, self.dur])
        a, px = fade_alpha(local, t0, t1), self.style.px
        x0, y0 = self.to_output(self.shot["spot"][:2], crop)
        x1, y1 = self.to_output(self.shot["spot"][2:], crop)
        ring = [x0 - px(8), y0 - px(8), x1 + px(8), y1 + px(8)]
        dim = Image.new("RGBA", layer.size, (0, 0, 0, int(140 * a)))
        rounded(dim, ring, px(12), fill=(0, 0, 0, 0))
        layer = Image.alpha_composite(layer, dim)
        rounded(layer, ring, px(12), outline=self.style.accent + (int(255 * a),), width=px(3))
        return layer

    def draw_cursor(self, layer, crop, s):
        at = self.cursor.at(s)
        if at is None:
            return
        scale = self.style.w / (crop[2] - crop[0])  # output pixels per source pixel at this zoom
        ox, oy = self.to_output(at, crop)
        rip = self.cursor.ripple(s)
        if rip is not None:
            r = (10 + 34 * ease(rip / 0.45)) * min(scale, 1.8)
            ImageDraw.Draw(layer).ellipse([ox - r, oy - r, ox + r, oy + r], width=self.style.px(4),
                                          outline=self.style.accent + (int(230 * (1 - rip / 0.45)),))
        layer.alpha_composite(cursor_sprite(int(24 * min(max(scale, 0.83), 2.2))), (int(ox) - 2, int(oy) - 2))

    def draw_texts(self, layer, crop, local, s):
        """Callouts, the step caption and the elapsed-time counter."""
        for c in self.shot.get("callouts", []):
            t0, t1 = c.get("t", [0.3, self.dur - 0.2])
            a = fade_alpha(local, t0, t1)
            if a > 0:
                draw_callout(layer, self.style, c, a, self.to_output(c["to"], crop) if "to" in c else None)
        if self.shot.get("caption"):
            draw_caption(layer, self.style, self.shot["caption"], self.shot.get("caption_bottom", False))
        if self.shot.get("counter") and self.take_start is not None:
            text = elapsed_text(self.shot["counter"], self.take_start + s - self.shot["counter_zero"])
            box = self.shot.get("counter_box", [self.style.w - self.style.px(520), self.style.px(28)])
            draw_callout(layer, self.style, {"text": text, "box": box}, 1.0)

    def compose(self, frame, s, local):
        """The output frame for source frame `frame` at take time s, `local` seconds into the shot."""
        crop = self.crop_at(local)
        img = self.hide(frame, s).resize((self.style.w, self.style.h), Image.LANCZOS, box=tuple(crop)).convert("RGBA")
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        if "spot" in self.shot:
            layer = self.draw_spot(layer, crop, local)
        if self.cursor and not (self.shot.get("no_cursor") or self.shot.get("title")):
            self.draw_cursor(layer, crop, s)
        self.draw_texts(layer, crop, local, s)
        if self.shot.get("title"):
            layer = draw_title(layer, self.style, self.shot["title"], 1.0)  # in and out come from the shots' fades
        return Image.alpha_composite(img, layer).convert("RGB")


# ---------------------------------------------------------------- decoding and encoding
def decode(take, start, length, speed, count, fps):
    """Yields `count` RGB frames from `take` starting at `start`, played `speed` times faster, at `fps`."""
    w, h = probe_size(take)
    cmd = [FFMPEG, "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length + 0.1:.3f}", "-i", str(take),
           "-vf", f"setpts=(PTS-STARTPTS)/{speed:.6f},fps={fps}", "-frames:v", str(count),
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    while len(raw := proc.stdout.read(w * h * 3)) == w * h * 3:
        yield np.frombuffer(raw, np.uint8).reshape(h, w, 3)
    proc.wait()


def source_frames(take, shot, fps):
    """Yields (take time, frame array) for each output frame of the shot; in == out holds one frame."""
    t_in, t_out, dur = shot["in"], shot["out"], shot_duration(shot)
    n = max(1, round(dur * fps))
    if t_out <= t_in:
        frame = next(decode(take, t_in, 1 / fps, 1.0, 1, fps))
        yield from ((t_in, frame) for _ in range(n))
        return
    speed = (t_out - t_in) / dur
    frames, last = decode(take, t_in, t_out - t_in, speed, n, fps), None
    for k in range(n):
        last = next(frames, last)
        yield t_in + k / fps * speed, last


def encoder(out, style):
    lossless = ["-c:v", "libx264rgb", "-qp", "0", "-preset", "ultrafast"]
    delivery = ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    return subprocess.Popen([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{style.w}x{style.h}", "-r", str(style.fps), "-i", "-",
                             *(lossless if str(out).endswith(".mkv") else delivery), str(out)], stdin=subprocess.PIPE)


# ---------------------------------------------------------------- edit list
def load_edl(path):
    """The edit list with `vars` substituted: a shot value that equals a var name takes the var's value."""
    with open(path, encoding="utf-8") as f:
        edl = json.load(f)
    names = edl.get("vars", {})
    edl["shots"] = [{k: names.get(v, v) if isinstance(v, str) else v for k, v in s.items()} for s in edl["shots"]]
    return edl


def make_style(edl):
    first = edl["shots"][0].get("source", edl.get("source"))
    w, h = edl.get("out") or probe_size(first)
    return Style(w=w - w % 2, h=h - h % 2, fps=edl.get("fps", 30), accent=tuple(edl.get("accent", (56, 139, 253))),
                 ink=tuple(edl.get("ink", (13, 22, 38))), regular=first_font("regular", edl.get("font")),
                 bold=first_font("bold", edl.get("font_bold")))


class Takes:
    """Per-take cursors and glow removal, loaded once."""

    def __init__(self, edl):
        self.edl, self.cursors = edl, {}
        self.deglow = Deglow(edl["deglow"]) if edl.get("deglow") else None

    def cursor(self, shot, take):
        path = shot.get("cursor", self.edl.get("cursor", f"{take}.cursor.csv"))
        if path not in self.cursors:
            lag = self.edl.get("cursor_lag_s", 0.0)
            self.cursors[path] = Cursor.from_csv(path, lag) if Path(path).exists() else None
        return self.cursors[path]

    def clean(self, frame):
        return Image.fromarray(self.deglow(frame) if self.deglow else frame)


def render_video(edl, out, only=None):
    """Renders the edit list to `out`; prints where each shot starts. Returns the number of frames written."""
    style, takes = make_style(edl), Takes(edl)
    enc, prev, total = encoder(out, style), None, 0
    for i, shot in enumerate(edl["shots"]):
        if only is not None and i != only:
            continue
        take = shot.get("source", edl.get("source"))
        shots = ShotRenderer(shot, style, takes.cursor(shot, take), take)
        print(f"shot {i:2d} at {total / style.fps:6.1f} s  {shot.get('caption') or shot.get('title', [''])[0]}")
        fade_n, last = round(shot.get("fade", 0) * style.fps), prev
        for k, (s, frame) in enumerate(source_frames(take, shot, style.fps)):
            img = shots.compose(takes.clean(frame), s, k / style.fps)
            if prev is not None and k < fade_n:
                img = Image.blend(prev, img, ease((k + 1) / (fade_n + 1)))
            enc.stdin.write(img.tobytes())
            last, total = img, total + 1
        prev = last
    enc.stdin.close()
    enc.wait()
    print(f"{out}: {total} frames, {total / style.fps:.1f} s, {style.w}x{style.h}")
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("edl")
    ap.add_argument("out")
    ap.add_argument("--only", type=int, help="render shot N alone, to check it")
    args = ap.parse_args()
    render_video(load_edl(args.edl), args.out, args.only)


if __name__ == "__main__":
    main()

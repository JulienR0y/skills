# Edit list format (render.py)

An edit list is a JSON file: a few settings and a list of shots, played in order. Times are seconds in the
**source take**. Rectangles in the take are `[x0, y0, x1, y1]` in take pixels. Positions of callout boxes are in
**output** pixels.

## Top level

| Field | Default | Meaning |
|---|---|---|
| `source` | - | The take every shot uses unless the shot names its own `source`. |
| `out` | the first take's size | Output `[width, height]`. 1600x960 or 1920x1080 suit decks. Overlays are designed for 1600x960 and scale with the output's area, so a portrait output works too. For a take smaller than about 1000 px on its long side, set `out` to 1.5-2x the take; more looks soft. |
| `fps` | 30 | Output frame rate. |
| `cursor` | `<take>.cursor.csv` | The cursor log to draw the pointer from. A take without a log gets no pointer. |
| `cursor_lag_s` | 0 | Seconds to shift the pointer earlier. The log starts slightly before the first captured frame; 0.3-0.5 s matches a pointer to its click on Windows. Check one click shot and adjust. |
| `deglow` | none | A glow model from `deglow.py fit`, applied to every frame (same size as the take). |
| `accent`, `ink` | blue, dark navy | `[R, G, B]` of the caption pill, rings and callout bar / of the callout cards and title veil. |
| `font`, `font_bold` | Segoe UI, Arial or DejaVu | TrueType files for the overlays. |
| `vars` | `{}` | Names for repeated values: a shot field whose value is a var's name gets the var's value (a path, a rect, a list). |
| `shots` | - | The shots, in order. |

## Shot

| Field | Meaning |
|---|---|
| `in`, `out` | Source range. `in == out` holds that one frame for `dur`. |
| `dur` | Seconds on screen. Default `out - in`. Shorter than the range plays it faster (a time-lapse). |
| `source`, `cursor` | Per-shot take and cursor log, overriding the top level. |
| `view` | The part of the take this shot may show, `[x0, y0, x1, y1]`. Default: the whole frame. Use it to crop away something that changes between shots, such as a browser bar that appears while an agent acts. |
| `zoom` | One rect `[x0, y0, x1, y1]` (a fixed crop), or a list of two `[[...], [...]]` (a move from the first to the second). Each is grown to the output's aspect and kept inside `view`. |
| `ease` | `[start, end]` fractions of the shot over which the zoom moves. Default `[0, 1]`; `[0, 0.6]` arrives early and holds. |
| `fade` | Cross-fade in from the previous shot's last frame, in seconds. |
| `caption` | Chapter text in the accent pill, top left. `caption_bottom: true` puts it bottom left (when the top holds the action). |
| `callouts` | Cards: `{"text": title, "sub": subtitle, "box": [x, y], "t": [from, to], "to": [x, y]}`. `box` is the card's top-left corner in output pixels; `t` is seconds into the shot; `to` (take pixels) draws a line and dot to that point. |
| `spot` | Take rect to highlight: the rest dims and the rect gets a ring. `spot_t: [from, to]` limits it in time. |
| `counter` | Elapsed-time card: `{min}`, `{sec}` or `{clock}` (m:ss) since `counter_zero` (unix seconds, for example a mark's time). Uses the take's `.start.txt` for wall time, so it stays right across segments and speed-ups. `counter_box: [x, y]` moves it. |
| `title` | `[title, subtitle]` on a dark veil over the frame. The pointer is not drawn on title shots. |
| `no_cursor` | Do not draw the pointer (for example a browser agent that draws its own). |
| `blur` | Take rects to blur in every frame of the shot. |
| `blur_track` | A moving blur: `[[take_s, x0, y0, x1, y1], ...]`, linear between keys. |
| `blur_find` | Blur wherever a template image matches: `[{"template": "row.png", "x": left, "box": [dx0, dy0, dx1, dy1]}]`. The template is a small crop (from `frames.py`) of the thing to hide; it is searched down the column at `x`, and the box is relative to the match. Use it for a list row that moves. |
| `patch` | Take rects painted with the colour just left of them (hides an update badge on a flat bar). |

## Example

```json
{
  "source": "takes/t1.mp4",
  "out": [1600, 960],
  "cursor_lag_s": 0.4,
  "deglow": "glow.npz",
  "vars": {"ZERO": 1762380000.0},
  "shots": [
    {"in": 3.0, "out": 3.0, "dur": 2.8, "title": ["Acme Reports", "A real run: last month's sales into a board report"]},
    {"in": 3.0, "out": 11.0, "dur": 5.0, "fade": 0.4, "caption": "1  Pick the data",
     "zoom": [[0, 0, 1920, 1152], [900, 200, 1900, 800]], "ease": [0, 0.5],
     "callouts": [{"text": "Choose a source", "sub": "Any connected database or sheet", "box": [60, 700],
                   "t": [1.2, 4.8], "to": [1400, 480]}]},
    {"in": 11.0, "out": 640.0, "dur": 2.0, "fade": 0.25, "caption": "2  It builds the report",
     "counter": "{min} min", "counter_zero": "ZERO", "no_cursor": true},
    {"in": 641.0, "out": 652.0, "dur": 5.5, "fade": 0.25, "caption": "3  The result",
     "spot": [600, 300, 1500, 900], "spot_t": [0.8, 5.5],
     "callouts": [{"text": "Ready to share", "sub": "12 pages, every figure linked to its source", "box": [60, 90]}]},
    {"in": 652.0, "out": 652.0, "dur": 2.8, "fade": 0.3, "title": ["Acme Reports", "One run · 10 min · 6 Nov 2026"]}
  ]
}
```

## Tips

- Shot times come from `mark.py --take` and contact sheets; render one shot with `--only N` and look at it before
  doing the rest.
- To find a callout's `to` point or a `zoom` rect, take a still of the take (`frames.py take.mp4 12.5 --out t`) and
  read the coordinates off it.
- `render.py` prints each shot's start time in the output. Use those for stills and for the timestamps in the notes.
- An `.mkv` output is lossless RGB (`libx264rgb`), a clean source for a GIF.

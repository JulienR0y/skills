# Pitfalls seen in real shoots, and their fixes

## Coloured glow at the screen edges

Agent apps signal "an agent is acting" with a coloured glow around the screen (Claude's computer use) or around a
browser page (browser extensions). Screen capture records it, and its colour shifts the whole edge of the video.

The glow usually vanishes for an instant whenever the agent takes a screenshot, so the take contains clean frames.

1. `deglow.py scan take.mp4 <start> <seconds>` prints the edge strength twice a second: high values glow, values near
   0 are clean. Pick a glowing time and a clean time close together, with the same content on screen.
2. `deglow.py fit take.mp4 <t_glow> <t_clean> glow.npz`. If the edges are a flat colour (a web page), the colour cannot
   be fitted: pass `--colour 204,104,80` (Claude's orange) or the colour you measure. For a glow inside a browser page
   rather than at the screen edge, add `--everywhere`.
3. `deglow.py check take.mp4 glow.npz <t> check.png` shows one frame before and after. Look at it.
4. Put `"deglow": "glow.npz"` in the edit list. A model fits takes of the same size and layout; refit for another
   window size.

## Screen lock and switched desktops

A locked screen cannot be captured (Windows: ffmpeg's gdigrab fails with error 5). `record.py` waits and continues in
`take-002.mp4`, `take-003.mp4`, each with its own start time and cursor log. The time-lapse jumps over the gap, and an
elapsed-time counter stays right because it uses each segment's start time. Better: turn the screen lock and screen
saver off for the take, and keep the machine awake.

## A browser bar that appears while the agent acts

Browser automation can show a bar such as "<extension> started debugging this browser" while it acts, which pushes
the page down by its height. Compare a still with the bar and one without, and give each shot a `view` that starts
at the page's top for that state, so content stays put from shot to shot. Crop the bar itself out of every shot.

## Playwright's browser window

Playwright MCP opens its own browser window. Record it with `--window "<page title>"` once the page is loaded (the
recorded area stays fixed when the title changes later). Playwright clicks through the page, not the real mouse,
so the cursor log stays still: set `no_cursor`.

- Its resize sets the page's viewport, not the window, so the take can hold the browser's tabs, address bar, an
  "automated test software" bar and an empty area below the page. Take a still of the take (`frames.py`), read the
  page's rect off it, and give every shot that rect as its `view`.
- Navigating can leave an extra `about:blank` tab in front. List the tabs, close the blank one, then resize.
- Element refs change after a reload or navigation: take a new page snapshot before the next action.
- Run actions one after another, never in parallel: two typing calls at once interleave their text.

## The browser agent draws its own pointer

Browser extensions draw their own pointer in the page, while the system pointer (the one `record.py` logs) does not
move. Set `no_cursor` on those shots and let the extension's pointer be the one viewers see.

## The take stops with "user interrupt"

Computer use cancels an action when someone else moves the mouse or presses a key, and it may hide other apps
while it acts. Before the take, ask the user to keep their hands off the machine until you say it is done. If an
action is interrupted while the user may be at the machine, stop and ask whether to go on; a retry may land in their
work. Interrupts also happen with nobody at the machine, for example when another app takes the focus: then single
actions (one click per call) get through where batches do not, and a shell sleep paces the beats.

## Window titles and DPI

- Window titles often carry more than the app name (a profile, a folder, a file). Use `record.py --list` and pass a
  unique part of the title.
- `record.py` works in physical pixels, relative to the recorded window. Computer-use screenshots come in a scaled
  frame that the tool reports (for example 1456x819 for a 2560x1440 screen), whatever scale you ask the image at.
  Click in that frame. For a `zoom`, `spot` or `blur` rect, read coordinates off a still from `frames.py` instead.

## Something covers the target window

Your own agent app, a notification or a chat popup in front of the target is recorded too: the recorder films a
screen area, not the window's own pixels. With `--window`, `record.py` prints `COVERED by '<title>'` and
`target clear again` with take times; an app can jump in front in the middle of a take (agent apps do when they
show a prompt). Bring the target back, redo the beat, and cut the covered stretch, or re-shoot it if it holds a key
beat. Check a contact sheet of the whole take before you plan the edit.

## Menus and flyouts that open past the window

Drop-down lists, menus and flyouts of compact apps often open beyond the window's own rectangle and get cut off.
Record with `--pad 40` (or more) so they stay in frame, then crop each shot with `view` or `zoom`. The margin films
whatever is behind it, other windows' text included: crop it away, or blur it where a flyout needs the room.

## Several windows with the same title

`record.py --window` takes the frontmost match and names it. Extra windows of the same app (left over from a
rehearsal) can still cover or confuse the operator: close them before the take.

## Hover tooltips and stuck states

A tooltip from the last click can sit over the next target for seconds. The operator moves the pointer to a neutral
spot after each click. In review, look for screens that stay frozen while the caption moves on (a page still loading,
a panel left open): shorten that shot, pick a later in-point, or re-shoot that beat.

## First-run prompts in a fresh profile

A fresh profile or account shows sign-in prompts, tours and empty states, and some features stay unavailable until
the first sign-in. Do all of that before the take, in a rehearsal.

## Text input in IDEs and terminals

Computer use often allows only clicks in IDEs and terminals. Send messages through the app's CLI, automation API or
a test-driver extension, from a shell that leaves the text alone. Git Bash on Windows rewrites arguments that start
with `/` into paths (`/help` becomes `C:/Program Files/Git/help`): use PowerShell or set `MSYS_NO_PATHCONV=1`.

## File chooser dialogs

A native file chooser cannot be driven by browser tools. Set the files on the page's file input with the tool's
upload action, and say in the notes that the dialog is not shown.

## GIF size

A GIF stores every frame as a full palette image. A 60-90 second screen demo will not fit under about 8 MB at a
readable size, even at 1024 px and 6 fps. Deliver the MP4 (decks, READMEs on GitHub and chat apps all play it). For a
short loop of 15 seconds or less, render a lossless `.mkv` and convert it:

```
ffmpeg -i loop.mkv -vf "fps=10,scale=1024:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" loop.gif
```

## Temp folders and open files

- Temp folders get cleaned. Keep the project folder (takes, cursor logs, marks, edit lists, glow models) somewhere
  durable until the video is signed off.
- Writing over a video that is open in a player or a slide fails. Write a new file name.

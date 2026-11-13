---
name: demo-video
description: Make a polished, product-style demo video of real software with an agent at the controls - plan a storyboard, record the screen while an operator agent clicks through a real run, then cut the take into an MP4 with eased zooms, callouts, step captions, a smooth redrawn pointer, time-lapses with an elapsed-time counter, blurs for sensitive data, title cards and stills. Use it whenever someone asks to record, film, screencast or make a demo, walkthrough, product video, teaser or GIF of an app, extension, CLI or web page - for a deck, a release note, a README or a review - even when they only say "show it working on video". Recording is tested on Windows; macOS and Linux are best effort.
---

# Make a product demo video with an agent at the controls

A good demo is one real run of the product, filmed cleanly and edited tightly. This skill splits the job the way a
small film crew would. You are the **director**: you plan, set the stage, run the recorder, edit and check. An
**operator** performs the clicks from a written brief while the recorder runs. Afterwards a renderer turns the raw
take and an edit list (JSON) into the finished video.

The scripts are in `scripts/` in this skill's folder. They need Python 3.10+ and [uv](https://docs.astral.sh/uv/);
uv fetches Pillow, NumPy and an ffmpeg binary (imageio-ffmpeg) on first use. Run them as

```
uv run --no-project --with pillow --with numpy --with imageio-ffmpeg python <skill>/scripts/<script>.py ...
```

| Script | What it does |
|---|---|
| `record.py --out take.mp4 [--window "<title text>" \| --rect X,Y,W,H]` | Records a window or screen area at full quality, without the real pointer, plus a cursor log. Stops when `take.mp4.stop` exists. Keeps going in new segments if capture drops. `--list` shows windows (Windows). |
| `mark.py <label>` / `--take take.mp4` / `--clicks take.mp4` | Stamps a beat on the wall clock during the take / lists each beat as a time in the take / lists every click in the take. Needs only plain `python`. |
| `frames.py <video> --sheet sheet.png --every 5 [--start 30 --end 60] [--cols 6]` | Contact sheet with timestamps, to find moments in a take or check a render; keep each sheet to about 30 frames so it stays readable. `frames.py <video> 12.5 40 --out still` saves full-size stills. |
| `deglow.py scan / fit / check` | Removes the coloured glow an agent app draws at the screen edges while it acts. |
| `render.py edl.json out.mp4 [--only N]` | Renders the edit list. Prints where each shot starts in the output. |
| `test_render.py` | Self-check: `uv run ... --with pytest python -m pytest <skill>/scripts`. |

## What makes a demo worth watching

- **Real, not staged.** Film one real run, with every state on screen something the product actually did. Viewers
  can tell a mock-up, and a reviewer who later finds one stops trusting the rest. Say in the delivery notes what you
  cut, sped up or blurred.
- **A task a real user does.** Take the flow or the prompt from real use: a teammate's recent run, a support ticket, a
  release's headline feature. A toy step ("print the version") proves nothing and wastes the viewer's time.
- **A first-time user's view.** Use a fresh profile or account, a clean folder, default settings and theme, nothing
  personal in sidebars or tabs. Viewers picture themselves starting from zero.
- **Short and chaptered.** Unless the user asks for a length, aim for 45-90 seconds in 3-5 numbered chapters
  ("1  Get started", "2  Run it", ...), shown as a caption pill. One idea per shot. A callout title is at most about
  8 words, its subtitle about 12.
- **Waiting, shown honestly.** Speed long waits up and put an elapsed-time counter on screen rather than cutting
  them out silently: the viewer learns how long it really takes.

## Roles

- **Director (you)** keeps the plan and the edit in context. You never babysit the run click by click: that burns
  your context and the user's screen time.
- **Operator**: a subagent on a smaller, faster model (for example Sonnet or Haiku) that follows the brief in
  `references/operator-brief.md`: it performs each beat with camera pacing, stamps a mark before it, reads every
  confirmation before clicking, and returns a report. If you cannot start subagents, play the operator yourself with
  the same brief.
- **How the operator acts**: desktop apps through computer use; web apps through a browser tool (Claude in Chrome or
  a built-in browser). IDEs and terminals usually allow clicks but not typing under computer use. Send text to them
  through the app's own CLI, automation API or a test-driver extension, and film the result.
- **Coordinates**: computer-use screenshots come in a scaled frame that the tool reports (for example 1456x819 for a
  2560x1440 screen). Click in that frame; but every rect and point in the edit list is in take pixels, read off a
  still from `frames.py`.

## Workflow

### 1. Plan

Write a short storyboard, one row per shot: chapter, what is on screen, the action, the callout text, and its time
on screen. Then agree with the user (when the request already fixes these, follow it and note your choices):

- the real task and the data it uses (test data or anonymised data, never a client's);
- what the run may change (accounts, files, messages) and what the operator must never click (send, push, delete,
  buy, install, settings) unless the plan names it;
- where the project folder lives. Keep takes out of temp folders: they get cleaned, and raw takes are the only
  way to re-edit.

### 2. Set the stage

- Apps people use full screen (IDEs, browsers, office apps) are maximised on the primary screen: double-click the
  title bar or press Win+Up. Never resize by dragging an edge: a drag that misses lands on another app. Snap compact
  apps (a calculator, a settings window) to half the screen with Win+Left or Win+Right: at their natural size of a
  few hundred pixels the video comes out small, and soft once enlarged.
- Everything that is not part of the story is done before the recorder starts: modes, units, sample data, opened
  files. A rehearsal finds these.
- Nothing else overlaps the target, including your own agent app. Move that to another screen or minimise it:
  anything over the target ends up in the take. Computer use may hide other apps while it acts; tell the user so.
- Do Not Disturb or Focus on, notifications off. Screen lock and screen saver off for the length of the take: a locked
  screen cannot be captured (the recorder then continues in a new segment once it unlocks).
- Sign-ins, first-run prompts and permissions are done beforehand, off camera.
- No secrets on screen: no `.env` files, tokens, keys, or personal or client data in any visible panel.
- Do a rehearsal without recording when the flow has dialogs you have not seen. It is cheap and finds the slow or
  surprising steps.
- Tell the user before you take the screen, and ask them to keep their hands off the mouse and keyboard until you
  say the take is done: computer use stops each action ("user interrupt") when someone else moves the mouse or
  types. If that happens while the user is at the machine, ask them before going on; do not retry into their work.
  When it happens with nobody at the machine, use single actions instead of batches, and pace with a shell sleep.

### 3. Record

1. Start the recorder in the background:
   `record.py --out <project>/takes/t1.mp4 --window "<title text>" --pad 40`. Wait for its line
   `recording WxH at X,Y to ...` (the first run of uv spends a few seconds installing packages) and check the window
   and size it names. When several windows match, it takes the frontmost and says so. `--pad` keeps menus and
   flyouts that open past the window's edges in frame; drop it for a maximised window.
   The recorder films a screen area, so anything in front of the window is filmed too. It prints
   `COVERED by '<title>'` with the take time when another window comes in front, and `target clear again` when it
   is gone. Read its output between beats; the operator brings the target back to the front, and you cut or
   re-shoot that stretch.
2. Start the operator with the brief (`references/operator-brief.md`). It runs `mark.py <beat>` from the project
   folder before each beat, so the beats land in `marks.csv`. When you play the operator yourself, mark only the
   chapter starts: `mark.py --clicks takes/t1.mp4` later lists every click in the take, which finds the rest.
3. Wait for the operator's report, then create `t1.mp4.stop`. For a long run, let the recorder run and check
   progress through the product's own status or logs at a slow interval, not by watching the screen.

Take 2-3 takes of the key moments if they are short; the best one usually needs the fewest edits.

### 4. Log the take

- `mark.py --take takes/t1.mp4 [takes/t1-002.mp4]` turns marks into take times; `mark.py --clicks takes/t1.mp4`
  lists the take time and position of every click.
- `frames.py takes/t1.mp4 --sheet sheet.png --every 5` (and narrower windows around each mark) shows what happened
  when. Look at the sheets: they are how you see the footage.
- If an agent app drew a glow at the edges, build a glow model now (`references/pitfalls.md`, "Coloured glow").
- Note anything that must not be shown: a personal name, a client file, a notification. It gets blurred in the edit.

### 5. Edit

Write the edit list (`references/edit-list.md`). For more than about ten shots, or a long time-lapse, write a short
Python script that generates it: times and repeated settings stay in one place.

- Each shot is a source range, its duration on screen, and what to draw. A shot shorter than its source range is a
  speed-up; `in == out` holds one frame (a title or a pause to read).
- Leave a callout up for about 1 second plus 1 second per 5 words, and at least 2.5 seconds.
- Zoom to where the action is; ease it over the first part of the shot. Cross-fade 0.25 s between shots of the same
  scene, 0.4 s at a chapter change.
- Time-lapses: at most about 2 seconds on screen per long wait, with a counter (`counter`, `counter_zero`).
- Title card at the start (what this is) and at the end (one-line result: time, scale, date).
- Check single shots with `render.py edl.json shot.mp4 --only N` as you go.

### 6. Review

Render the whole video, then make a contact sheet of it every second (`frames.py out.mp4 --sheet review.png
--every 1 --width 400`, in 30-second windows if it is long) and look at every frame:

- Does each shot show what its caption and callout say, at that moment? Nothing stuck, frozen or half-loaded on
  screen while the caption has moved on, no dialog left open behind the action, no hover tooltip over the subject.
- No secret, personal or client data anywhere, including in small text, tabs and file lists.
- Callouts and captions do not cover the thing they point at. The pointer moves where the clicks happen.
- No glow, debugging bar or other agent overlay left in.

Fix and re-render until a full pass finds nothing. This step is what separates a demo from a screen recording.

### 7. Deliver

- The MP4: H.264, yuv420p, faststart, as `render.py` writes it. It plays in PowerPoint, Keynote, browsers and chat
  apps. For a slide: Insert > Video, set to start on click, with a still as its poster frame.
- 2-3 stills at the key moments, taken from the rendered video so they carry the callouts
  (`frames.py out.mp4 13.5 45.2 81 --out still`).
- A short notes file: what each chapter shows with its timestamp, the real run behind it (when, which version), and
  what was edited (speed-ups, cuts, blurs, the redrawn pointer).
- A GIF only for a loop of about 15 seconds or less (`references/pitfalls.md`, "GIF size").

## Ground rules

- The run touches real systems. Do only what the plan names; the operator reads every confirmation dialog before
  clicking and backs out with Cancel when unsure, then reports.
- Secrets and personal data never appear in a delivered frame. When one slipped into the take, blur it in every
  frame it appears (`blur`, `blur_track`, `blur_find`) and check the review sheets again.
- Delete only what your own run created, and only when the plan says so. Leave the user's windows, folders and
  accounts as they were.
- Never fake a state. If a step failed in the take, re-shoot it or say so; do not paint over it.

## References

- `references/edit-list.md`: the edit-list format, every field, and an example.
- `references/operator-brief.md`: the brief template for the operator subagent.
- `references/pitfalls.md`: problems seen in real shoots and their fixes (glow, screen lock, browser bars, DPI,
  covered windows, GIF size, typed text).

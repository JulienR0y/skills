---
name: linkedin-banner
description: Use when someone wants a LinkedIn banner (cover or background image) designed for them. Interviews the person about their industry, path and accomplishments, finds one visual idea that is theirs, renders it as a 1584 x 396 PNG with a script, checks it at LinkedIn's real display size, iterates on their feedback, and uploads it only after they approve a specific image.
---

# LinkedIn banner

Design a banner that represents the person, with them, until they approve one. Every person should end up with a
different banner: this skill carries a process and a set of checks, not a look.

## Rules that always hold

- **The person, not the employer.** No company, client, colleague or product names, and nothing that implies
  production use of anything. The banner should survive a job change.
- **Inspiration, never copying.** References (brands, games, posters) give general ideas such as "dense technical
  labels" or "flat blocks on a grid". Never trace or reuse anyone's artwork, glyphs, logos, palette values or layout.
  Draw every mark from scratch in the script. Say plainly to the person what is taken and what is avoided.
- **No downloads without asking.** Use fonts already installed. Ask before fetching a font or any other file.
- **Public edit needs a yes.** Upload only after the person approves one specific image by name.
- **No invented evidence.** There is no controlled study comparing banner styles. The popular "21x" and "11x" figures
  bundle the banner with the profile photo or have no primary source. If asked, say so and show the mock instead.

## Step 1: interview

Ask two or three questions at a time, in plain words. Stop when you can state their story as "from X to Y" or
"X and Y at once".

1. What do you do now, and what did you do before? What changed between the two?
2. Which two or three accomplishments are you proud of?
3. Who should the banner speak to: recruiters, clients, peers?
4. Is there a phrase you use about yourself, or one that colleagues use about you?
5. What outside work is safe and fun to show: a place, a craft, an obsession?
6. Which visuals do you love (a brand, a game, a poster, your current banner) and which do you dislike? Why?
7. What must never appear?

If they name references, research them briefly from reputable sources, including any controversy about originality,
and report what was confirmed and what was not.

## Step 2: find one idea

Look for the tension or the transformation in their answers, and express it as one picture. In the session this skill
came from, a biochemist turned AI engineer became "an organic network that settles into a strict grid". A different
person needs a different picture: do not reuse that one.

Offer three concepts as one line each, recommend one, and render the best one or two straight away. People react to
images far more usefully than to descriptions.

## Step 3: render

Write a Python script with Pillow, starting from `scripts/banner_base.py` (3x supersampling, exact output size, safe
zone guides, fixed random seeds). Keep the script next to the output so the banner can be regenerated.

Checks before showing any image:

- Exactly 1584 x 396.
- Nothing important in the photo zone: x under 350 and y over 200.
- **Nothing meant to be read is under 20 px tall in the source.** LinkedIn shows the banner at about 792 px wide on
  desktop, so smaller text becomes texture.
- At most two typefaces, each with a job. Generic sans-serif type reads as a template; choose type deliberately and
  say why.
- Every word passes the stranger test: would someone who has never met them understand it in two seconds? Personal
  taglines often fail it; plain facts pass.
- Nothing that goes stale: no city, coordinates, job title of the month, or dates.
- Look at the render yourself before sending it.

Known traps:

- A row of labelled tiles (periodic-table style) is read as a word. Either make it spell one or do not use tiles.
- Numbered lists imply a ranking or a sequence the viewer then tries to decode.
- A light banner has no visible bottom edge on LinkedIn's white page; a dark one holds its shape in both modes.
- With random generation, use one seeded generator for layout and another for styling, so a style tweak does not
  reshuffle a picture the person already likes.

## Step 4: preview on a profile

Run `scripts/profile_preview.py <banner.png> [more.png ...]`. It places each banner on a mock profile card in
LinkedIn's light and dark modes at desktop size, with a disc where the photo goes. Judge and compare variants there,
not at full size. Tell the person the mock is approximate and does not cover the mobile app.

## Step 5: iterate

- Take feedback literally. If they dislike one element, remove that element; do not redesign the rest.
- Change one thing per round when you can, and say in a few lines what changed and why.
- When they say they like something, save a checkpoint copy of the image and the script before going further.
- Give one recommendation, not a survey, and ask at most three questions per round.

## Step 6: approve and upload

1. Ask: "Do you approve `<file>` for upload?" Proceed only on a clear yes for that file.
2. In their own browser, open `https://www.linkedin.com/in/me/`, then Edit background image, Edit cover image,
   Change photo, Upload single photo.
3. LinkedIn creates its file input only when "Upload single photo" is clicked, and clicking opens a native file
   picker that browser tools cannot see. If the upload tool finds no file input, either ask the person to pick the
   file themselves, or, before clicking, patch `HTMLInputElement.prototype.click` in the page so a file input is
   attached to the document instead of opening the picker, then give the file to that input.
4. Check the crop screen shows the whole image, then Save changes.
5. Reload the profile and confirm the new banner is showing. Say what you checked and what you did not (mobile).
6. Tell them which image and script are final and which drafts can be deleted. Delete nothing yourself.

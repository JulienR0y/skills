---
name: teams-reader
description: Read Microsoft Teams chats and channels on demand by driving the Teams web app as the signed-in user, with no Graph API or app registration. Use when the user wants to read a Teams chat or channel, catch up on a conversation, pull a daily standup, see what someone said in Teams, grab messages from a thread filtered by author or date range, or feed Teams content into another skill. Also use on "read the standup", "check Teams", "my DSU".
---

# Teams reader

Reads Microsoft Teams chats by driving a real signed-in browser (Playwright with Chrome) instead of the Graph API.
Use it where the tenant does not allow app registration. It acts as the user's own session, so it sees only chats
the user is already in.

The scripts are in `scripts/` in this skill's folder. The sign-in persists in `~/.teams-reader-profile`.

## Setup, once per machine

1. Install Node.js 18 or later and Google Chrome. Set `CHROME_PATH` if Chrome is not in its default place.
2. In this skill's `scripts/` folder, run `npm install`. Run it again after the skill updates, because an update
   replaces the folder.
3. Sign in. The user must do this, because MFA cannot be automated:

   ```bash
   node scripts/teams-read.js --login
   ```

   They sign in, then press Enter in the terminal when their chat list shows. Re-run `--login` when the session
   expires.

## Read a chat

```bash
node scripts/teams-read.js --url "<teams chat or channel link>" [options]
```

On Windows, `scripts\read.cmd` does the same; on macOS and Linux, `scripts/read.sh`.

Options:

- `--url "<link>"`: the Teams link of a chat, meeting chat or channel. Required.
- `--days N`: scroll back about N days. Without it, only the messages already loaded are read.
- `--author "Lastname, Firstname"`: keep only messages whose author contains this text, ignoring case.
- `--json`: print `[{author, datetime, text}]`. Use it when another skill consumes the output.
- `--dump`: print the raw pane text and save a screenshot to `~/teams-reader/last-dump.png`, for debugging.
- `--login`: the one-time interactive sign-in.
- `--headful`: show the browser window. Reads are headless by default.

The default output is one block per message, oldest first: `[YYYY-MM-DD HH:MM] Author`, then the message.

If a read prints `Not logged in`, ask the user to run `--login`.

## Named chats

Get a chat's link in Teams from the chat's `...` menu, then Copy link. Keep the user's named chats (for example
their standup) in their own notes or memory. This skill stores no chat links.

## Common patterns

- Read today's standup: `--url "<standup link>"`.
- One person's updates over 3 weeks: `--url "<standup link>" --days 21 --author "<Lastname, Firstname>"`.
- Hand the user's own updates to a note-taking skill: `--days 2 --author "<the user's name>" --json`, then pass the
  JSON on. This skill only reads.

## Maintenance

Teams uses obfuscated class names but stable `data-tid` attributes. The extractor reads:

- a message from `chat-pane-item`;
- the author from `message-author-name`;
- the body from `chat-pane-message`;
- the time from `time[datetime]`, in UTC ISO;
- the scroll container from `message-pane-list-viewport`.

If Teams changes its layout and reads come back empty, run `node scripts/inspect.js "<link>"` and update
`teams-read.js`.

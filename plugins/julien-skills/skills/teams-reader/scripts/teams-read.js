#!/usr/bin/env node
// On-demand Teams reader: drives the Teams web app as the logged-in user.
// No app registration, no Graph. Login persists in a profile dir so reads are one-shot.
//
//   node teams-read.js --login                              # once: opens a window, you sign in
//   node teams-read.js --url "<url>"                         # read what's currently loaded
//   node teams-read.js --url "<url>" --days 21               # scroll back ~3 weeks of history
//   node teams-read.js --url "<url>" --days 21 --author "Lastname, Firstname"
//   node teams-read.js --url "<url>" --json                 # machine-readable (for other skills)
//   node teams-read.js --url "<url>" --dump                 # raw pane text + screenshot (debug)

const { chromium } = require("playwright-core");
const path = require("path"), os = require("os"), fs = require("fs");

const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PROFILE = path.join(os.homedir(), ".teams-reader-profile");
const OUT = path.join(os.homedir(), "teams-reader"); // debug screenshots
fs.mkdirSync(OUT, { recursive: true });

const has = (f) => process.argv.includes(f);
const arg = (f) => { const i = process.argv.indexOf(f); return i >= 0 ? process.argv[i + 1] : null; };
const url = arg("--url") || process.argv.find((a) => a.startsWith("http"));
const author = arg("--author");
const days = arg("--days") ? parseInt(arg("--days"), 10) : null;

// Runs in the browser: pull every rendered message. Empty placeholders (no body) are skipped.
// Grouped follow-up messages inherit the previous author (Teams shows the name only on the first).
function EXTRACT() {
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const items = [...document.querySelectorAll('[data-tid="chat-pane-item"]')];
  const out = [];
  let lastAuthor = "";
  for (const it of items) {
    const body = clean(it.querySelector('[data-tid="chat-pane-message"]')?.innerText);
    if (!body) continue;
    let a = clean(it.querySelector('[data-tid="message-author-name"]')?.textContent);
    if (a) lastAuthor = a; else a = lastAuthor;
    const t = it.querySelector("time[datetime]");
    out.push({ author: a, datetime: t ? t.getAttribute("datetime") : null, text: body });
  }
  return out;
}

const fmt = (iso) => {
  if (!iso) return "?";
  try {
    return new Date(iso).toLocaleString("en-CA", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).replace(",", "");
  } catch { return iso; }
};

(async () => {
  const login = has("--login");
  const ctx = await chromium.launchPersistentContext(PROFILE, {
    headless: !login && !has("--headful"),
    executablePath: CHROME,
    viewport: { width: 1360, height: 940 },
  });
  const page = ctx.pages()[0] || (await ctx.newPage());
  const done = async (code) => { await ctx.close(); process.exit(code); };

  if (login) {
    await page.goto("https://teams.microsoft.com/", { waitUntil: "domcontentloaded" });
    process.stderr.write("\nSign in to Teams in the window that opened.\nWhen your chat list is visible, press Enter here.\n");
    await new Promise((r) => process.stdin.once("data", r));
    await done(0);
  }

  if (!url) { process.stderr.write("need --url <teams chat url> (or run --login first)\n"); await done(1); }

  // --- POST mode: paste an HTML message into the compose box; --send to actually send ---
  if (has("--post")) {
    const htmlFile = arg("--html-file");
    const html = (htmlFile ? fs.readFileSync(htmlFile, "utf8") : arg("--html") || "").trim();
    if (!html) { process.stderr.write("need --html-file <path> or --html \"<inline html>\"\n"); await done(1); }
    await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: "https://teams.microsoft.com" });
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
    for (const rx of [/use the web app/i, /continue on this browser/i]) {
      try { await page.getByRole("button", { name: rx }).first().click({ timeout: 2500 }); break; } catch {}
    }
    await page.waitForTimeout(3000);
    if (/login\.(microsoftonline|live)\.com/.test(page.url())) { process.stderr.write("Not logged in — run --login\n"); await done(2); }
    const box = await page.waitForSelector('[data-tid="ckeditor"]', { timeout: 60000 });
    await box.click();
    await page.keyboard.press("Control+A");   // clear any persisted draft so the paste doesn't double up
    await page.keyboard.press("Delete");
    const plain = html.replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, "");
    const pasted = await page.evaluate(async ({ h, p }) => {
      try {
        await navigator.clipboard.write([new ClipboardItem({ "text/html": new Blob([h], { type: "text/html" }), "text/plain": new Blob([p], { type: "text/plain" }) })]);
        return "clipboard";
      } catch (e) { return "err:" + e.message; }
    }, { h: html, p: plain });
    if (pasted === "clipboard") {
      await page.keyboard.press("Control+V");
    } else {
      // fallback: synthetic paste event straight into CKEditor
      await page.evaluate(({ h, p }) => {
        const el = document.querySelector('[data-tid="ckeditor"]'); el.focus();
        const dt = new DataTransfer(); dt.setData("text/html", h); dt.setData("text/plain", p);
        el.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
      }, { h: html, p: plain });
    }
    await page.waitForTimeout(1500);
    const shot = path.join(OUT, "last-post.png");
    await page.screenshot({ path: shot });
    process.stderr.write(`clipboard: ${pasted}; draft screenshot: ${shot}\n`);
    if (has("--send")) {
      await box.click();
      await page.keyboard.press("Control+Enter");   // "Send (Ctrl+Enter)" in this chat
      await page.waitForTimeout(3000);
      const shot2 = path.join(OUT, "last-post-sent.png");
      await page.screenshot({ path: shot2 });
      process.stderr.write(`SENT (Ctrl+Enter). post-send screenshot: ${shot2}\n`);
    } else {
      process.stderr.write("DRAFT only — not sent. Add --send to post.\n");
    }
    await done(0);
  }

  // --- EDIT mode: edit my own existing message in place; --save to commit ---
  if (has("--edit")) {
    const htmlFile = arg("--html-file");
    const html = (htmlFile ? fs.readFileSync(htmlFile, "utf8") : arg("--html") || "").trim();
    if (!html) { process.stderr.write("need --html-file <path> or --html\n"); await done(1); }
    const match = arg("--match") || "my DSU"; // text that identifies my message to edit
    await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: "https://teams.microsoft.com" });
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
    for (const rx of [/use the web app/i, /continue on this browser/i]) {
      try { await page.getByRole("button", { name: rx }).first().click({ timeout: 2500 }); break; } catch {}
    }
    await page.waitForTimeout(3000);
    if (/login\.(microsoftonline|live)\.com/.test(page.url())) { process.stderr.write("Not logged in — run --login\n"); await done(2); }
    await page.waitForSelector('[data-tid="chat-pane-item"]', { timeout: 60000 });
    // wait until the target message actually renders (avoids a load-timing race)
    try {
      await page.waitForFunction((m) => [...document.querySelectorAll('[data-tid="chat-pane-item"]')].some((it) => (it.textContent || "").includes(m) && /\]\(http/.test(it.textContent || "")), match, { timeout: 30000 });
    } catch {}
    await page.waitForTimeout(1000);
    // find target, scroll it into the custom viewport, return a stable data-mid handle
    const mid = await page.evaluate((m) => {
      const items = [...document.querySelectorAll('[data-tid="chat-pane-item"]')];
      for (let i = items.length - 1; i >= 0; i--) {
        const t = items[i].textContent || "";
        if (t.includes(m) && /\]\(http/.test(t)) {
          items[i].scrollIntoView({ block: "center" });
          const msg = items[i].querySelector('[data-tid="chat-pane-message"]');
          return msg ? msg.getAttribute("data-mid") : "";
        }
      }
      return null;
    }, match);
    if (mid === null) { process.stderr.write(`No message matching "${match}" with raw markdown found.\n`); await done(3); }
    process.stderr.write(`[1] found mid=${mid}\n`);
    await page.waitForTimeout(1200);
    const bubble = page.locator(`[data-mid="${mid}"]`);
    const item = page.locator('[data-tid="chat-pane-item"]').filter({ has: bubble });
    await item.hover();
    await page.waitForTimeout(900);
    process.stderr.write("[2] hovered row\n");
    await page.click('[data-tid="message-actions-edit"]', { timeout: 15000 }); // single floating toolbar button
    process.stderr.write("[3] clicked edit\n");
    await page.waitForTimeout(1200);
    const editor = item.locator('[contenteditable="true"]').first();
    await editor.click({ timeout: 8000 });
    process.stderr.write("[4] editor focused\n");
    await page.keyboard.press("Control+A");
    await page.keyboard.press("Delete");
    await page.waitForTimeout(300);
    const plain = html.replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, "");
    const pasted = await page.evaluate(async ({ h, p }) => {
      try { await navigator.clipboard.write([new ClipboardItem({ "text/html": new Blob([h], { type: "text/html" }), "text/plain": new Blob([p], { type: "text/plain" }) })]); return "clipboard"; }
      catch (e) { return "err:" + e.message; }
    }, { h: html, p: plain });
    if (pasted === "clipboard") { await page.keyboard.press("Control+V"); }
    else { await page.evaluate(({ h, p }) => { const el = document.activeElement; const dt = new DataTransfer(); dt.setData("text/html", h); dt.setData("text/plain", p); el.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true })); }, { h: html, p: plain }); }
    await page.waitForTimeout(1200);
    const shot = path.join(OUT, "last-edit.png");
    await page.screenshot({ path: shot });
    // discover the save/cancel controls that appear in edit mode
    const ctrls = await page.evaluate(() => [...document.querySelectorAll("button")]
      .filter((b) => /save|done|update|edit|cancel/i.test((b.getAttribute("aria-label") || "") + "|" + (b.getAttribute("data-tid") || "")))
      .map((b) => ({ tid: b.getAttribute("data-tid"), aria: (b.getAttribute("aria-label") || "").slice(0, 40) })).slice(0, 12));
    process.stderr.write(`clipboard: ${pasted}; edit screenshot: ${shot}\nedit controls: ${JSON.stringify(ctrls)}\n`);
    if (has("--save")) {
      await editor.click();                       // ensure the edit editor is focused
      await page.keyboard.press("Control+Enter");  // "Done (Ctrl+Enter)" saves the edit
      await page.waitForTimeout(3000);
      const shot2 = path.join(OUT, "last-edit-saved.png");
      await page.screenshot({ path: shot2 });
      process.stderr.write(`SAVED (Ctrl+Enter). post-save screenshot: ${shot2}\n`);
    } else {
      process.stderr.write("EDIT DRAFT only — not saved (context will discard it).\n");
    }
    await done(0);
  }

  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  for (const rx of [/use the web app/i, /continue on this browser/i, /open teams on the web/i]) {
    try { await page.getByRole("button", { name: rx }).first().click({ timeout: 2500 }); break; } catch {}
  }
  await page.waitForTimeout(3000);
  if (/login\.(microsoftonline|live)\.com/.test(page.url())) {
    process.stderr.write("Not logged in — run: node teams-read.js --login\n"); await done(2);
  }
  try { await page.waitForSelector('[data-tid="chat-pane-item"]', { timeout: 60000 }); }
  catch { process.stderr.write("No messages rendered. Re-run with --dump to inspect.\n"); }
  await page.waitForTimeout(2000);

  if (has("--dump")) {
    const shot = path.join(OUT, "last-dump.png");
    await page.screenshot({ path: shot });
    const text = await page.evaluate(() => (document.querySelector('[data-tid="message-pane-list-viewport"]') || document.body).innerText);
    process.stderr.write(`screenshot: ${shot}\n`);
    process.stdout.write(text.slice(0, 8000) + "\n");
    await done(0);
  }

  // Accumulate across scroll steps (virtualized list): key on unique datetime.
  const acc = new Map();
  const merge = (batch) => { for (const m of batch) { const k = m.datetime || m.author + "|" + m.text.slice(0, 60); if (!acc.has(k)) acc.set(k, m); } };
  const oldestMs = () => { let o = null; for (const m of acc.values()) if (m.datetime) { const t = Date.parse(m.datetime); if (o === null || t < o) o = t; } return o; };

  merge(await page.evaluate(EXTRACT));
  if (days) {
    const cutoff = Date.now() - days * 86400000;
    let stagnant = 0;
    for (let i = 0; i < 100 && stagnant < 4; i++) {
      const o = oldestMs();
      if (o !== null && o <= cutoff) break;
      const before = acc.size;
      await page.evaluate(() => { const s = document.querySelector('[data-tid="message-pane-list-viewport"]'); if (s) s.scrollTo(0, 0); });
      await page.waitForTimeout(1400);
      merge(await page.evaluate(EXTRACT));
      stagnant = acc.size > before ? 0 : stagnant + 1;
      process.stderr.write(`  scroll ${i + 1}: ${acc.size} messages loaded (oldest ${new Date(oldestMs()).toISOString().slice(0, 10)})\n`);
    }
  }

  let msgs = [...acc.values()];
  if (days) { const cutoff = Date.now() - days * 86400000; msgs = msgs.filter((m) => !m.datetime || Date.parse(m.datetime) >= cutoff); }
  if (author) msgs = msgs.filter((m) => m.author.toLowerCase().includes(author.toLowerCase()));
  msgs.sort((a, b) => (a.datetime || "").localeCompare(b.datetime || ""));

  if (has("--json")) { process.stdout.write(JSON.stringify(msgs, null, 2) + "\n"); await done(0); }
  if (!msgs.length) { process.stderr.write("No messages matched.\n"); await done(0); }
  for (const m of msgs) process.stdout.write(`\n[${fmt(m.datetime)}] ${m.author}\n${m.text}\n`);
  await done(0);
})().catch((e) => { process.stderr.write("ERROR: " + e.message + "\n"); process.exit(1); });

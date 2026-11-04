// Discover how to EDIT the user's own DSU message. Opens the message's "More options"
// menu and dumps the items. Does NOT click Edit or change anything.
const { chromium } = require("playwright-core");
const path = require("path"), os = require("os");
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PROFILE = path.join(os.homedir(), ".teams-reader-profile");
const url = process.argv[2];

(async () => {
  const ctx = await chromium.launchPersistentContext(PROFILE, {
    headless: true, executablePath: CHROME, viewport: { width: 1360, height: 940 },
  });
  const page = ctx.pages()[0] || (await ctx.newPage());
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  for (const rx of [/use the web app/i, /continue on this browser/i]) {
    try { await page.getByRole("button", { name: rx }).first().click({ timeout: 2500 }); break; } catch {}
  }
  await page.waitForTimeout(7000);

  // locate the target message: my own DSU that still has raw markdown "](http"
  const idx = await page.evaluate(() => {
    const items = [...document.querySelectorAll('[data-tid="chat-pane-item"]')];
    for (let i = items.length - 1; i >= 0; i--) {
      const t = items[i].innerText || "";
      if (/my DSU/i.test(t) && /\]\(http/.test(t)) return i;
    }
    return -1;
  });
  if (idx < 0) { console.log(JSON.stringify({ error: "target DSU message not found" })); await ctx.close(); return; }

  const item = page.locator('[data-tid="chat-pane-item"]').nth(idx);
  await item.scrollIntoViewIfNeeded();
  await item.hover();
  await page.waitForTimeout(800);

  // buttons revealed on hover (the message action bar)
  const bar = await page.evaluate((i) => {
    const it = [...document.querySelectorAll('[data-tid="chat-pane-item"]')][i];
    const btns = [...document.querySelectorAll("button")].filter((b) => {
      const r = b.getBoundingClientRect(); const ir = it.getBoundingClientRect();
      return r.bottom > ir.top - 40 && r.top < ir.bottom + 40 && (b.getAttribute("aria-label") || b.getAttribute("data-tid"));
    });
    return btns.slice(0, 14).map((b) => ({ tid: b.getAttribute("data-tid"), aria: (b.getAttribute("aria-label") || "").slice(0, 40) }));
  }, idx);

  // open "More options" and dump the menu
  let menu = [];
  try {
    await page.getByRole("button", { name: /more options/i }).first().click({ timeout: 3000 });
    await page.waitForTimeout(700);
    menu = await page.evaluate(() => [...document.querySelectorAll('[role="menuitem"]')].map((m) => ({ tid: m.getAttribute("data-tid"), text: (m.innerText || "").slice(0, 30) })).slice(0, 20));
  } catch (e) { menu = ["more-options click failed: " + e.message]; }

  console.log(JSON.stringify({ targetIdx: idx, actionBar: bar, menu }, null, 2));
  await ctx.close();
})().catch((e) => { console.error("ERR", e.message); process.exit(1); });

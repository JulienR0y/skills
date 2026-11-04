// Discover the Teams compose box + send button selectors (does NOT send anything).
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

  const info = await page.evaluate(() => {
    const dump = (el) => el ? { tag: el.tagName, tid: el.getAttribute("data-tid"), role: el.getAttribute("role"), aria: (el.getAttribute("aria-label") || "").slice(0, 60), ce: el.getAttribute("contenteditable"), ph: el.getAttribute("data-placeholder") } : null;
    const out = {};
    // compose box candidates
    out.editors = [...document.querySelectorAll('[contenteditable="true"], [role="textbox"], [data-tid*="ckeditor"], [data-tid*="messageEntry"]')].slice(0, 6).map(dump);
    // send button candidates
    out.sendButtons = [...document.querySelectorAll('button[name="send"], [data-tid*="send"], button[aria-label*="Send" i], button[title*="Send" i]')].slice(0, 6).map(dump);
    return out;
  });
  console.log(JSON.stringify(info, null, 2));
  await ctx.close();
})().catch((e) => { console.error("ERR", e.message); process.exit(1); });

// Discover the internal structure of a chat-pane-item + the message-pane scroller.
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
    const items = [...document.querySelectorAll('[data-tid="chat-pane-item"]')];
    const sample = items.slice(-4).map((it) => {
      const tids = [...new Set([...it.querySelectorAll("[data-tid]")].map((e) => e.getAttribute("data-tid")))];
      const timeEl = it.querySelector("time");
      return {
        aria: (it.getAttribute("aria-label") || "").slice(0, 80),
        descendantTids: tids.slice(0, 25),
        time: timeEl ? { datetime: timeEl.getAttribute("datetime"), text: timeEl.textContent.trim() } : null,
        anyDatetimeAttr: (() => { const e = it.querySelector("[datetime]"); return e ? e.getAttribute("datetime") : null; })(),
        innerText: it.innerText.replace(/\s+/g, " ").trim().slice(0, 160),
      };
    });
    // message-pane scroller = first scrollable ancestor of a chat-pane-item
    let scroller = null;
    const it0 = items[0];
    if (it0) {
      let el = it0.parentElement, d = 0;
      while (el && d < 20) {
        const oy = getComputedStyle(el).overflowY;
        if ((oy === "auto" || oy === "scroll") && el.scrollHeight > el.clientHeight + 50) {
          scroller = { tid: el.getAttribute("data-tid"), role: el.getAttribute("role"), aria: (el.getAttribute("aria-label") || "").slice(0, 50), cls: (el.className || "").toString().slice(0, 50) };
          break;
        }
        el = el.parentElement; d++;
      }
    }
    return { total: items.length, sample, scroller };
  });
  console.log(JSON.stringify(info, null, 2));
  await ctx.close();
})().catch((e) => { console.error("ERR", e.message); process.exit(1); });

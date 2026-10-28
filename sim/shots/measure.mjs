// Measure elements on one screen of the served sim (sim/serve.sh; SIM_URL to change it).
//
//   node sim/shots/measure.mjs [--width 390] [--text 130] [--click TEXT]... ROUTE SELECTOR...
//
// For each SELECTOR, every visible match's top, height, vertical middle, width and
// computed font-size, in CSS px: to check that an icon sits on its text's centre line,
// or that two controls are the same height. --click clicks a button or link with that
// name first (in order, for example --click Edit --click Tags); --text 130 sets the root
// font-size to 22.1px, as the phone's font size at 130% does.
import { createRequire } from "node:module";

const require = createRequire(new URL("../../web/package.json", import.meta.url));
const { chromium } = require("@playwright/test");
const base = process.env.SIM_URL || "http://127.0.0.1:9100/art/x1/index.html";

let width = 390;
let text = "100";
const clicks = [];
const rest = [];
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === "--width") width = Number(argv[++i]);
  else if (argv[i] === "--text") text = argv[++i];
  else if (argv[i] === "--click") clicks.push(argv[++i]);
  else rest.push(argv[i]);
}
const [route = "/", ...selectors] = rest;

const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width, height: 844 }, hasTouch: true });
const page = await ctx.newPage();
await page.goto(`${base}#${route.replace(/^#/, "")}`);
await page.waitForTimeout(1300);
const big = text === "130" ? "html{font-size:22.1px!important}" : "";
await page.addStyleTag({ content: `.sim-fb{display:none!important}${big}` });
for (const c of clicks) {
  await page
    .getByRole("button", { name: c })
    .or(page.getByRole("link", { name: c }))
    .or(page.locator("summary", { hasText: c }))
    .first()
    .click();
  await page.waitForTimeout(600);
}
for (const sel of selectors) {
  const rows = await page.evaluate((sel) => {
    return [...document.querySelectorAll(sel)]
      .filter((e) => e.getClientRects().length)
      .map((e) => {
        const r = e.getBoundingClientRect();
        const n = (x) => Math.round(x * 10) / 10;
        return { top: n(r.top), height: n(r.height), mid: n(r.top + r.height / 2), width: n(r.width), font: getComputedStyle(e).fontSize };
      });
  }, sel);
  console.log(sel, rows.length ? "" : "(none shown)");
  for (const r of rows) console.log(`  top ${r.top}  height ${r.height}  mid ${r.mid}  width ${r.width}  font ${r.font}`);
}
await b.close();

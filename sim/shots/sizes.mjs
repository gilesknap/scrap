// node sim/shots/sizes.mjs [label]: the type-size audit, against the served sim (sim/serve.sh;
// SIM_URL to change it). The computed font-size and drawn height of every editing chip and field
// (the page editor's Due and Tags folds, Search's Filters panel) beside the Related links and the
// page's own chips, at 100% and 130% text, 390 px; flags any editing chip or field larger than --t-sm.
import { createRequire } from "node:module";
const require = createRequire(new URL("../../web/package.json", import.meta.url));
const { chromium } = require("@playwright/test");
const base = process.env.SIM_URL || "http://127.0.0.1:9100/art/x1/index.html";
const SLUG = "pick-a-developer-portal-for-the-controls-group";
const label = process.argv[2] || "";
const b = await chromium.launch();
let bad = 0;
for (const size of [100, 130]) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true });
  const p = await ctx.newPage();
  const go = async (h) => {
    await p.goto("about:blank"); await p.goto(base + h); await p.waitForTimeout(1300);
    await p.addStyleTag({ content: `.sim-fb{display:none!important}${size === 130 ? "html{font-size:22.1px!important}" : ""}` });
    await p.waitForTimeout(300);
  };
  // [name, selector, editing?]
  const read = (groups) => p.evaluate((groups) => {
    const probe = document.createElement("span");
    probe.style.fontSize = "var(--t-sm)";
    document.body.append(probe);
    const tsm = parseFloat(getComputedStyle(probe).fontSize);
    probe.remove();
    const out = [];
    for (const [name, sel, editing] of groups) {
      const els = [...document.querySelectorAll(sel)].filter((e) => e.getClientRects().length);
      if (!els.length) { out.push({ name, n: 0 }); continue; }
      const fs = new Set(), drawn = new Set(), box = new Set();
      for (const e of els) {
        const s = getComputedStyle(e);
        fs.add(parseFloat(s.fontSize));
        const r = e.getBoundingClientRect();
        box.add(Math.round(r.height));
        // drawn: less transparent top and bottom borders (a pill drawn inside its target)
        const clear = (w, c) => (/rgba\(0, 0, 0, 0\)|transparent/.test(c) ? parseFloat(w) : 0);
        drawn.add(Math.round(r.height - clear(s.borderTopWidth, s.borderTopColor) - clear(s.borderBottomWidth, s.borderBottomColor)));
      }
      const max = Math.max(...fs);
      out.push({ name, n: els.length, fontPx: [...fs].join("/"), drawnPx: [...drawn].join("/"), targetPx: [...box].join("/"), editing, big: editing && max > tsm + 0.05 });
    }
    return { tsm, out };
  }, groups);
  const report = (state, r) => {
    console.log(`\n${label} ${size}% · ${state} · --t-sm = ${r.tsm}px`);
    for (const x of r.out) {
      if (!x.n) { console.log(`  ${x.name.padEnd(26)} (none shown)`); continue; }
      if (x.big) bad++;
      console.log(`  ${x.name.padEnd(26)} ${String(x.fontPx).padStart(6)}px  drawn ${String(x.drawnPx).padStart(7)}  target ${String(x.targetPx).padStart(7)}  ×${x.n}${x.big ? "  << LARGER THAN --t-sm" : ""}`);
    }
  };
  const common = [
    ["Related links", ".related a", false],
    ["Page chips (read mode)", ".page > .tags :is(a, button)", false],
  ];
  // Read mode: the sizes the editing chips should match
  await go(`#/p/${SLUG}`);
  report("page, read mode", await read(common));
  // The page editor (Edit), its Due fold open
  const edit = async () => {
    await go(`#/p/${SLUG}`);
    await p.locator(".page > .tools button", { hasText: "Edit" }).click(); await p.waitForTimeout(900);
  };
  await edit();
  await p.locator(".editor .fold summary", { hasText: "Due" }).click(); await p.waitForTimeout(300);
  report("page editor, Due fold", await read([
    ["Due chips", ".editor .todoedit > .soon .facet", true],
    ["Priority select", ".editor .todoedit select", true],
  ]));
  // Its Tags fold
  await edit();
  await p.locator(".editor .fold summary", { hasText: "Tags" }).click(); await p.waitForTimeout(900);
  report("page editor, Tags fold", await read([
    ["Picker: chosen", ".editor .tagedit .facet.on", true],
    ["Picker: offered", ".editor .tagedit .offers .facet", true],
    ["Picker: Add a tag box", ".editor .tagedit input", true],
  ]));
  // Search, Filters open, one tag on
  await go("#/search?q=" + encodeURIComponent("controls tag:kind/project-management"));
  await p.getByRole("button", { name: /^Filters/ }).click(); await p.waitForTimeout(800);
  await p.evaluate(() => p = document.querySelector(".fpanel details:not([open]) > summary")?.click()).catch(() => {});
  await p.waitForTimeout(300);
  report("search, Filters open", await read([
    ["Filters: tag offers", ".fpanel .offers .facet", true],
    ["Filters: Add a tag box", ".fpanel input[type=text], .fpanel input:not([type])", true],
    ["Filters: When/Order/Group", ".fpanel .frow:not(.ftags) .facet", true],
    ["Filters on (under kinds)", ".fon .facet", true],
  ]));
  await ctx.close();
}
console.log(`\n${bad ? `${bad} group(s) larger than --t-sm` : "no editing chip larger than --t-sm"}`);
await b.close();

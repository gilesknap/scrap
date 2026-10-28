// Screenshots of the served sim (sim/serve.sh), one per route, width, text size and scheme.
//
//   node sim/shots/shot.mjs [options] ROUTE...
//
// ROUTE is the app's address after the hash, such as "/" or "/p/embedded-items-test"
// or "/search?q=tag:person group:letter" (a leading # is optional). Options:
//   --width 308,320,390    viewport widths in CSS px (default 390; height 844)
//   --text 100,130         text size: 130 sets the root font-size to 22.1px, as the
//                          phone's font size at 130% does (default 100)
//   --scheme light,dark    colour scheme (default light)
//   --out DIR              where the PNGs go (default sim/out-shots), named
//                          <route>-<width>-<text>-<scheme>.png
//   --full                 the whole page, not just the first screen
//   --wait MS              settle time after load (default 1500)
//   --base URL             the sim (default http://127.0.0.1:9100/art/x1/index.html)
// The sim's Feedback tab is hidden; page errors are printed (not the service worker's).
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../../web/package.json", import.meta.url));
const { chromium } = require("@playwright/test");

const opt = {
  width: "390",
  text: "100",
  scheme: "light",
  out: fileURLToPath(new URL("../out-shots", import.meta.url)),
  wait: "1500",
  base: "http://127.0.0.1:9100/art/x1/index.html",
};
const routes = [];
let full = false;
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--full") full = true;
  else if (a.startsWith("--")) opt[a.slice(2)] = argv[++i];
  else routes.push(a.replace(/^#/, ""));
}
if (!routes.length) routes.push("/");
const list = (s) => s.split(",").filter(Boolean);
const name = (r) => r.replace(/^\//, "").replace(/[^\w-]+/g, "_").replace(/^_+|_+$/g, "") || "home";
mkdirSync(opt.out, { recursive: true });

const browser = await chromium.launch();
for (const scheme of list(opt.scheme)) {
  for (const w of list(opt.width).map(Number)) {
    const ctx = await browser.newContext({
      viewport: { width: w, height: 844 },
      deviceScaleFactor: 2,
      hasTouch: true,
      colorScheme: scheme,
    });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => {
      // sim/build.sh drops sw.js: the app's registration fails, as in the artifact
      if (!/ServiceWorker/.test(e.message)) console.log("pageerror", e.message);
    });
    for (const text of list(opt.text)) {
      for (const r of routes) {
        await page.goto("about:blank");
        await page.goto(`${opt.base}#${r.startsWith("/") ? r : `/${r}`}`);
        await page.waitForTimeout(Number(opt.wait));
        const big = text === "130" ? "html{font-size:22.1px!important}" : "";
        await page.addStyleTag({
          content: `.sim-fb{display:none!important}${big}*{animation:none!important;transition:none!important;caret-color:transparent!important}`,
        });
        await page.waitForTimeout(300);
        const path = join(opt.out, `${name(r)}-${w}-${text}-${scheme}.png`);
        await page.screenshot({ path, fullPage: full });
        console.log(path);
      }
    }
    await ctx.close();
  }
}
await browser.close();

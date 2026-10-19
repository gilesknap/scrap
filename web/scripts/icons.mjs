// Render the PNG icons from public/icon.svg (run after changing it: npm run icons).
import { readFileSync } from "node:fs";
import { chromium } from "@playwright/test";

const svg = readFileSync("public/icon.svg", "utf8");
const browser = await chromium.launch();
const page = await browser.newPage();
for (const [name, size, rx] of [
  ["icon-192", 192, 96],
  ["icon-512", 512, 96],
  ["icon-maskable", 512, 0],
]) {
  await page.setViewportSize({ width: size, height: size });
  const scaled = svg
    .replace('rx="96"', `rx="${rx}"`)
    .replace("<svg ", `<svg width="${size}" height="${size}" `);
  await page.setContent(`<body style="margin:0;background:transparent">${scaled}</body>`);
  await page.screenshot({ path: `public/${name}.png`, omitBackground: true });
}
await browser.close();

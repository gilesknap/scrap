// Maths in page text (render.ts, mathrules.ts; drawn by KaTeX in math.ts, a chunk loaded only
// for a page with maths): $...$, $$...$$ and ```math draw in the page and in Preview, a
// mistake shows its TeX, money stays text, and a page without maths loads no KaTeX. Nothing in
// the console, and no Content-Security-Policy report (its CSS and fonts are scrap's own).
// Share's HTML file has the TeX as typed. Named to run after smoke.spec.ts (an empty store).
import { readFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";
import { ulid } from "./helpers";

async function note(page: Page, text: string): Promise<string> {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text } });
  return (await r.json()).slug as string;
}

/** Console errors, page errors and failed requests. */
function problems(page: Page) {
  const seen: string[] = [];
  page.on("pageerror", (e) => seen.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error" || /Content Security Policy|Refused to/i.test(m.text()))
      seen.push(m.text());
  });
  page.on("requestfailed", (r) => seen.push(`${r.url()} ${r.failure()?.errorText}`));
  return seen;
}

/** The KaTeX files the page has fetched (its chunk, CSS or fonts). */
const katexLoaded = (page: Page) =>
  page.evaluate(() =>
    performance
      .getEntriesByType("resource")
      .map((e) => e.name)
      .filter((n) => /\/assets\/(math|katex|KaTeX_)[\w-]*\./.test(n)),
  );

test("maths draws in the page and in Preview; a mistake shows its TeX", async ({ page }) => {
  const seen = problems(page);
  // A phone that shares, but not this file: Share saves it
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "canShare", { value: () => false });
    Object.defineProperty(navigator, "share", { value: async () => {} });
  });
  const slug = await note(
    page,
    [
      "Maths homework",
      "",
      "Inline $a_1^2 + b_1^2$ and [[not-a-link]] outside.",
      "",
      "$$",
      "\\frac{1}{2} \\times \\frac{3}{4}",
      "$$",
      "",
      "```math",
      "\\begin{aligned} x &= 1 \\\\ y &= 2 \\end{aligned}",
      "```",
      "",
      "Broken: $\\frac{1}{$ here.",
    ].join("\n"),
  );
  await page.goto(`/p/${slug}`);
  const body = page.locator(".body.md");
  await expect(body.locator(".math .katex")).toHaveCount(3);
  await expect(body.locator(".math.display .katex-display")).toHaveCount(2);
  await expect(body.locator("code.language-math")).toHaveCount(0); // drawn in its place
  // KaTeX's fonts load (scrap's own files, under the policy)
  const fontLoaded = () =>
    page.evaluate(() =>
      [...document.fonts].some((f) => f.family.includes("KaTeX_Main") && f.status === "loaded"),
    );
  await expect.poll(fontLoaded).toBe(true);
  // _ in the formula is TeX, not emphasis
  await expect(body.locator("em")).toHaveCount(0);
  await expect(body.locator("a[href='/p/not-a-link']")).toHaveCount(1);
  // The mistake: its TeX as typed, the page drawn around it
  await expect(body.locator(".math-error")).toHaveText("\\frac{1}{");
  await expect(body).toContainText("here.");
  expect(await katexLoaded(page)).not.toEqual([]); // so the check below sees a load

  // Share > HTML: the formulas as their TeX, not KaTeX's markup (it needs its CSS)
  await page.getByRole("button", { name: "Share" }).click();
  const saved = page.waitForEvent("download");
  await page.getByRole("button", { name: "HTML" }).click();
  const html = readFileSync((await (await saved).path()) as string, "utf8");
  expect(html).toContain('<code class="math">$a_1^2 + b_1^2$</code>');
  expect(html).toContain("$$\n\\frac{1}{2} \\times \\frac{3}{4}\n$$");
  expect(html).not.toContain("katex");
  await page.keyboard.press("Escape");

  await page.locator(".page .tools").getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Body").fill("Preview $x^2$");
  await page.locator(".editor").getByRole("button", { name: "Preview" }).click();
  await expect(page.locator(".editor .preview .math .katex")).toHaveCount(1);
  expect(seen).toEqual([]);
});

test("money stays text, and a page without maths loads no KaTeX", async ({ page }) => {
  const seen = problems(page);
  const money = await note(page, "Shopping\n\nIt cost $5 and $10, or $10-$20.");
  await page.goto(`/p/${money}`);
  const body = page.locator(".body.md");
  await expect(body).toContainText("It cost $5 and $10, or $10-$20.");
  await expect(body.locator(".math, .katex")).toHaveCount(0);
  expect(await katexLoaded(page)).toEqual([]);

  const plain = await note(page, "Plain page\n\nNo **maths** here.");
  await page.goto(`/p/${plain}`);
  await expect(page.locator(".body.md strong")).toHaveText("maths");
  await page.waitForTimeout(500); // anything the page would load for it has started
  expect(await katexLoaded(page)).toEqual([]);
  expect(seen).toEqual([]);
});

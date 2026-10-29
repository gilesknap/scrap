// Share > HTML (pagehtml.ts): the saved file shows the page's Markdown as elements, also in
// Claude's summary (plain text on the screen), and loads with the network blocked (#427).
// Named to run after smoke.spec.ts, which wants an empty store.
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

const BODY =
  "# Plan\n\n## Heading two\n\nSome **bold** and a [link](https://example.com).\n\n- one\n- two\n\n```\ncode here\n```\n\n- [ ] todo a\n- [x] todo b\n";

test("Share > HTML renders Markdown in the body and the summary, offline", async ({
  page,
  browser,
}) => {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text: BODY } });
  const n = (await r.json()) as { slug: string };
  await page.route(`**/api/pages/${n.slug}`, async (rt) => {
    if (rt.request().method() !== "GET") return rt.continue();
    const json = await (await rt.fetch()).json();
    const summary =
      "A **bold** summary and [a site](https://example.com/s)\n\n- item one\n- item two";
    await rt.fulfill({
      json: { ...json, enrich: { on: true, error: null, state: "done", summary } },
    });
  });
  // A phone that shares, but not this file: Share saves it
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "canShare", { value: () => false });
    Object.defineProperty(navigator, "share", { value: async () => {} });
  });
  await page.goto(`/p/${n.slug}`);
  await page.getByRole("button", { name: "Share" }).click();
  const saved = page.waitForEvent("download");
  await page.getByRole("button", { name: "HTML" }).click();
  const html = readFileSync((await (await saved).path()) as string, "utf8");

  const ctx = await browser.newContext({ offline: true });
  const file = await ctx.newPage();
  await file.setContent(html);
  await expect(file.locator("h2")).toHaveText("Heading two");
  await expect(file.locator("strong")).toHaveCount(2); // body and summary
  await expect(file.locator("pre code")).toContainText("code here");
  await expect(file.locator(".summary li")).toHaveText(["item one", "item two"]);
  await expect(file.locator(".summary a")).toHaveAttribute("href", "https://example.com/s");
  const text = await file.locator("body").innerText();
  expect(text).not.toMatch(/\*\*|##|```/);
  // The meta line's parts are told apart in the file's text too (#431), not "Note1 of 2"
  expect(await file.locator(".meta").first().innerText()).toMatch(/\S · \S/);
  if (process.env.SHOT) await file.screenshot({ path: process.env.SHOT });
  await ctx.close();
});

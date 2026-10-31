// Share's menu on a computer with no share sheet (Firefox, Chrome on Linux): it copies the
// link, the Markdown or the page as rich text, prints, and downloads the page as HTML or as
// its file (clipboard.ts, sharing.ts). Named to run after smoke.spec.ts, which wants an empty
// store.
import { readFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";
import { ulid } from "../src/ulid";

const BODY = "Desk share\n\nSome **bold** and a [link](https://example.com).\n\n- one\n- two\n";

test.use({
  viewport: { width: 1280, height: 900 },
  isMobile: false,
  hasTouch: false,
  permissions: ["clipboard-read", "clipboard-write"],
});

async function open(page: Page) {
  await page.addInitScript(() => {
    // No share sheet, as on Firefox; print() counted, not shown
    delete (Navigator.prototype as Partial<Navigator>).share;
    delete (Navigator.prototype as Partial<Navigator>).canShare;
    const w = window as unknown as { printed: number };
    w.printed = 0;
    window.print = () => void w.printed++;
  });
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text: BODY } });
  const { slug, page_id } = (await r.json()) as { slug: string; page_id: string };
  await page.goto(`/p/${slug}`);
  const menu = page.locator(".share-menu");
  const share = async () => {
    await page.locator(".page > .tools").getByRole("button", { name: "Share" }).click();
    await expect(menu).toBeVisible();
    return menu;
  };
  return { slug, page_id, menu, share };
}

const clip = (page: Page, type: string) =>
  page.evaluate(async (t) => {
    for (const item of await navigator.clipboard.read())
      if (item.types.includes(t)) return (await item.getType(t)).text();
    return null;
  }, type);

test("Share on a computer copies, prints and downloads", async ({ page }) => {
  const { slug, page_id, menu, share } = await open(page);
  const tools = page.locator(".page > .tools");
  // Share in Download's place, and Download in its menu, once
  await expect(tools.getByRole("link", { name: "Download" })).toHaveCount(0);
  await share();
  await expect(menu.locator(":scope > *")).toHaveText([
    "Copy link",
    "Copy as Markdown",
    "Copy as rich text",
    "Print / Save as PDF",
    "Download HTML",
    "Download",
    "Pin to Search",
  ]);

  await menu.getByRole("button", { name: "Copy link" }).click();
  await expect(menu).toHaveCount(0);
  await expect(page.locator(".toast", { hasText: "Link copied" })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    new URL(`/p/${slug}`, page.url()).href,
  );

  await (await share()).getByRole("button", { name: "Copy as Markdown" }).click();
  await expect(page.locator(".toast", { hasText: "Markdown copied" })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(BODY.trimEnd());

  await (await share()).getByRole("button", { name: "Copy as rich text" }).click();
  await expect(page.locator(".toast", { hasText: "Rich text copied" })).toBeVisible();
  const html = (await clip(page, "text/html")) ?? "";
  expect(html).toContain("<strong>bold</strong>");
  expect(html).toContain('href="https://example.com/"'); // as the browser writes it
  expect(html).not.toMatch(/<button|Share|<style/);
  expect(await clip(page, "text/plain")).toBe(BODY.trimEnd());

  await (await share()).getByRole("button", { name: "Print / Save as PDF" }).click();
  await expect(menu).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { printed: number }).printed)).toBe(1);

  let saving = page.waitForEvent("download");
  await (await share()).getByRole("button", { name: "Download HTML" }).click();
  let file = await saving;
  expect(file.suggestedFilename()).toBe("Desk-share.html");
  expect(readFileSync((await file.path()) as string, "utf8")).toContain("<strong>bold</strong>");

  saving = page.waitForEvent("download");
  await (await share()).getByRole("link", { name: "Download" }).click();
  file = await saving;
  expect(file.suggestedFilename()).toMatch(/\.md$/);
  expect(readFileSync((await file.path()) as string, "utf8")).toContain("Some **bold**");
  // Deleted after, so other specs' counts of the store's pages hold
  expect((await page.request.delete(`/api/pages/${page_id}`)).ok()).toBe(true);
});

test("Copy as rich text falls back to plain text without ClipboardItem", async ({ page }) => {
  await page.addInitScript(() => {
    delete (window as Partial<Window & { ClipboardItem: unknown }>).ClipboardItem;
  });
  const { page_id, share } = await open(page);
  await (await share()).getByRole("button", { name: "Copy as rich text" }).click();
  await expect(page.locator(".toast", { hasText: "Text copied" })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(BODY.trimEnd());
  expect((await page.request.delete(`/api/pages/${page_id}`)).ok()).toBe(true);
});

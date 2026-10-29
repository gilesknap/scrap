// Settings > Export everything (#417): a plain link saving the whole store as a zip of
// Markdown (GET /api/store/download), each page as <slug>.md; the sheet stays open.
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { ulid } from "../src/ulid";

test("Export everything saves the store as a zip with each page's Markdown", async ({ page }) => {
  const title = `Exported page ${Date.now()}`;
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text: title } });
  expect(r.ok()).toBe(true);
  const { slug, page_id } = await r.json();

  await page.goto("/");
  await page.getByRole("button", { name: "Settings" }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  const link = dialog.getByRole("link", { name: "Export everything" });
  await expect(link).toHaveAttribute("href", "/api/store/download");
  await expect(link).toHaveAttribute("download", "");
  const box = (await link.boundingBox()) as { height: number };
  expect(box.height).toBeGreaterThanOrEqual(48);
  await expect(dialog).toContainText("opens as an Obsidian vault");

  const saving = page.waitForEvent("download");
  await link.click();
  const file = await saving;
  expect(file.suggestedFilename()).toMatch(/^scrap-export-\d{4}-\d\d-\d\d\.zip$/);
  const zip = readFileSync((await file.path()) as string);
  expect(zip.subarray(0, 2).toString()).toBe("PK");
  expect(zip.includes(Buffer.from(`${slug}.md`))).toBe(true); // names are not compressed
  await expect(dialog).toBeVisible(); // a download, not a screen: Settings stays open
  // Deleted after, so other specs' counts of the store's pages hold
  expect((await page.request.delete(`/api/pages/${page_id}`)).ok()).toBe(true);
});

// Store health (#262): Settings opens the screen, each check with its count from GET
// /api/health, and a tap lists the check's pages in Search. Runs after smoke.spec.ts.
import { expect, test } from "@playwright/test";
import { ulid } from "../src/ulid";
import { lowContrast } from "./contrast";

test("Settings opens Store health, and a check lists its pages", async ({ page }) => {
  const text = `Health check page\n\nIt links to [[no-such-page-${Date.now()}]].`;
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text } });
  expect(r.ok()).toBe(true);
  const { checks } = await (await page.request.get("/api/health")).json();
  const dangling = checks.find((c: { term: string }) => c.term === "has:dangling").count;
  expect(dangling).toBeGreaterThanOrEqual(1);

  await page.emulateMedia({ reducedMotion: "reduce" }); // no fade-in under the contrast check
  await page.goto("/");
  await page.getByRole("button", { name: "Settings" }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await dialog.getByRole("link", { name: "Store health" }).click();
  await expect(dialog).toHaveCount(0); // the sheet closes to open the screen
  await expect(page).toHaveURL(/\/health$/);
  await expect(page.getByRole("heading", { name: "Store health" })).toBeVisible();
  const rows = page.locator(".health .list li");
  await expect(rows).toHaveCount(6);
  await expect(rows.locator("strong")).toHaveText([
    "Orphans",
    "Untagged",
    "Stale todos",
    "Duplicates",
    "Dangling links",
    "Outdated",
  ]);
  const row = page.getByRole("link", { name: `Dangling links: ${dangling}` });
  await expect(row).toBeVisible();
  await expect(row).toHaveAccessibleDescription(/^A \[\[link\]\] to a page/);
  const box = (await row.boundingBox()) as { height: number };
  expect(box.height).toBeGreaterThanOrEqual(48);
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    expect(await page.evaluate(lowContrast, ""), colorScheme).toEqual([]);
  }

  await row.click();
  await expect(page).toHaveURL(/\/search\?q=has%3Adangling$/);
  await expect(page.locator(".hits li a strong", { hasText: "Health check page" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove Dangling links" })).toBeVisible();
  await page.goBack(); // Back comes back to the screen
  await expect(page.getByRole("heading", { name: "Store health" })).toBeVisible();
});

test("Store health opens cold from its address", async ({ page }) => {
  await page.goto("/health");
  await expect(page.getByRole("heading", { name: "Store health" })).toBeVisible();
  await expect(page.getByRole("link", { name: /^Orphans: \d+$/ })).toBeVisible();
});

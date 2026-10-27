// The Trash screen (#276): Settings opens it, each page in the trash says when it goes for
// good (GET /api/trash's purge_at), and Restore brings one back.
import { expect, test } from "@playwright/test";
import { ulid } from "../src/ulid";
import { lowContrast } from "./contrast";

test("Settings opens the Trash, which says when a page goes, and Restore brings it back", async ({
  page,
}) => {
  const title = `Trashed page ${Date.now()}`;
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text: title } });
  expect(r.ok()).toBe(true);
  const { page_id } = await r.json();
  expect((await page.request.delete(`/api/pages/${page_id}`)).ok()).toBe(true);
  const { days, results } = await (await page.request.get("/api/trash")).json();
  expect(days).toBe(30);
  const row = results.find((t: { id: string }) => t.id === page_id);
  expect(Date.parse(row.purge_at) - Date.parse(row.deleted_at)).toBe(30 * 86400_000);

  await page.emulateMedia({ reducedMotion: "reduce" }); // no fade-in under the contrast check
  await page.goto("/");
  await page.getByRole("button", { name: "Settings" }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await dialog.getByRole("link", { name: "Trash" }).click();
  await expect(dialog).toHaveCount(0); // the sheet closes to open the screen
  await expect(page).toHaveURL(/\/trash$/);
  await expect(page.getByRole("heading", { name: "Trash" })).toBeVisible();
  await expect(page.locator(".trash .hint")).toContainText("stay here for 30 days");
  const item = page.locator(".trash .list li", { hasText: title });
  await expect(item.locator("small")).toHaveText(/^Deleted\s.+\s·\sdeleted\sfor\sgood\safter\s.+$/); // parts hold their no-break spaces
  const restore = page.getByRole("button", { name: `Restore ${title}` });
  const box = (await restore.boundingBox()) as { height: number };
  expect(box.height).toBeGreaterThanOrEqual(48);
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    expect(await page.evaluate(lowContrast, ""), colorScheme).toEqual([]);
  }

  await restore.click();
  await expect(item).toHaveCount(0);
  const toast = page.locator(".toast", { hasText: `Restored: ${title}` });
  await expect(toast).toBeVisible();
  await toast.getByRole("button", { name: "Open" }).click();
  await expect(page).toHaveURL(/\/p\//);
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
});

test("the Trash opens cold from its address", async ({ page }) => {
  await page.goto("/trash");
  await expect(page.getByRole("heading", { name: "Trash" })).toBeVisible();
});

test("restoring the last page leaves the empty state with focus on the heading", async ({
  page,
}) => {
  await page.route("**/api/trash", (route) =>
    route.fulfill({
      json: {
        days: 30,
        total: 1,
        results: [
          {
            id: "01JZZZZZZZZZZZZZZZZZZZZZZZ",
            slug: "only-one",
            title: "Only one",
            kind: "note",
            deleted_at: "2026-10-20T09:00:00.000Z",
            topic: false,
            purge_at: "2020-01-01T00:00:00.000Z",
          },
        ],
      },
    }),
  );
  await page.route("**/api/pages/*/undelete", (route) => route.fulfill({ json: {} }));
  await page.goto("/trash");
  await expect(page.locator(".trash .list small")).toHaveText(
    /·\sdeleted\sfor\sgood\sat\sthe\snext\snightly\sclean-up$/,
  );
  await page.getByRole("button", { name: "Restore Only one" }).click();
  await expect(page.getByText("The trash is empty.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Trash" })).toBeFocused();
});

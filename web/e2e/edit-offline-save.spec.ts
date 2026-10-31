// Save in the page editor while offline (#436): a plain message, not the browser's "TypeError:
// Failed to fetch"; the editor stays open with the text as typed, and Save works once back online.
import { expect, test } from "@playwright/test";
import { ulid } from "./helpers";

test("an offline Save says so, keeps the text, and saves once back online", async ({ page }) => {
  const r = await page.request.post("/api/captures", {
    data: { id: ulid(), text: `Offline save ${ulid().slice(-6)}`, kind: "note" },
  });
  const made = (await r.json()) as { page_id: string; slug: string };
  try {
    await page.goto(`/p/${made.slug}`);
    await page.locator(".page > .tools").getByRole("button", { name: "Edit" }).click();
    const box = page.locator(".editor textarea");
    await box.fill("Typed while offline");
    await page.context().setOffline(true);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    const toast = page.locator(".toast");
    await expect(toast).toContainText("You're offline");
    await expect(toast).not.toContainText("TypeError");
    await expect(box).toHaveValue("Typed while offline");
    await page.context().setOffline(false);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(box).toBeHidden();
    await expect(page.locator(".page")).toContainText("Typed while offline");
  } finally {
    await page.context().setOffline(false);
    await page.request.delete(`/api/pages/${made.page_id}`);
  }
});

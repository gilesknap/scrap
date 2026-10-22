// Recent searches (handover item 2): the last ten run on this phone, under the empty box while
// it has focus. Named to sort after smoke.spec.ts, which wants an empty store.
import { expect, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};
async function make(page: Page, text: string) {
  await page.request.post("/api/captures", { data: { id: ulid(), text, kind: "note" } });
}
const recents = (page: Page) => page.getByRole("group", { name: "Recent searches" });
const rows = (page: Page) => recents(page).locator(".again");

test("the empty box shows the last searches: run again, forget one, clear all", async ({
  page,
}) => {
  await make(page, "Recent wombat");
  await make(page, "Recent echidna");
  await page.goto("/search");
  const box = page.getByRole("searchbox");
  await box.click();
  await expect(recents(page)).toHaveCount(0); // no history: no block at all
  await expect(page.getByText("Recent", { exact: true })).toHaveCount(0);

  // Run by Enter, and by opening a result
  await box.fill("wombat");
  await box.press("Enter");
  await expect(page).toHaveURL(/\/p\//);
  await page.goto("/search");
  await box.fill("echidna");
  await page.locator(".hits a").first().click();
  await page.goto("/search");
  // Not per keystroke: typing without running keeps nothing
  await box.fill("platyp");
  await box.fill("");
  await expect(rows(page)).toHaveText(["echidna", "wombat"]); // newest first, box focused
  // Hidden as soon as the box has text, and when it loses focus
  await box.fill("w");
  await expect(recents(page)).toHaveCount(0);
  await box.fill("");
  await expect(recents(page)).toBeVisible();
  await box.blur();
  await expect(recents(page)).toHaveCount(0);

  // Tapped: runs it, the list and the keyboard go
  await box.click();
  await rows(page).filter({ hasText: "wombat" }).click();
  await expect(box).toHaveValue("wombat");
  await expect(box).not.toBeFocused();
  await expect(page).toHaveURL(/\/search\?q=wombat$/);
  await expect(page.locator(".hits li a strong")).toHaveText(["Recent wombat"]);
  // Left 3 s with a result, it is kept again: to the top
  await expect
    .poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("scrap.searches") ?? "[]")), {
      timeout: 10_000, // it settles after 3 s
    })
    .toEqual(["wombat", "echidna"]);

  // ✕ forgets one, Clear all the rest; focus stays in the box
  await page.getByRole("button", { name: "Clear search" }).click();
  await box.click();
  await recents(page).getByRole("button", { name: "Remove echidna" }).click();
  await expect(rows(page)).toHaveText(["wombat"]);
  await expect(box).toBeFocused();
  await page.getByRole("button", { name: "Clear all" }).click();
  await expect(recents(page)).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("scrap.searches"))).toBeNull();
});

test("search works the same when the phone keeps nothing", async ({ page }) => {
  await make(page, "Recent bandicoot");
  await page.addInitScript(() => {
    const no = () => {
      throw new DOMException("blocked", "SecurityError");
    };
    Object.defineProperty(window, "localStorage", { get: no, configurable: true });
  });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/search");
  const box = page.getByRole("searchbox");
  await expect(box).toBeVisible(); // not a blank screen
  await box.fill("bandicoot");
  await expect(page.locator(".hits li a strong")).toHaveText(["Recent bandicoot"]);
  await box.press("Enter");
  await expect(page).toHaveURL(/\/p\//);
  await page.goto("/search");
  await box.click();
  await expect(recents(page)).toHaveCount(0);
  expect(errors).toEqual([]);
});

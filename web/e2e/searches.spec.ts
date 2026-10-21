// The last searches (searches.ts): under the empty box, on this phone only.
import { expect, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};
test.beforeAll(async ({ request }) => {
  for (const [text, kind] of [
    ["Echidna burrow notes", "note"],
    ["Echidna feeding todo", "todo"],
  ])
    await request.post("/api/captures", { data: { id: ulid(), text, kind } });
});

const recents = (page: Page) => page.getByRole("group", { name: "Recent searches" });
const box = (page: Page) => page.getByRole("searchbox");

test("the empty box shows the last searches: run again, forget one, clear all", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/search");
  await box(page).click();
  await expect(recents(page)).toHaveCount(0); // none yet
  // Typed keys are not searches: only one run is remembered
  await box(page).pressSequentially("echid");
  await box(page).press("Enter"); // run: remembered (and the first result opens)
  await expect(page).toHaveURL(/\/p\//);
  await page.goto("/search");
  // Left a moment with results: remembered too, with its filters
  await box(page).fill("echidna kind:todo");
  await expect(page.locator(".hits li")).toHaveCount(1);
  await page.waitForTimeout(3500);
  await page.goto("/search");
  await box(page).click();
  const runs = recents(page).locator(".again");
  await expect(runs).toHaveText(["echidna kind:todo", "echid"]); // newest first
  // Typing hides them; empty again shows them
  await box(page).pressSequentially("x");
  await expect(recents(page)).toHaveCount(0);
  await box(page).press("Backspace");
  await expect(runs).toHaveCount(2);
  // Tap one: run again
  await runs.first().click();
  await expect(box(page)).toHaveValue("echidna kind:todo");
  await expect(page.locator(".hits li a strong")).toHaveText(["Echidna feeding todo"]);
  await expect(recents(page)).toHaveCount(0);
  // ✕ forgets one; Clear all the rest
  await page.goto("/search");
  await box(page).click();
  await recents(page).getByRole("button", { name: "Remove echid", exact: true }).click();
  await expect(runs).toHaveText(["echidna kind:todo"]);
  await expect(box(page)).toBeFocused();
  await recents(page).getByRole("button", { name: "Clear all" }).click();
  await expect(recents(page)).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem("scrap.searches"))).toBeNull();
  expect(errors).toEqual([]);
});

test("search works the same when the phone keeps nothing", async ({ page }) => {
  await page.addInitScript(() => {
    const no = () => {
      throw new DOMException("denied", "SecurityError");
    };
    Object.defineProperty(window, "localStorage", { get: no });
  });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/search");
  await box(page).click();
  await box(page).fill("echidna");
  await expect(page.locator(".hits li")).toHaveCount(2);
  await box(page).press("Enter");
  await expect(page).toHaveURL(/\/p\//);
  await page.goto("/search");
  await box(page).click();
  await expect(recents(page)).toHaveCount(0);
  expect(errors).toEqual([]);
});

// Runs after smoke.spec.ts, which wants an empty store (files run in name order).
// The search screen's Filters: a short row (Filters, with how many are on, then the top
// tags), the count and the filters on above the list, and the Filters sheet: a modal at the
// bottom that edits the query at once, closed by Done, Escape, Back or a tap outside.
import { expect, type Page, test } from "@playwright/test";

let n = 0;
async function note(page: Page, text: string, tags: string[]) {
  const id = `01E2EF1T${String(++n).padStart(2, "0")}`.padEnd(26, "0");
  const r = await page.request.post("/api/captures", { data: { id, text } });
  const { page_id } = await r.json();
  await page.request.patch(`/api/pages/${page_id}`, { data: { tags } });
}

test.beforeAll(async ({ request }) => {
  const page = { request } as Page;
  await note(page, "Potoroo one", ["marsupial"]);
  await note(page, "Potoroo two", ["marsupial", "hop"]);
  await note(page, "Potoroo three", []);
});

const hits = (page: Page) => page.locator(".hits li a strong");
const row = (page: Page) => page.getByRole("group", { name: "Refine" });
const filtersChip = (page: Page) => row(page).getByRole("button", { name: /^Filters/ });
const sheet = (page: Page) => page.getByRole("dialog", { name: "Filters" });

test("the row starts with Filters alone, then tags; the count and filters sit above the list", async ({
  page,
}) => {
  await page.goto("/search?q=potoroo");
  await expect(hits(page)).toHaveCount(3);
  await expect(row(page).locator(":scope > *")).toHaveText(["Filters", /^#marsupial/, /^#hop/]);
  await expect(page.locator(".found")).toHaveText("3 pages");
  await row(page).getByRole("button", { name: "#marsupial 2" }).click();
  await expect(hits(page)).toHaveCount(2);
  // The filter on: a chip above the list, and a count on Filters; the row's start stays put
  await expect(filtersChip(page)).toHaveAccessibleName("Filters, 1 on");
  await expect(filtersChip(page).locator("b")).toHaveText("1");
  await expect(row(page).locator(":scope > :first-child")).toHaveAccessibleName("Filters, 1 on");
  const on = page.locator(".found").getByRole("button", { name: "Remove tag:marsupial" });
  await expect(on).toBeVisible();
  expect((await on.boundingBox())?.height).toBeGreaterThanOrEqual(44);
  expect((await filtersChip(page).boundingBox())?.height).toBeGreaterThanOrEqual(44);
  await on.click();
  await expect(hits(page)).toHaveCount(3);
  await expect(filtersChip(page)).toHaveAccessibleName("Filters");
});

test("the sheet: opens at the bottom, applies at once, Clear filters, Done", async ({ page }) => {
  await page.goto("/search?q=potoroo");
  await expect(hits(page)).toHaveCount(3);
  await filtersChip(page).click();
  const s = sheet(page);
  await expect(s).toBeVisible();
  await expect(filtersChip(page)).toHaveAttribute("aria-haspopup", "dialog");
  // At the bottom of the screen, its title focused (inside it, not behind it)
  const box = await s.boundingBox();
  const vh = page.viewportSize()?.height ?? 0;
  expect(Math.round((box?.y ?? 0) + (box?.height ?? 0))).toBeGreaterThanOrEqual(vh - 1);
  await expect(s.getByRole("heading", { name: "Filters" })).toBeFocused();
  await expect(s).toContainText("3 pages");
  // Every control a 44 px target (rounded: still sliding up, a box can be 43.99997 px)
  for (const b of await s.locator("button:visible, a:visible, select:visible").all())
    expect(
      Math.round((await b.boundingBox())?.height ?? 0),
      await b.innerText(),
    ).toBeGreaterThanOrEqual(44);
  await s.getByRole("combobox", { name: "Sort" }).selectOption({ label: "Title A–Z" });
  await expect(page.getByRole("searchbox")).toHaveValue("potoroo sort:title");
  await expect(hits(page)).toHaveText(["Potoroo one", "Potoroo three", "Potoroo two"]);
  await s.getByRole("button", { name: "Edited in the past year" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("potoroo sort:title after:1y");
  await expect(page).toHaveURL(/q=potoroo%20sort%3Atitle%20after%3A1y$/);
  await expect(s).toBeVisible(); // still open: more to choose
  // Focus stays on the control tapped, though the sheet was drawn again
  await expect(s.getByRole("button", { name: "Edited in the past year" })).toBeFocused();
  await s.getByRole("button", { name: "Clear filters" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("potoroo"); // the words stay
  await expect(s.getByRole("button", { name: "Clear filters" })).toBeHidden(); // none left
  await s.getByRole("button", { name: "Edited in the past week" }).click();
  await s.getByRole("button", { name: "Done" }).click();
  await expect(s).toBeHidden();
  await expect(filtersChip(page)).toBeFocused(); // back where it was
  await expect(filtersChip(page)).toHaveAccessibleName("Filters, 1 on");
  await expect(page.getByRole("button", { name: "Remove after:1w" })).toBeVisible();
});

test("Escape, Back and a tap outside close it; Back then leaves the screen", async ({ page }) => {
  await page.goto("/");
  await page.goto("/search?q=potoroo");
  await expect(hits(page)).toHaveCount(3);
  // Escape
  await filtersChip(page).click();
  await expect(sheet(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(sheet(page)).toBeHidden();
  await expect(filtersChip(page)).toBeFocused();
  await expect(page).toHaveURL(/\/search\?q=potoroo$/);
  // Back: closes it, keeps what it chose, and the screen stays
  await filtersChip(page).click();
  await sheet(page).getByRole("button", { name: "Edited in the past year" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("potoroo after:1y");
  await page.goBack();
  await expect(sheet(page)).toBeHidden();
  await expect(page).toHaveURL(/\/search\?q=potoroo%20after%3A1y$/);
  await expect(page.getByRole("searchbox")).toHaveValue("potoroo after:1y");
  await expect(hits(page)).toHaveCount(3);
  await expect(filtersChip(page)).toBeFocused();
  // A tap outside it, on the dimmed list
  await filtersChip(page).click();
  await expect(sheet(page)).toBeVisible();
  await page.mouse.click(200, 60);
  await expect(sheet(page)).toBeHidden();
  // Back now: off the screen, as before (no stray entries left)
  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
});

test("a tap just as the sheet closes is not undone by its step back", async ({ page }) => {
  await page.goto("/");
  await page.goto("/search?q=potoroo");
  await expect(hits(page)).toHaveCount(3);
  await filtersChip(page).click();
  await expect(sheet(page)).toBeVisible();
  // Done and a row tapped in the same moment, before the sheet's history.back() lands
  const title = await page.evaluate(() => {
    (document.querySelector(".sheet .primary") as HTMLElement).click();
    const a = document.querySelector(".hits li a") as HTMLAnchorElement;
    a.click();
    return a.querySelector("strong")?.textContent;
  });
  await expect(page).toHaveURL(/\/p\//);
  await expect(page.locator(".page h1")).toHaveText(title ?? "");
  // Back: the search screen once (no stray entry), then where it came from
  await page.goBack();
  await expect(page).toHaveURL(/\/search\?q=potoroo$/);
  await expect(hits(page)).toHaveCount(3);
  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
});

test("closed and opened again at once, it stays open; Forward steps over its old entry", async ({
  page,
}) => {
  await page.goto("/");
  await page.goto("/search?q=potoroo");
  await expect(hits(page)).toHaveCount(3);
  await filtersChip(page).click();
  await expect(sheet(page)).toBeVisible();
  await page.evaluate(() => {
    (document.querySelector(".sheet .primary") as HTMLElement).click();
    (document.querySelector(".refine .filter") as HTMLElement).click();
  });
  await expect(sheet(page)).toBeVisible();
  await expect.poll(() => page.evaluate(() => history.state?.sheet)).toBe(1);
  await expect(sheet(page)).toBeVisible(); // the first close's step back did not close it
  await sheet(page).getByRole("button", { name: "Done" }).click();
  await expect(sheet(page)).toBeHidden();
  await expect.poll(() => page.evaluate(() => history.state?.sheet)).toBeUndefined();
  // Forward: onto the closed sheet's entry, which is stepped over, back to the list
  await page.goForward();
  await expect.poll(() => page.evaluate(() => history.state?.sheet)).toBeUndefined();
  await expect(sheet(page)).toBeHidden();
  await expect(hits(page)).toHaveCount(3);
  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
});

test("the rest of the page is inert while it is open; Tab stays inside", async ({ page }) => {
  await page.goto("/search?q=potoroo");
  await expect(hits(page)).toHaveCount(3);
  await filtersChip(page).click();
  await expect(sheet(page)).toBeVisible();
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    const inside = await page.evaluate(
      () => !!document.activeElement?.closest("dialog") || document.activeElement === document.body,
    );
    expect(inside).toBe(true);
  }
  await expect(page.getByRole("searchbox")).not.toBeFocused();
});

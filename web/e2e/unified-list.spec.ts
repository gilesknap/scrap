// The one list screen (Recent merged into Search): an empty box lists every page newest first,
// the kind row and Clear, and the query in the address, so Back and a delete come back to it.
import { expect, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

async function make(page: Page, text: string, kind = "note") {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text, kind } });
  return (await r.json()).slug as string;
}

const tab = (page: Page, name: string) => page.locator("nav a", { hasText: name });

test("one Search tab: newest first, no keyboard; /recent is this screen", async ({ page }) => {
  const tag = ulid().slice(-6);
  const older = await make(page, `List older ${tag}`);
  const newer = await make(page, `List newer ${tag}`, "todo");
  await page.goto("/recent");
  await expect(page).toHaveURL(/\/search$/);
  await expect(page.locator("nav a")).toHaveText(["Capture", "Search"]); // one tab for it
  await expect(tab(page, "Search")).toHaveAttribute("aria-current");
  await expect(page.getByRole("searchbox")).toHaveValue("");
  await expect(page.getByRole("searchbox")).not.toBeFocused(); // the list, not the keyboard
  const links = page.locator(".list li a");
  await expect(links.first()).toHaveAttribute("href", `/p/${newer}`);
  await expect(links.nth(1)).toHaveAttribute("href", `/p/${older}`);
  await expect(page.locator(".list li").first().locator(".tick")).toBeVisible(); // a todo's
  await expect(page.locator(".refine")).not.toContainText("Clear"); // nothing to clear

  // A query keeps the tab lit; the Search tab from elsewhere: the list again, no keyboard
  await page.getByRole("searchbox").fill(tag);
  await expect(page).toHaveURL(/\/search\?q=/);
  await expect(tab(page, "Search")).toHaveAttribute("aria-current");
  await tab(page, "Capture").click();
  await expect(tab(page, "Search")).not.toHaveAttribute("aria-current");
  await tab(page, "Search").click();
  await expect(page).toHaveURL(/\/search$/);
  await expect(page.getByRole("searchbox")).not.toBeFocused();
  await expect(links.first()).toHaveAttribute("href", `/p/${newer}`);
});

test("Clear resets text, kind and filters to the newest-first list", async ({ page }) => {
  const tag = ulid().slice(-6);
  await make(page, `Clear me ${tag}`, "todo");
  await page.goto(`/search?q=${encodeURIComponent(`clear kind:todo after:1w`)}`);
  await expect(page.locator(".kindrow").getByRole("radio", { name: "Todos" })).toBeChecked();
  await expect(page.locator(".hits li", { hasText: `Clear me ${tag}` })).toBeVisible();
  const clear = page.locator(".refine button", { hasText: "Clear" });
  await expect(page.locator(".refine > :first-child")).toHaveText("Clear"); // the row's start
  await clear.click();
  await expect(page).toHaveURL(/\/search$/);
  await expect(page.getByRole("searchbox")).toHaveValue("");
  await expect(page.locator(".kindrow").getByRole("radio", { name: "All" })).toBeChecked();
  await expect(clear).toHaveCount(0);
  await expect(page.locator(".list li").first()).toContainText(`Clear me ${tag}`);
});

test("deleting an opened page returns to its search, filters kept; Back too", async ({ page }) => {
  const tag = ulid().slice(-6);
  const keep = await make(page, `Kept ${tag} item`, "todo");
  const gone = await make(page, `Gone ${tag} item`, "todo");
  const q = `${tag} kind:todo`;
  const url = `/search?q=${encodeURIComponent(q)}`;
  await page.goto("/"); // from elsewhere, so Back has somewhere wrong to go
  await page.goto(url);
  await page.locator(`a[href="/p/${keep}"]`).click();
  await expect(page.locator(".pager")).toContainText("Search results");
  await page.goBack();
  await expect(page).toHaveURL(url);
  await expect(page.getByRole("searchbox")).toHaveValue(q);

  await page.locator(`a[href="/p/${gone}"]`).click();
  await expect(page).toHaveURL(`/p/${gone}`);
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(url);
  await expect(page.locator(".kindrow").getByRole("radio", { name: "Todos" })).toBeChecked();
  await expect(page.getByText("Page deleted")).toBeVisible();
  await expect(page.locator(`a[href="/p/${gone}"]`)).toHaveCount(0);
  await expect(page.locator(`a[href="/p/${keep}"]`)).toBeVisible();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page).toHaveURL(`/p/${gone}`);

  // A page opened from no list (a link from outside): delete lands on the newest-first list
  await page.goto(`/p/${keep}`);
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/search$/);
  await expect(page.getByText("Page deleted")).toBeVisible();
});

test("Back restores where the list was scrolled to", async ({ page }) => {
  const tag = ulid().slice(-6);
  for (let i = 0; i < 25; i++) await make(page, `Scroll ${tag} ${i}`);
  await page.goto("/search");
  const row = page.locator(".list li", { hasText: `Scroll ${tag} 3` }).first();
  await row.scrollIntoViewIfNeeded();
  await page.mouse.wheel(0, 400);
  await page.waitForTimeout(300);
  const y = await page.evaluate(() => scrollY);
  expect(y).toBeGreaterThan(200);
  await page.mouse.click(200, 400); // a row on screen (a locator's click would scroll to it)
  await expect(page.locator(".pager")).toBeVisible();
  await page.goBack();
  await expect(page.locator(".list li").first()).toBeVisible();
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(y - 50);
});

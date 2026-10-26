// The one list screen (Recent merged into Search): an empty box lists every page newest first,
// the kind row and Clear, and the query in the address, so Back and a delete come back to it.
import { expect, type Page, test } from "@playwright/test";
import { filtersButton } from "./panel";

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
  await expect(page.locator("nav a")).toHaveText(["Capture", /Todos$/, "Search", "Topics"]); // one tab for it
  await expect(tab(page, "Search")).toHaveAttribute("aria-current");
  await expect(page.getByRole("searchbox")).toHaveValue("");
  await expect(page.getByRole("searchbox")).not.toBeFocused(); // the list, not the keyboard
  const links = page.locator(".list li a");
  await expect(links.first()).toHaveAttribute("href", `/p/${newer}`);
  await expect(links.nth(1)).toHaveAttribute("href", `/p/${older}`);
  await expect(page.locator(".list li").first().locator(".tick")).toBeVisible(); // a todo's
  await expect(page.getByRole("button", { name: "Clear search" })).toBeHidden(); // nothing to clear

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
  // The box's ✕, inside it at its end, just before the Filters slider; each a 48 px target
  const clear = page.getByRole("button", { name: "Clear search" });
  const filters = filtersButton(page);
  const [field, x, f] = [
    await page.locator(".field-search").boundingBox(),
    await clear.boundingBox(),
    await filters.boundingBox(),
  ];
  expect(x?.height).toBeGreaterThanOrEqual(44);
  expect(f?.height).toBeGreaterThanOrEqual(44);
  expect(Math.abs((x?.x ?? 0) + (x?.width ?? 0) - (f?.x ?? 0))).toBeLessThan(2);
  expect(
    Math.abs((f?.x ?? 0) + (f?.width ?? 0) - ((field?.x ?? 0) + (field?.width ?? 0))),
  ).toBeLessThan(2);
  await expect(filters).toHaveAccessibleName("Filters, 1 on"); // after:1w; the kind is the row's
  await clear.click();
  await expect(page).toHaveURL(/\/search$/);
  await expect(page.getByRole("searchbox")).toHaveValue("");
  await expect(page.getByRole("searchbox")).not.toBeFocused(); // a tap: no keyboard
  await expect(page.locator(".kindrow").getByRole("radio", { name: "All" })).toBeChecked();
  await expect(clear).toBeHidden();
  // Typed again, it shows again; by key it leaves the focus in the box
  await page.getByRole("searchbox").fill("clear");
  await expect(clear).toBeVisible();
  await clear.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("searchbox")).toHaveValue("");
  await expect(page.getByRole("searchbox")).toBeFocused();
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
  await expect(page.locator("header .pager")).toHaveAttribute("aria-label", "In Search results");
  await expect(page.locator("#backto")).toHaveText("Search");
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

test("search results page on with Show more, as far as the count says", async ({ page }) => {
  const tag = `more${ulid().slice(-6).toLowerCase()}`;
  for (let i = 0; i < 105; i++) await make(page, `Paged ${tag} ${i}`);
  await page.goto(`/search?q=${tag}`);
  const rows = page.locator(".hits > li");
  await expect(rows).toHaveCount(100);
  await expect(page.locator(".found")).toContainText("105 pages"); // above the list
  await page.getByRole("button", { name: "Show more" }).click();
  await expect(rows).toHaveCount(105);
  await expect(page.getByRole("button", { name: "Show more" })).toHaveCount(0);
  await page.reload(); // as long again (it rides in the history entry)
  await expect(rows).toHaveCount(105);
});

test("the kind row keeps focus as arrow keys move through it; any case of kind:", async ({
  page,
}) => {
  await page.goto("/search?q=kind%3ATodo");
  const row = page.getByRole("radiogroup", { name: "Kind" });
  await expect(row.getByRole("radio", { name: "Todos" })).toBeChecked(); // kind:Todo
  await row.getByRole("radio", { name: "Todos" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("searchbox")).toHaveValue("kind:later");
  await expect(row.getByRole("radio", { name: "Later" })).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("searchbox")).toHaveValue("kind:board");
  await expect(row.getByRole("radio", { name: "Boards" })).toBeFocused();
  await page.goto("/recent?kind=bogus"); // an unknown kind: ignored
  await expect(page).toHaveURL(/\/search$/);
  await page.goto("/recent?kind=consume");
  await expect(page).toHaveURL(/\/search\?q=kind%3Alater$/);
  // The old name still works, typed or in a link
  await page.goto("/search?q=kind%3Aread");
  await expect(row.getByRole("radio", { name: "Later" })).toBeChecked();
});

test("the kind row: each kind's own icon over its word, at 320 px too", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.goto("/search");
  const row = page.getByRole("radiogroup", { name: "Kind" });
  const labels = row.locator("label");
  await expect(labels).toHaveText(["All", "Notes", "Todos", "Later", "Boards", "Docs"]);
  await expect(row.locator("label > svg.i")).toHaveCount(6);
  // Each kind's own icon, as the editor's kinds have them (All: a grid of tiles)
  const glyphs = await labels.evaluateAll((ls) =>
    ls.map((l) => l.querySelector("svg")?.innerHTML ?? ""),
  );
  expect(new Set(glyphs).size).toBe(6);
  // The icon over its word (one row of them is checked in view.spec.ts)
  const over = await labels.evaluateAll((ls) =>
    ls.map((l) => {
      const icon = (l.querySelector("svg") as SVGElement).getBoundingClientRect();
      const word = document.createRange();
      word.selectNodeContents(l.lastChild as Node);
      return icon.bottom <= word.getBoundingClientRect().top + 1;
    }),
  );
  expect(over).toEqual([true, true, true, true, true, true]);
  // Shown with a query and filters too, under the filters on
  await page.goto("/search?q=x%20after%3A1w");
  await expect(row).toBeVisible();
  const [on, kinds] = [
    await page.getByRole("group", { name: "Filters on" }).boundingBox(),
    await row.boundingBox(),
  ];
  expect((on?.y ?? 0) + (on?.height ?? 0)).toBeLessThanOrEqual(kinds?.y ?? 0);
});

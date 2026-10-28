// Runs after smoke.spec.ts, which wants an empty store (files run in name order).
// The search screen's Filters (refine.ts): a slider at the box's end (with how many are on),
// the filters on as chips under the box, the count over the list, and the Filters panel that
// opens in place: Tags (offering only tags of the results), Order and When, each tap editing
// the query at once, and Clear filters.
import { expect, type Page, test } from "@playwright/test";
import { lowContrast } from "./contrast";
import { filters, filtersButton } from "./panel";

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
  await note(page, "Bettong elsewhere", ["hopper"]); // a tag in use, on no potoroo
});

const hits = (page: Page) => page.locator(".hits li a strong");
const filtersOn = (page: Page) => page.getByRole("group", { name: "Filters on" });
/** The tags the panel offers, as their chips say them ("#hop1": the tag and its count). */
const offers = (page: Page) =>
  page.getByRole("group", { name: "Tags", exact: true }).locator("[data-k^='tag:']");

test("Filters is a slider in the box; what is on shows as chips under it", async ({ page }) => {
  await page.goto("/search?q=potoroo");
  await expect(hits(page)).toHaveCount(3);
  await expect(page.locator(".rhead .count")).toHaveText("3 pages");
  await expect(filtersOn(page)).toHaveCount(0); // none on: no row
  const button = filtersButton(page);
  await expect(button).toHaveAccessibleName("Filters");
  await expect(button).toHaveAttribute("aria-controls", "fpanel");
  await expect(button).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator("#fpanel")).toBeHidden();
  expect((await button.boundingBox())?.height).toBeGreaterThanOrEqual(44);
  const panel = await filters(page);
  await expect(button).toHaveAttribute("aria-expanded", "true");
  // In place: under the box, over the kind row and the list
  const [field, open, kinds] = await Promise.all([
    page.locator(".field-search").boundingBox(),
    panel.boundingBox(),
    page.getByRole("radiogroup", { name: "Kind" }).boundingBox(),
  ]);
  expect(open?.y ?? 0).toBeGreaterThan(field?.y ?? 0);
  expect((open?.y ?? 0) + (open?.height ?? 0)).toBeLessThanOrEqual(kinds?.y ?? 0);
  // Every control a 44 px target
  for (const b of await panel.locator("button:visible, a:visible, input:visible").all())
    expect(
      Math.round((await b.boundingBox())?.height ?? 0),
      await b.evaluate((el) => el.outerHTML.slice(0, 80)),
    ).toBeGreaterThanOrEqual(44);
  // A tag chosen: on as a chip under the box, counted on the slider; the panel stays open
  await offers(page).filter({ hasText: "#marsupial" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("potoroo tag:marsupial");
  await expect(hits(page)).toHaveCount(2);
  // The count is the results header's, under the chips: no count in the chips' row (#314)
  await expect(page.locator(".rhead .count")).toHaveText("2 pages");
  await expect(filtersOn(page).locator(".count")).toHaveCount(0);
  await expect(button).toHaveAccessibleName("Filters, 1 on");
  await expect(button.locator("b")).toHaveCount(0); // no count badge: the chips say it
  await expect(panel).toBeVisible();
  const on = filtersOn(page).getByRole("button", { name: "Remove #marsupial" });
  await expect(on).toHaveText("#marsupial");
  expect((await on.boundingBox())?.height).toBeGreaterThanOrEqual(44);
  // Folded: the panel goes, the chips stay
  await button.click();
  await expect(button).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator("#fpanel")).toBeHidden();
  await expect(on).toBeVisible();
  await on.click();
  await expect(hits(page)).toHaveCount(3);
  await expect(button).toHaveAccessibleName("Filters");
  await expect(filtersOn(page)).toHaveCount(0);
  await expect(page.locator(".rhead .count")).toHaveText("3 pages");
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    await filters(page);
    await page.locator("#fpanel").getByRole("button", { name: "Edited in the past year" }).click();
    await expect(filtersOn(page)).toBeVisible();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} panel`).toEqual([]);
    await filtersOn(page).getByRole("button").click();
    await expect(filtersOn(page)).toHaveCount(0);
  }
});

test("Tags offers only tags that narrow the results; typed, those of the results", async ({
  page,
}) => {
  await page.goto("/search?q=potoroo");
  await expect(hits(page)).toHaveCount(3);
  const panel = await filters(page);
  // The results' top tags, with how many of them have each; not a tag of no result
  await expect(offers(page)).toHaveText(["#marsupial2", "#hop1"]);
  await expect(panel.getByRole("link", { name: "All tags" })).toHaveCount(0); // retired
  await offers(page).filter({ hasText: "#marsupial" }).click();
  // Now from these two: #hop narrows them, #marsupial (on every one) does not
  await expect(hits(page)).toHaveCount(2);
  await expect(offers(page)).toHaveText(["#hop1"]);
  // Typed: the tags of the results that match (#hopper is in use, on no potoroo)
  const box = panel.getByRole("textbox", { name: "Add a tag filter" });
  await box.fill("ho");
  await expect(offers(page)).toHaveText(["#hop1"]);
  await box.fill("hopp");
  await expect(offers(page)).toHaveCount(0);
  await expect(panel.locator(".none")).toHaveText("No tag in these results has “hopp”");
  // Enter takes the first offer
  await box.fill("ho");
  await expect(offers(page)).toHaveText(["#hop1"]);
  await box.press("Enter");
  await expect(page.getByRole("searchbox")).toHaveValue("potoroo tag:marsupial tag:hop");
  await expect(hits(page)).toHaveText(["Potoroo two"]);
  await expect(panel.getByRole("textbox", { name: "Add a tag filter" })).toHaveValue("");
  await expect(panel.locator(".none")).toHaveText("No tag narrows these results");
  // Before any search: the most used tags of all
  await page.goto("/search");
  await filters(page);
  // (as many as fit two rows, full paths: which ones depends on what else the store holds)
  await expect(offers(page).first()).toBeVisible();
  await expect(offers(page).filter({ hasText: "…/" })).toHaveCount(0);
});

test("When, Order and Clear filters: each a tap, applied at once", async ({ page }) => {
  await page.goto("/search?q=potoroo");
  await expect(hits(page)).toHaveCount(3);
  const panel = await filters(page);
  await expect(panel.getByRole("button", { name: "Clear filters" })).toHaveCount(0); // none on
  const order = panel.getByRole("group", { name: "Order" });
  await order.getByRole("button", { name: "A–Z" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("potoroo sort:title");
  await expect(hits(page)).toHaveText(["Potoroo one", "Potoroo three", "Potoroo two"]);
  await panel.getByRole("button", { name: "Edited in the past year" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("potoroo sort:title after:1y");
  await expect(page).toHaveURL(/q=potoroo%20sort%3Atitle%20after%3A1y$/);
  // Focus stays on the control tapped, though the panel was drawn again
  await expect(panel.getByRole("button", { name: "Edited in the past year" })).toBeFocused();
  await expect(panel.getByRole("button", { name: "Edited in the past year" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(filtersOn(page).getByRole("button")).toHaveText(["A–Z", "past year"]);
  await panel.getByRole("button", { name: "Clear filters" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("potoroo"); // the words stay
  await expect(panel.getByRole("button", { name: "Clear filters" })).toHaveCount(0); // none left
  await expect(filtersOn(page)).toHaveCount(0);
  // Clear keeps the kind (the kind row's own) and the words
  await page.getByRole("radiogroup", { name: "Kind" }).getByText("Notes").click();
  await panel.getByRole("button", { name: "Edited in the past week" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("potoroo kind:note after:1w");
  await panel.getByRole("button", { name: "Clear filters" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("potoroo kind:note");
});

test("Order replaces the order: a typed Sort:due, and two picks in a row", async ({ page }) => {
  // The server reads the key in any case: a typed Sort:due is an order Order replaces
  await page.goto("/search?q=potoroo%20Sort:due");
  await expect(hits(page)).toHaveCount(3);
  const order = (await filters(page)).getByRole("group", { name: "Order" });
  await order.getByRole("button", { name: "Oldest" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("potoroo -sort:created");
  // Two picks before the panel is drawn again: the second replaces the first
  await page.evaluate(() => {
    for (const k of ["sort:sort:title", "sort:sort:created"])
      (document.querySelector(`#fpanel [data-k="${k}"]`) as HTMLElement).click();
  });
  const box = page.getByRole("searchbox");
  await expect(box).toHaveValue("potoroo sort:created");
  expect((await box.inputValue()).match(/sort:/gi)).toHaveLength(1);
  await expect(page).toHaveURL(/q=potoroo%20sort%3Acreated$/);
  await expect(hits(page)).toHaveText(["Potoroo three", "Potoroo two", "Potoroo one"]);
});

test("the panel takes no history entry: Back leaves the screen", async ({ page }) => {
  await page.goto("/");
  await page.goto("/search?q=potoroo");
  await expect(hits(page)).toHaveCount(3);
  const panel = await filters(page);
  await panel.getByRole("button", { name: "Edited in the past year" }).click();
  await expect(page).toHaveURL(/\/search\?q=potoroo%20after%3A1y$/);
  // A row tapped with the panel open opens it; Back comes back to the search as it was
  const title = await hits(page).first().textContent();
  await hits(page).first().click();
  await expect(page.locator(".page h1")).toHaveText(title ?? "");
  await page.goBack();
  await expect(page).toHaveURL(/\/search\?q=potoroo%20after%3A1y$/);
  await expect(page.getByRole("searchbox")).toHaveValue("potoroo after:1y");
  await expect(hits(page)).toHaveCount(3);
  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
});

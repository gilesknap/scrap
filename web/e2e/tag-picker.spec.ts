// The tag picker (#394): one shared picker for Search's Tags and the composer's and page
// editor's Tags fold. Offered tags are outlined chips under the box in at most two rows, each
// saying its tag's full path (a long one wraps inside its chip); nothing scrolls.
import { expect, type Locator, type Page, test } from "@playwright/test";
import { lowContrast } from "./contrast";
import { deletedAfterEach, ulid } from "./helpers";
import { filters, filtersButton, openFold } from "./panel";

const word = () => `q${ulid().slice(-7).toLowerCase()}`;

// Every page made here is deleted after, so other specs' counts of the store's pages hold
const made = deletedAfterEach();

/** A page whose text holds w, with those tags: its slug and id. Queued for deletion. */
async function make(page: Page, w: string, tags: string[]) {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text: `Picker ${w}` } });
  const got = (await r.json()) as { page_id: string; slug: string };
  made.push(got.page_id);
  const patch = await page.request.patch(`/api/pages/${got.page_id}`, { data: { tags } });
  expect(patch.ok()).toBe(true);
  return got;
}

/** Pages holding w, all tagged with the two clashing tags and each with a long one of its own
 * (more than the picker can offer in two rows). Returns the clashing pair. */
async function seed(page: Page, w: string, own = 12) {
  // (a short suffix of w keeps them this test's own, and still fits the picker's two rows at 390 px)
  const k = w.slice(-3);
  const pair = [`a${k}/epics/ioc`, `b${k}/other/ioc`];
  for (let i = 0; i < own; i++)
    await make(page, w, [...pair, `topic${i}${w}-quite-a-long-top-level-tag-name`]);
  return pair;
}

/** Text at 130% (the app's 17 px root, as an Android user's larger setting makes it). */
const large = (page: Page) => page.addStyleTag({ content: ":root { font-size: 22.1px; }" });

/** How many rows the chips of a group take: the distinct tops of its buttons. lead: also
 * counts the row of this element (Search's box). */
const rowsOf = (group: Locator, lead?: Locator) =>
  group.evaluate(
    (el, leadSel) => {
      const tops = new Set(
        [...el.querySelectorAll<HTMLElement>("button")].map((b) =>
          Math.round(b.getBoundingClientRect().top),
        ),
      );
      const box = leadSel ? el.querySelector(leadSel) : null;
      if (box) tops.add(Math.round(box.getBoundingClientRect().top));
      return tops.size;
    },
    lead ? "input" : "",
  );

/** Elements of scope that scroll sideways (or vertically) on their own, or stick out of it. */
const scrollers = (scope: Locator) =>
  scope.evaluate((root) => {
    const r = root.getBoundingClientRect();
    return [root, ...root.querySelectorAll<HTMLElement>("*")]
      .filter((e) => {
        const cs = getComputedStyle(e);
        const scrolls =
          /auto|scroll/.test(cs.overflowX + cs.overflowY) && e.scrollWidth > e.clientWidth;
        const out = e.getBoundingClientRect().right > r.right + 1 && e !== root;
        return scrolls || out;
      })
      .map((e) => e.className || e.tagName);
  });

const results = (page: Page) => page.locator(".list li");

test("Search offers at most two rows of tags at 390 px with 130% text, and nothing scrolls", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const w = word();
  await seed(page, w);
  await page.goto(`/search?q=${w}`);
  await large(page);
  const panel = await filters(page);
  const offers = panel.getByRole("group", { name: "Tags in these results" });
  await expect(offers.getByRole("button").first()).toBeVisible();
  await expect.poll(() => rowsOf(offers, page.locator("input"))).toBeLessThanOrEqual(2);
  // Some were left out (more tags than fit), not squeezed in
  expect(await offers.getByRole("button").count()).toBeLessThan(14);
  expect(await scrollers(panel)).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  // Typing narrows: still two rows
  await panel.getByRole("textbox", { name: "Add a tag filter" }).fill("topic");
  const matching = panel.getByRole("group", { name: "Matching tags" });
  await expect(matching.getByRole("button").first()).toBeVisible();
  await expect.poll(() => rowsOf(matching, page.locator("input"))).toBeLessThanOrEqual(2);
});

test("the first result shows under the open Filters panel at 390 px, 130%", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const w = word();
  await seed(page, w, 4);
  await page.goto(`/search?q=${w}`);
  await large(page);
  const panel = await filters(page, false); // Arrange folded, as it opens
  // The offers are fitted to two rows by a ResizeObserver once the panel shows (tagpick.ts),
  // a frame after it opens or is drawn again: until then every chip is in it, and the results
  // sit far lower (#415). Measured only once fitted
  const offers = panel.getByRole("group", { name: "Tags in these results" });
  const fitted = () =>
    expect.poll(() => rowsOf(offers, page.locator("input"))).toBeLessThanOrEqual(2);
  await fitted();
  const nav = page.locator("nav");
  await expect(nav).toBeVisible();
  const navTop = (await nav.boundingBox())?.y as number;
  await expect(results(page).first()).toContainText(w);
  const top = async () => ((await results(page).first().boundingBox()) as { y: number }).y;
  const under = async () => {
    const box = (await panel.boundingBox()) as { y: number; height: number };
    expect(await top()).toBeGreaterThanOrEqual(box.y + box.height); // under the panel
  };
  await expect.poll(top).toBeLessThanOrEqual(navTop - 160); // well into view, not just its edge
  await under();
  // With one (long) tag chosen the row's start still shows, at least a line above the nav (a long tag adds a wrapped chip row)
  await page.getByRole("button", { name: /^Filter by #topic0/ }).click();
  await expect(filtersButton(page)).toHaveAccessibleName("Filters, 1 on");
  await expect(results(page)).toHaveCount(1); // narrowed: drawn again
  await fitted(); // (the panel is drawn again too)
  await expect.poll(top).toBeLessThanOrEqual(navTop - 100);
  await under();
});

test("every chip says its tag's full path, never shortened", async ({ page }) => {
  const w = word();
  const [one, two] = await seed(page, w, 2);
  await make(page, w, [`c${w}/deep/unique-leaf-name`]);
  await page.goto(`/search?q=${w}`);
  const panel = await filters(page);
  await panel.getByRole("textbox", { name: "Add a tag filter" }).fill("ioc");
  const offers = panel.getByRole("group", { name: "Matching tags" });
  const a = offers.getByRole("button", { name: `Filter by #${one}` });
  const b = offers.getByRole("button", { name: `Filter by #${two}` });
  await expect(a).toHaveText(new RegExp(`^#${one}\\d*$`)); // (and its count)
  await expect(b).toHaveText(new RegExp(`^#${two}\\d*$`));
  await expect(offers).not.toContainText("…/");
  await panel.getByRole("textbox", { name: "Add a tag filter" }).fill("unique-leaf");
  const solo = offers.getByRole("button", { name: `Filter by #c${w}/deep/unique-leaf-name` });
  await expect(solo).toHaveText(new RegExp(`^#c${w}/deep/unique-leaf-name\\d*$`));
  // Chosen, the Filters-on chip says it in full too
  await solo.click();
  const on = page.getByRole("group", { name: "Filters on" });
  await expect(on.getByRole("button", { name: `Remove #c${w}/deep/unique-leaf-name` })).toHaveText(
    `#c${w}/deep/unique-leaf-name`,
  );
});

test("the page editor's and the composer's Tags fold offer two rows, nothing scrolling", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const w = word();
  await seed(page, w);
  const { slug } = await make(page, `${w}x`, []);
  await page.goto(`/p/${slug}`);
  await large(page);
  await page.locator(".page > .tools").getByRole("button", { name: "Edit" }).click();
  await openFold(page.locator(".editor"), "Tags");
  const editor = page.locator(".editor .tagedit");
  await editor.getByRole("textbox", { name: "Add a tag" }).fill(w);
  const offers = editor.getByRole("group", { name: "Matching tags" });
  await expect(offers.getByRole("button").first()).toBeVisible();
  await expect.poll(() => rowsOf(offers)).toBeLessThanOrEqual(2);
  expect(await scrollers(editor)).toEqual([]);
  await expect(offers.getByRole("button").first()).toHaveText(/^#/);
  page.once("dialog", (d) => d.accept());
  await page.locator(".editor > .bar").getByRole("button", { name: "Cancel" }).click();
  // The composer
  await page.goto("/");
  await page.getByRole("button", { name: "Note", exact: true }).click();
  const composer = page.locator(".editor");
  await openFold(composer, "Tags");
  await composer.getByRole("textbox", { name: "Add a tag" }).fill(w);
  const matching = composer.getByRole("group", { name: "Matching tags" });
  await expect(matching.getByRole("button").first()).toBeVisible();
  await expect.poll(() => rowsOf(matching)).toBeLessThanOrEqual(2);
  expect(await scrollers(composer)).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("outlined offer chips and the picker's text meet contrast, in both themes", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const w = word();
  await seed(page, w, 4);
  /** The outline of each offered chip against what is behind it: at least 3:1 (WCAG 1.4.11). */
  const outlines = (group: Locator) =>
    group.evaluate((el) => {
      const rgb = (c: string) => (c.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
      const lum = (c: number[]) =>
        c
          .map((v) => v / 255)
          .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
          .reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0);
      const behind = (e: Element) => {
        for (let p: Element | null = e; p; p = p.parentElement) {
          const c = getComputedStyle(p).backgroundColor;
          if (!/rgba\(.*, 0\)|transparent/.test(c)) return rgb(c);
        }
        return rgb("rgb(255,255,255)");
      };
      return [...el.querySelectorAll("button")].map((b) => {
        const cs = getComputedStyle(b);
        // The edge is an inset ring (box-shadow) inside a transparent 8 px border (a 32 px pill
        // in a 48 px target), else the border
        const edge = cs.boxShadow.match(/rgba?\([^)]*\)/)?.[0] ?? cs.borderTopColor;
        const [hi, lo] = [lum(rgb(edge)), lum(behind(b))].sort((x, y) => y - x);
        const own = cs.backgroundColor;
        // (a chip with a fill of its own is judged against that)
        const fill = /rgba\(.*, 0\)|transparent/.test(own) ? null : lum(rgb(own));
        const [h2, l2] = fill === null ? [hi, lo] : [lum(rgb(edge)), fill].sort((x, y) => y - x);
        return (h2 + 0.05) / (l2 + 0.05);
      });
    });
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    await page.goto(`/search?q=${w}`);
    const panel = await filters(page);
    const offers = panel.getByRole("group", { name: "Tags in these results" });
    await expect(offers.getByRole("button").first()).toBeVisible();
    for (const r of await outlines(offers))
      expect(r, `${colorScheme} search outline`).toBeGreaterThanOrEqual(3);
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} search`).toEqual([]);
    await page.goto("/");
    await page.getByRole("button", { name: "Note", exact: true }).click();
    const composer = page.locator(".editor");
    await openFold(composer, "Tags");
    await composer.getByRole("textbox", { name: "Add a tag" }).fill(w);
    const matching = composer.getByRole("group", { name: "Matching tags" });
    await expect(matching.getByRole("button").first()).toBeVisible();
    for (const r of await outlines(matching))
      expect(r, `${colorScheme} composer outline`).toBeGreaterThanOrEqual(3);
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} composer`).toEqual([]);
    page.once("dialog", (d) => d.accept());
    await composer.getByRole("button", { name: "Cancel" }).click();
  }
});

test("Enter in Search's tag box adds the first match even right after a chip was tapped", async ({
  page,
}) => {
  const w = word();
  const [one, two] = await seed(page, w, 3);
  await make(page, w, [`c${w}`]); // so the clashing pair is on some results, not all
  await page.goto(`/search?q=${w}`);
  const panel = await filters(page);
  const box = panel.getByRole("textbox", { name: "Add a tag filter" });
  await box.fill("ioc");
  const offers = panel.getByRole("group", { name: "Matching tags" });
  await expect(offers.getByRole("button")).toHaveCount(2);
  // A tap (a click with a detail), then at once Enter's click on the first match, which has
  // none: the double-tap guard is for taps only, so this one is not dropped
  await offers.evaluate((el) => {
    const [a, b] = el.querySelectorAll<HTMLElement>("button");
    a.dispatchEvent(new MouseEvent("click", { bubbles: true, detail: 1 }));
    b.click();
  });
  const on = page.getByRole("group", { name: "Filters on" });
  await expect(on.getByRole("button", { name: `Remove #${one}` })).toBeVisible();
  await expect(on.getByRole("button", { name: `Remove #${two}` })).toBeVisible();
});

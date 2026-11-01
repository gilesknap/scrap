// The editor's Link key (#511): [[]] at the caret and a page picker; a page picked is
// [[slug]] (a selection its words: [[slug|words]]), the caret after it; cancelled, the brackets
// stay with the caret inside; Undo takes back the pick and then the brackets; and the seven
// keys fit on one line on any phone, at 100% and 130% text.
import { expect, type Page, test } from "@playwright/test";
import { capture, deletedAfterEach, ulid } from "./helpers";

const made = deletedAfterEach();

const open = async (page: Page) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  const text = page.locator(".editor .fields > textarea");
  const keys = page.locator(".editor .keys");
  return {
    text,
    link: keys.getByRole("button", { name: "Link", exact: true }),
    undo: keys.getByRole("button", { name: "Undo" }),
    picker: page.getByRole("dialog", { name: "Link to a page" }),
    box: page.getByRole("searchbox", { name: "Find a page" }),
  };
};

/** The text box's text with | at the caret (or «..» around a selection). */
const caret = (page: Page) =>
  page.locator(".editor .fields > textarea").evaluate((t: HTMLTextAreaElement) => {
    const { value: v, selectionStart: a, selectionEnd: b } = t;
    return a === b
      ? `${v.slice(0, a)}|${v.slice(a)}`
      : `${v.slice(0, a)}«${v.slice(a, b)}»${v.slice(b)}`;
  });

/** The picker closed and gone: removed as it closes, and the caret placed straight after. */
const closed = (page: Page) => expect(page.locator("dialog.linkpick")).toHaveCount(0);

/** A page to link to, with a word of its own to find it by. */
const target = async (page: Page) => {
  const word = `wombat${ulid().slice(-8).toLowerCase()}`;
  const p = await capture(page, `Linked ${word} page`);
  made.push(p.page_id);
  return { word, slug: p.slug };
};

test("Link puts in [[]] and opens the picker; a page picked is [[slug]], the caret after it; Undo takes both back", async ({
  page,
}) => {
  const { word, slug } = await target(page);
  const { text, link, undo, picker, box } = await open(page);
  // 48 px, named Link, its icon alone at a phone's width
  expect(await link.evaluate((b) => b.getBoundingClientRect().height)).toBeGreaterThanOrEqual(48);
  await text.focus();
  await page.keyboard.insertText("See ");
  await link.click();
  await expect(picker).toBeVisible();
  await expect(box).toBeFocused();
  await expect.poll(() => caret(page)).toBe("See [[|]]");
  // Recent pages while the box is empty: the newest first
  await expect(picker.getByRole("heading", { name: "Recent" })).toBeVisible();
  await expect(picker.getByRole("button", { name: `Linked ${word} page` })).toBeVisible();
  // Matches as you type
  await box.fill(word);
  await expect(picker.getByRole("heading", { name: "Matching" })).toBeVisible();
  const row = picker.getByRole("button", { name: `Linked ${word} page` });
  await expect(row).toBeVisible();
  // Typing in the picker is another field's: it doesn't move Undo's floor
  await row.click();
  await closed(page);
  await expect(text).toBeFocused();
  await expect.poll(() => caret(page)).toBe(`See [[${slug}]]|`);
  await expect(undo).toBeEnabled();
  await undo.click();
  await expect(text).toHaveValue("See [[]]"); // the pick first
  await expect(undo).toBeEnabled();
  await undo.click();
  await expect(text).toHaveValue("See "); // then the brackets
  await expect(box).toHaveCount(0); // the picker's box is gone, with its typing
});

test("a selection becomes the link's words: [[slug|words]], the caret after it", async ({
  page,
}) => {
  const { word, slug } = await target(page);
  const { text, link, picker, box, undo } = await open(page);
  await text.focus();
  await page.keyboard.insertText("Plan the garden today");
  await text.evaluate((t: HTMLTextAreaElement) => t.setSelectionRange(9, 15)); // "garden"
  await link.click();
  await expect(picker).toBeVisible();
  await expect.poll(() => caret(page)).toBe("Plan the «garden» today"); // still selected, unchanged
  await box.fill(word);
  await box.press("Enter"); // the first match
  await closed(page);
  await expect.poll(() => caret(page)).toBe(`Plan the [[${slug}|garden]]| today`);
  await undo.click();
  await expect(text).toHaveValue("Plan the garden today");
});

test("cancelled (Escape, a tap outside, ✕, Back), the brackets stay with the caret inside", async ({
  page,
}) => {
  const { text, link, picker, box } = await open(page);
  await text.focus();
  await page.keyboard.insertText("a b");
  await text.evaluate((t: HTMLTextAreaElement) => t.setSelectionRange(1, 1));
  await link.click();
  await expect(picker).toBeVisible();
  await box.pressSequentially("zz");
  // A close request, as the phone's Back is: one closes it, though its box has text
  await page.keyboard.press("Escape");
  await closed(page);
  await expect(text).toBeFocused();
  await expect.poll(() => caret(page)).toBe("a[[|]] b");

  // A tap outside the sheet, on its backdrop
  await text.evaluate((t: HTMLTextAreaElement) => t.setSelectionRange(9, 9));
  await link.click();
  await expect(picker).toBeVisible();
  const sheet = await picker.boundingBox();
  const vp = page.viewportSize();
  expect(sheet && vp && sheet.y + sheet.height < vp.height - 20).toBe(true);
  await page.mouse.click(10, vp ? vp.height - 10 : 600);
  await closed(page);
  await expect.poll(() => caret(page)).toBe("a[[]] b[[|]]");

  // Its ✕; and pressed again in those empty brackets, they are used, not nested
  await link.click();
  await picker.getByRole("button", { name: "Close" }).click();
  await closed(page);
  await expect.poll(() => caret(page)).toBe("a[[]] b[[|]]");

  // The browser's Back (a computer's, which is no close request): the picker closes, and the
  // editor stays, its text as it was
  await text.fill("x");
  await link.click();
  await expect(picker).toBeVisible();
  await page.goBack();
  await closed(page);
  await expect(page.locator(".editor")).toBeVisible();
  await expect(text).toHaveValue("x[[]]");
  // and the editor's Back still works after it
  await page.goBack();
  await expect(page.locator(".editor")).toBeHidden();
});

test("in a code block, Link does nothing", async ({ page }) => {
  const { text, link, picker } = await open(page);
  await text.fill("```\ncode");
  await text.press("End");
  await link.click();
  await expect(picker).toHaveCount(0);
  await expect(text).toHaveValue("```\ncode");
});

// Seven keys on one line, no overflow; at 100% text the words show from about 413 px
// (css/composer.css), at 130% from wider still
for (const scale of [1, 1.3]) {
  for (const [width, words] of [
    [308, false],
    [320, false],
    [360, false],
    [390, false],
    [430, scale === 1],
  ] as const) {
    test(`the seven keys fit on one line at ${width} px and ${scale * 100}% text, ${words ? "with words" : "icons alone"}`, async ({
      page,
    }) => {
      await page.addInitScript((s) => localStorage.setItem("scrap.text_size", String(s)), scale);
      await page.setViewportSize({ width, height: 640 });
      await open(page);
      const keys = page.locator(".editor .keys button");
      await expect(keys).toHaveText([
        "Task",
        "Bullet",
        "Number",
        "Indent",
        "Outdent",
        "Link",
        "Undo",
      ]);
      await expect
        .poll(
          () =>
            page.evaluate(() => {
              const row = document.querySelector(".editor .keys") as HTMLElement;
              const ks = [...row.querySelectorAll("button")];
              const top = ks[0]?.getBoundingClientRect().y;
              const bad = ks.filter((b) => {
                const r = b.getBoundingClientRect();
                const word = (b.querySelector("span") as HTMLElement).getClientRects();
                const w = word[0];
                return (
                  r.x < 0 ||
                  r.right > innerWidth ||
                  r.y !== top ||
                  r.height < 48 ||
                  word.length > 1 ||
                  (w && (w.left < r.left || w.right > r.right))
                );
              });
              return {
                overflow: document.documentElement.scrollWidth > innerWidth,
                rowOverflow: row.scrollWidth > row.clientWidth,
                words: ks.map((b) => (b.querySelector("span") as HTMLElement).offsetWidth > 0),
                bad: bad.map((b) => b.textContent),
              };
            }),
          { message: `no overflow at ${width} px, ${scale * 100}%` },
        )
        .toEqual({ overflow: false, rowOverflow: false, words: Array(7).fill(words), bad: [] });
    });
  }
}

test("the open picker fits a 308 px phone at 130% text", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("scrap.text_size", "1.3"));
  await page.setViewportSize({ width: 308, height: 640 });
  await target(page); // a page to list, at least
  const { link, picker } = await open(page);
  await link.click();
  await expect(picker).toBeVisible();
  await expect(picker.locator(".rows button").first()).toBeVisible(); // the rows in, to measure
  const fit = await picker.evaluate((d) => {
    const r = d.getBoundingClientRect();
    const rows = [...d.querySelectorAll("button")].map((b) => b.getBoundingClientRect());
    return {
      inside: r.left >= 0 && r.right <= innerWidth,
      sideways: d.scrollWidth > d.clientWidth,
      small: rows.filter((b) => b.height < 48).length,
    };
  });
  expect(fit).toEqual({ inside: true, sideways: false, small: 0 });
});

test("Enter typed faster than the search answers picks the match, not the last list's first", async ({
  page,
}) => {
  const { word, slug } = await target(page);
  // A newer page, the Recent list's first
  const other = await capture(page, `Newest other ${ulid().slice(-6)}`);
  made.push(other.page_id);
  const { text, link, picker, box } = await open(page);
  await page.route("**/api/search?*", async (route) => {
    await new Promise((ok) => setTimeout(ok, 400)); // a slow phone's network
    await route.continue();
  });
  await text.focus();
  await link.click();
  await expect(picker.locator(".rows button").first()).toBeVisible(); // Recent drawn
  await box.fill(word);
  await box.press("Enter");
  await closed(page);
  await expect.poll(() => caret(page)).toBe(`[[${slug}]]|`);
});

test("a double tap on Link opens one picker and puts in one [[]]", async ({ page }) => {
  const { text, link, picker } = await open(page);
  await text.focus();
  await link.dblclick();
  await expect(picker).toBeVisible();
  await expect(page.locator("dialog.linkpick")).toHaveCount(1);
  await expect(text).toHaveValue("[[]]");
});

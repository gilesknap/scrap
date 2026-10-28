// A page's tag chips (#345 follow-up): each tag's full path, "+N" past two rows (− folds them
// again), ✦ for Claude's tags. Read only: the tags change in the editor (Edit), whose Tags fold
// says the full path too, as do the search chips.
import { execFileSync } from "node:child_process";
import { expect, type Locator, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};
const word = () => ulid().slice(-6).toLowerCase();

// Every page made here is deleted after, so other specs' counts of the store's pages hold
const made: string[] = [];
test.afterEach(async ({ request }) => {
  for (const id of made.splice(0)) await request.delete(`/api/pages/${id}`);
});

/** A page with those tags (and kind, and due date): its slug and id. Queued for deletion first. */
async function make(
  page: Page,
  tags: string[],
  kind = "note",
  extra: Record<string, unknown> = {},
) {
  const r = await page.request.post("/api/captures", {
    data: { id: ulid(), text: `Chips ${word()}`, kind },
  });
  const got = (await r.json()) as { page_id: string; slug: string };
  made.push(got.page_id);
  const patch = await page.request.patch(`/api/pages/${got.page_id}`, { data: { tags, ...extra } });
  expect(patch.ok()).toBe(true);
  return got;
}

/** Tags of a page marked as Claude's (what an ingest read does). */
function claudes(id: string, ...tags: string[]) {
  const data = process.env.SCRAP_E2E_DATA as string;
  execFileSync("uv", ["run", "--locked", "python", "web/e2e/chips.py", data, id, ...tags], {
    cwd: "..",
  });
}

const row = (page: Page) => page.locator(".page .tags");
const tag = (page: Page, full: string) => row(page).getByRole("link", { name: `Tag ${full}` });

/** How many rows the visible chips of a row take: the distinct tops of its links and buttons. */
const rowsOf = (line: Locator) =>
  line.evaluate(
    (el) =>
      new Set(
        [...el.querySelectorAll<HTMLElement>("a, button")]
          .filter((c) => !c.hidden && c.getClientRects().length)
          .map((c) => Math.round(c.getBoundingClientRect().top)),
      ).size,
  );

/** Text at 130% (the app's 17 px root, as an Android user's larger setting makes it). */
const large = (page: Page) => page.addStyleTag({ content: ":root { font-size: 22.1px; }" });

test("a chip says its tag's full path, and searches for it", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 }); // wide: no chip folds away to +N
  const [a, b] = [word(), word()];
  const p = await make(page, [`kind${a}/project-management`, `epics${a}/thoth`, `other${b}/thoth`]);
  await page.goto(`/p/${p.slug}`);
  await expect(tag(page, `kind${a}/project-management`)).toHaveText(`#kind${a}/project-management`);
  await expect(tag(page, `epics${a}/thoth`)).toHaveText(`#epics${a}/thoth`);
  await expect(tag(page, `other${b}/thoth`)).toHaveText(`#other${b}/thoth`);
  await expect(row(page)).not.toContainText("…/"); // no shortened path, anywhere
  // The full tag is the tooltip too, and the chip searches for it, children too
  await expect(tag(page, `kind${a}/project-management`)).toHaveAttribute(
    "title",
    `Tag kind${a}/project-management`,
  );
  // Read only: no + to change them (Edit does)
  await expect(row(page).getByRole("button", { name: /Change tags|Add tags/ })).toHaveCount(0);
  await tag(page, `kind${a}/project-management`).click();
  await expect(page).toHaveURL(`/search?q=tag%3Akind${a}%2Fproject-management`);
  await expect(page.locator(".list li a strong")).toHaveText([/^Chips /]);
});

test("a chip's search finds a deeper tag's pages too", async ({ page }) => {
  const a = word();
  const p = await make(page, [`par${a}/child`]);
  await make(page, [`par${a}/child/leaf`]);
  await page.goto(`/p/${p.slug}`);
  await tag(page, `par${a}/child`).click();
  // tag:par/child finds par/child/leaf too, as it always did
  await expect(page.locator(".list li a strong")).toHaveCount(2);
});

test("Claude's tag has ✦ in its pill and says so, with no dashed ring", async ({ page }) => {
  const a = word();
  const p = await make(page, [`mine${a}`, `ai${a}/robot`]);
  claudes(p.page_id, `ai${a}/robot`);
  await page.goto(`/p/${p.slug}`);
  const ai = row(page).getByRole("link", { name: `Tag ai${a}/robot, added by Claude` });
  await expect(ai).toHaveText(`#ai${a}/robot`);
  await expect(ai).toHaveClass(/\bai\b/);
  const mark = await ai.evaluate((el) => {
    const s = getComputedStyle(el, "::before");
    return [s.content, getComputedStyle(el).outlineStyle];
  });
  expect(mark).toEqual(['"✦"', "none"]);
  // The owner's own is plain
  const mine = tag(page, `mine${a}`);
  await expect(mine).toHaveAccessibleName(`Tag mine${a}`);
  expect(await mine.evaluate((el) => getComputedStyle(el, "::before").content)).toBe("none");
  // The editor's Tags fold marks it the same way, by its full path
  await page.locator(".page > .tools").getByRole("button", { name: "Edit" }).click();
  await page.locator(".editor .fold summary", { hasText: "Tags" }).click();
  const chip = page.getByRole("button", { name: `Remove #ai${a}/robot, added by Claude` });
  await expect(chip).toHaveText(`#ai${a}/robot`);
  await expect(chip).toHaveAttribute("title", `#ai${a}/robot, added by Claude`);
  expect(await chip.evaluate((el) => getComputedStyle(el, "::before").content)).toBe('"✦"');
  await expect(page.getByRole("button", { name: `Remove #mine${a}`, exact: true })).toBeVisible();
});

test("the editor's Tags fold and a filter on say the full path", async ({ page }) => {
  const a = word();
  const full = `deep${a}/er/leaf${a}`;
  const p = await make(page, [full]);
  await page.goto(`/p/${p.slug}`);
  await expect(tag(page, full)).toHaveText(`#${full}`);
  await page.locator(".page > .tools").getByRole("button", { name: "Edit" }).click();
  await page.locator(".editor .fold summary", { hasText: "Tags" }).click();
  const chip = page.getByRole("button", { name: `Remove #${full}` });
  await expect(chip).toHaveText(`#${full}`);
  await page.goto(`/search?q=tag%3A${encodeURIComponent(full)}`);
  const on = page.getByRole("group", { name: "Filters on" });
  await expect(on.getByRole("button", { name: `Remove #${full}` })).toHaveText(`#${full}`);
});

test("at 390 px and 130% text, tags fold to two rows, +N shows the rest in place, − folds them", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const a = word();
  const names = ["alpha-centauri", "bravo-charlie", "delta-foxtrot", "golf-hotel", "india-juliet"];
  const tags = names.map((n, i) => `t${i}${a}/${n}`);
  const p = await make(page, tags);
  await page.goto(`/p/${p.slug}`);
  await large(page);
  const line = row(page);
  const more = line.getByRole("button", { name: /^Show \d+ more tags?$/ });
  await expect(more).toBeVisible();
  await expect.poll(() => rowsOf(line)).toBeLessThanOrEqual(2);
  const shown = await line.getByRole("link").count();
  expect(shown).toBeLessThan(tags.length);
  expect(shown).toBeGreaterThan(0);
  await expect(more).toHaveText(`+${tags.length - shown}`); // how many more, not an add
  // Tapping it shows them all, in place (no navigation), then − at the end folds them again
  const url = page.url();
  await more.click();
  await expect(line.getByRole("link")).toHaveCount(tags.length);
  expect(page.url()).toBe(url);
  const fewer = line.getByRole("button", { name: "Show fewer tags" });
  await expect(fewer).toHaveText("−");
  await expect(fewer).toBeFocused();
  expect(await fewer.evaluate((el) => !el.nextElementSibling)).toBe(true);
  await fewer.click();
  await expect(more).toBeVisible();
  await expect.poll(() => rowsOf(line)).toBeLessThanOrEqual(2);
});

test("a focused tag that folds away on a narrower screen hands focus to +N", async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 800 });
  const a = word();
  // Short names: all three fit on one row at 1000 px in any font (the glyph widths differ
  // between machines, so a test that needs "just fits" passes here and not on CI, #421), and
  // two do not fit beside each other at 320 px
  const tags = ["alpha", "bravo", "delta"].map((n, i) => `t${i}${a}/${n}`);
  const p = await make(page, tags);
  await page.goto(`/p/${p.slug}`);
  await large(page);
  const line = row(page);
  const more = line.getByRole("button", { name: /^Show \d+ more tags?$/ });
  await expect(line.getByRole("link")).toHaveCount(tags.length);
  await expect(more).toHaveCount(0);
  const last = tag(page, tags[tags.length - 1]); // by name: stays this one once folded away
  await last.focus();
  await expect(last).toBeFocused();
  await page.setViewportSize({ width: 320, height: 800 });
  await expect(more).toBeVisible();
  await expect(last).toBeHidden();
  await expect(more).toBeFocused();
});

test("a todo's due chip is always shown, and tags fold beside it to two rows", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const a = word();
  const tags = ["alpha", "bravo", "delta"].map((n, i) => `g${i}${a}/${n}`);
  const p = await make(page, tags, "todo", { due: "2099-01-02" });
  await page.goto(`/p/${p.slug}`);
  await large(page);
  const line = row(page);
  await expect(line.getByRole("button", { name: /^Show \d+ more tags?$/ })).toBeVisible();
  await expect(line.locator(".duechip")).toBeVisible();
  await expect.poll(() => rowsOf(line)).toBeLessThanOrEqual(2);
  // Smaller text: all fit, so no +N
  await page.addStyleTag({ content: ":root { font-size: 12px; }" });
  await expect(line.getByRole("button", { name: /^Show \d+ more/ })).toHaveCount(0);
  await expect(line.getByRole("link")).toHaveCount(tags.length);
});

test("on a 360 px phone at 130% a todo's long first tag wraps inside its chip, never hidden", async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 780 });
  const a = word();
  const tags = [
    `a${a}/quite-a-long-name-for-alpha/and-more`,
    `b${a}/quite-a-long-name-for-bravo`,
    `c${a}/quite-a-long-name-for-delta`,
  ];
  const p = await make(page, tags, "todo", { due: "2099-01-02" });
  await page.goto(`/p/${p.slug}`);
  await large(page);
  const line = row(page);
  const more = line.getByRole("button", { name: /^Show \d+ more tags?$/ });
  await expect(more).toBeVisible();
  const links = line.getByRole("link");
  await expect(links.first()).toBeVisible();
  // Everything stays inside the line: a long path wraps after a "/", not sideways
  const fits = await line.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return [...el.querySelectorAll<HTMLElement>("a, button")]
      .filter((c) => !c.hidden)
      .every((c) => c.getBoundingClientRect().right <= r.right + 0.5);
  });
  expect(fits).toBe(true);
  // And +N still shows the rest
  await more.click();
  await expect(links).toHaveCount(tags.length);
});

test("the page does not scroll sideways at 320 to 430 px with 130% text", async ({ page }) => {
  const a = word();
  const p = await make(page, [`x${a}/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`, `y${a}`, `z${a}/b`]);
  await page.goto(`/p/${p.slug}`);
  await large(page);
  for (const width of [320, 360, 390, 430]) {
    await page.setViewportSize({ width, height: 800 });
    await expect(row(page)).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true);
    await expect.poll(() => rowsOf(row(page))).toBeLessThanOrEqual(2);
  }
});

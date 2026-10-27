// A page's tag chips (#345 follow-up): the last part of each tag, "+N" past two rows, ✦ for
// Claude's tags. The full tag stays what a chip searches for, what its accessible name says,
// and what the tag editor and the search chips show.
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

test("a chip says the last part of its tag, more of the path only to tell two apart", async ({
  page,
}) => {
  await page.setViewportSize({ width: 800, height: 900 }); // wide: no chip folds away to +N
  const [a, b] = [word(), word()];
  const p = await make(page, [`kind${a}/project-management`, `epics${a}/thoth`, `other${b}/thoth`]);
  await page.goto(`/p/${p.slug}`);
  await expect(tag(page, `kind${a}/project-management`)).toHaveText("#…/project-management"); // "…/": shortened
  // Two end the same: each says the part before as well
  await expect(tag(page, `epics${a}/thoth`)).toHaveText(`#epics${a}/thoth`); // the whole tag: no "…/"
  await expect(tag(page, `other${b}/thoth`)).toHaveText(`#other${b}/thoth`);
  // The full tag stays in the tooltip, and the chip still searches for it, children too
  await expect(tag(page, `kind${a}/project-management`)).toHaveAttribute(
    "title",
    `Tag kind${a}/project-management`,
  );
  await tag(page, `kind${a}/project-management`).click();
  await expect(page).toHaveURL(`/search?q=tag%3Akind${a}%2Fproject-management`);
  await expect(page.locator(".list li a strong")).toHaveText([/^Chips /]);
});

test("a short name does not hide a deeper tag's parent search", async ({ page }) => {
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
  await expect(ai).toHaveText("#…/robot");
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
  // The tag editor marks it the same way, by the same short name (the full tag its tooltip)
  await row(page).getByRole("button", { name: "Change tags" }).click();
  const chip = page.getByRole("button", { name: `Remove #ai${a}/robot, added by Claude` });
  await expect(chip).toHaveText("#…/robot");
  await expect(chip).toHaveAttribute("title", `#ai${a}/robot, added by Claude`);
  expect(await chip.evaluate((el) => getComputedStyle(el, "::before").content)).toBe('"✦"');
  await expect(page.getByRole("button", { name: `Remove #mine${a}`, exact: true })).toBeVisible();
});

test("the tag editor says the short name (the full path its tooltip), a filter on its full path", async ({
  page,
}) => {
  const a = word();
  const full = `deep${a}/er/leaf${a}`;
  const p = await make(page, [full]);
  await page.goto(`/p/${p.slug}`);
  await expect(tag(page, full)).toHaveText(`#…/leaf${a}`);
  await row(page).getByRole("button", { name: "Change tags" }).click();
  const chip = page.getByRole("button", { name: `Remove #${full}` });
  await expect(chip).toHaveText(`#…/leaf${a}`);
  await expect(chip).toHaveAttribute("title", `#${full}`);
  await page.keyboard.press("Escape");
  await page.goto(`/search?q=tag%3A${encodeURIComponent(full)}`);
  const on = page.getByRole("group", { name: "Filters on" });
  await expect(on.getByRole("button", { name: `Remove #${full}` })).toHaveText(`#${full}`); // in full: the focus of the search
});

test("at 390 px and 130% text, tags fold to two rows, then +N shows the rest in place", async ({
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
  await expect(more).toHaveText(`+${tags.length - shown}`);
  // + stays right after +N, in one box
  const plus = line.getByRole("button", { name: "Change tags" });
  expect(
    await more.evaluate((el, t) => el.nextElementSibling === t, await plus.elementHandle()),
  ).toBe(true);
  expect(await more.evaluate((el) => el.parentElement?.className)).toBe("last");
  // Tapping it shows them all, in place (no navigation), focus on the first one that was hidden
  const url = page.url();
  await more.click();
  await expect(more).toHaveCount(0);
  await expect(line.getByRole("link")).toHaveCount(tags.length);
  expect(page.url()).toBe(url);
  await expect(line.getByRole("link").nth(shown)).toBeFocused();
  // The + is still reachable, and a redraw (the tag editor closed) keeps them shown
  await plus.click();
  await page.keyboard.press("Escape");
  await expect(line.getByRole("link")).toHaveCount(tags.length);
  await expect(line.getByRole("button", { name: "Change tags" })).toBeFocused();
});

test("a focused tag that folds away on a narrower screen hands focus to +N", async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 800 });
  const a = word();
  const tags = [
    "alpha-centauri",
    "bravo-charlie",
    "delta-foxtrot",
    "golf-hotel",
    "india-juliet",
  ].map((n, i) => `t${i}${a}/${n}`);
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

test("on a 360 px phone at 130% a todo's long first tag is cut with …, not hidden", async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 780 });
  const a = word();
  const tags = [
    `a${a}/quite-a-long-name-for-alpha`,
    `b${a}/quite-a-long-name-for-bravo`,
    `c${a}/quite-a-long-name-for-delta`,
  ];
  const p = await make(page, tags, "todo", { due: "2099-01-02" });
  await page.goto(`/p/${p.slug}`);
  await large(page);
  const line = row(page);
  const more = line.getByRole("button", { name: /^Show \d+ more tags?$/ });
  await expect(more).toBeVisible();
  // A tag shows beside +N (before the fix none did, until +N was tapped)
  const links = line.getByRole("link");
  await expect(links).toHaveCount(1);
  await expect(links.first()).toBeVisible();
  await expect.poll(() => rowsOf(line)).toBeLessThanOrEqual(2);
  // Cut with …: it overflows its own box, and everything stays inside the line
  const fits = await line.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return [...el.querySelectorAll<HTMLElement>("a, button")]
      .filter((c) => !c.hidden)
      .every((c) => c.getBoundingClientRect().right <= r.right + 0.5);
  });
  expect(fits).toBe(true);
  const text = links.first().locator("span.tl");
  await expect(text).toHaveCSS("text-overflow", "ellipsis");
  // Really cut: the name is wider than the room it has
  expect(await text.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
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

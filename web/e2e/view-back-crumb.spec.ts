// Back goes up one level: from a page B reached by a link in A, Back is
// "‹ A" and goes to A; beside it, the list's name ("· Search") jumps straight back to the list.
// A page opened from a list has Back to it and no jump; desktop hides the jump.
import { expect, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

async function make(page: Page, text: string, kind = "note") {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text, kind } });
  return (await r.json()) as { page_id: string; slug: string };
}

const title = (page: Page) => page.locator(".page h1");
const back = (page: Page) => page.locator("header #back");
const jump = (page: Page) => page.locator("header #tolist");

/** A note A linking to a note B, A opened from the search screen, then the link followed. */
async function onB(page: Page, more = "") {
  const tag = ulid().slice(-6);
  const b = await make(page, `Crumb B ${tag}`);
  const name = `Crumb A ${tag}${more}`;
  const a = await make(page, `${name}\n\nSee [[${b.slug}|the B page]].`);
  await page.goto(`/search?q=${encodeURIComponent(tag)}`);
  await page.locator(".hits a", { hasText: name.slice(0, 20) }).click();
  await expect(title(page)).toHaveText(name);
  await expect(back(page)).toHaveAccessibleName("Back to Search");
  await expect(page.locator("#jump")).toBeHidden(); // Back goes to the list: no jump
  await page.locator(".page .body a", { hasText: "the B page" }).click();
  await expect(title(page)).toHaveText(`Crumb B ${tag}`);
  return { a, b, tag, name };
}

test("B, reached by a link in A: Back is ‹ A, then the jump to Search", async ({ page }) => {
  const { a, name } = await onB(page);
  await expect(page.locator("#backto")).toHaveText(name);
  await expect(back(page)).toHaveAccessibleName(`Back to ${name}`);
  await expect(jump(page)).toBeVisible();
  await expect(jump(page)).toHaveText("Search");
  await expect(jump(page)).toHaveAccessibleName("Back to Search");
  expect((await jump(page).boundingBox())?.height).toBeGreaterThanOrEqual(48);
  await expect(page.locator("#jump > span")).toHaveAttribute("aria-hidden", "true"); // the dot
  await expect(page.locator("#pos")).toBeEmpty(); // no pager: opened from a page

  // Back goes up one level, to A, whose Back is the list's and which has no jump
  await back(page).click();
  await expect(page).toHaveURL(`/p/${a.slug}`);
  await expect(title(page)).toHaveText(name);
  await expect(page.locator("#backto")).toHaveText("Search");
  await expect(page.locator("#jump")).toBeHidden();
  await back(page).click();
  await expect(page).toHaveURL(/\/search\?q=/);
  await expect(page.locator("#jump")).toBeHidden();
});

test("the jump from B goes straight back to the list, as left", async ({ page }) => {
  const { tag } = await onB(page);
  await jump(page).click();
  await expect(page).toHaveURL(/\/search\?q=/);
  await expect(page.getByRole("searchbox")).toHaveValue(tag);
  await expect(back(page)).toBeHidden();
  await expect(page.locator("#jump")).toBeHidden();
  // The phone's own Back still goes one at a time: forward is A, then B
  await page.goForward();
  await expect(title(page)).toHaveText(`Crumb A ${tag}`);
});

test("Delete on B lands back on A, whose Back and jump are A's", async ({ page }) => {
  const { a, b, name } = await onB(page);
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(`/p/${a.slug}`);
  await expect(title(page)).toHaveText(name);
  await expect(page.getByText("Page deleted")).toBeVisible();
  await expect(page.locator("#backto")).toHaveText("Search");
  await expect(page.locator("#jump")).toBeHidden();
  // Undo opens B again from A: up one level to A, the jump to Search
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page).toHaveURL(`/p/${b.slug}`);
  await expect(page.locator("#backto")).toHaveText(name);
  await expect(jump(page)).toHaveText("Search");
});

test.describe("at 360 px", () => {
  test.use({ viewport: { width: 360, height: 740 } });

  test("a long A title is cut with …; the jump, the badge and Settings stay whole", async ({
    page,
  }) => {
    const { name: long } = await onB(page, " with a title far too long for any phone's top bar");
    await expect(page.locator("#backto")).toHaveText(long);
    // The queue badge up too, as when a capture waits to upload
    await page.evaluate(() => {
      const q = document.getElementById("queue") as HTMLElement;
      q.hidden = false;
      q.textContent = "1 waiting";
    });
    const box = async (sel: string) =>
      (await page.locator(sel).boundingBox()) ?? { x: 0, width: 0 };
    const [label, tolist, badge, settings] = await Promise.all(
      ["#backto", "#tolist", "#queue", "#settings"].map(box),
    );
    expect(settings.x + settings.width).toBeLessThanOrEqual(360);
    expect(badge.x + badge.width).toBeLessThanOrEqual(settings.x);
    expect(tolist.x + tolist.width).toBeLessThanOrEqual(badge.x);
    expect(label.x + label.width).toBeLessThanOrEqual(tolist.x);
    expect(settings.width).toBe(48); // whole: Back's label is what gives up the width
    expect(badge.width).toBeGreaterThan(90); // "1 waiting", not squeezed
    expect(label.width).toBeGreaterThanOrEqual(90); // about 97 px of A's title beside the badge
    const cut = await page
      .locator("#backto")
      .evaluate((el) => [el.scrollWidth > el.clientWidth, getComputedStyle(el).textOverflow]);
    expect(cut).toEqual([true, "ellipsis"]);
    const whole = await jump(page).evaluate((el) => el.scrollWidth <= el.clientWidth);
    expect(whole).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      360,
    );
  });
});

test.describe("on a computer", () => {
  test.use({ viewport: { width: 1280, height: 800 }, isMobile: false, hasTouch: false });

  test("no jump; Back still goes up one level", async ({ page }) => {
    const { a, name } = await onB(page);
    await expect(page.locator("#backto")).toHaveText(name);
    await expect(page.locator("#jump")).toBeHidden();
    await back(page).click();
    await expect(page).toHaveURL(`/p/${a.slug}`);
  });
});

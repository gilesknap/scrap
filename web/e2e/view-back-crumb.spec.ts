// Back goes up one level: from a page B reached by a link in A, Back is "‹ A" and goes to A;
// beside it, the list's name ("· Search") jumps straight back to the list, on every phone and
// computer (a page has no nav). A page opened from a list has Back to it and no jump. Back
// names A as it is now (renamed, or replaced by its parent), and the top bar fits at 320 px.
import { expect, type Page, test } from "@playwright/test";
import { lowContrast } from "./contrast";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

async function make(page: Page, text: string, kind = "note") {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text, kind } });
  return (await r.json()) as { page_id: string; slug: string; id?: string };
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
  await page.locator(".hits a", { hasText: name.slice(0, 14) }).click();
  await expect(title(page)).toHaveText(name);
  await expect(back(page)).toHaveAccessibleName("Back to Search");
  await expect(page.locator("#jump")).toBeHidden(); // Back goes to the list: no jump
  await page.locator(".page .body a", { hasText: "the B page" }).click();
  await expect(title(page)).toHaveText(`Crumb B ${tag}`);
  return { a, b, tag, name };
}

/** Two captures in the upload queue, one waiting (no connection) and one refused. */
async function queueTwo(page: Page) {
  await page.route("**/api/captures", (r) =>
    r.request().postData()?.includes("Queued one")
      ? r.fulfill({ status: 400, json: { detail: "refused" } })
      : r.abort(),
  );
  await page.goto("/");
  for (const text of ["Queued one", "Queued two"]) {
    await page.getByRole("button", { name: "Note" }).click();
    await page.getByPlaceholder("Note or link").fill(text);
    await page.getByRole("button", { name: "Save" }).click();
  }
  await expect(page.locator("#queue")).toHaveText("1 waiting · 1 failed");
  await expect(page.locator("#queue")).toHaveAccessibleName("2 queued: 1 waiting · 1 failed");
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
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    await page.waitForFunction(() =>
      document.getAnimations().every((a) => a.playState !== "running"),
    );
    expect(await page.evaluate(lowContrast, ""), colorScheme).toEqual([]);
  }

  // A reload keeps both
  await page.reload();
  await expect(page.locator("#backto")).toHaveText(name);
  await expect(jump(page)).toHaveText("Search");

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

test("A renamed meanwhile: Forward to B names it as it is now", async ({ page }) => {
  const { a, name } = await onB(page);
  await page.goBack();
  await expect(title(page)).toHaveText(name);
  const p = await (await page.request.get(`/api/pages/${a.page_id}`)).json();
  const renamed = `Renamed ${name}`;
  const r = await page.request.patch(`/api/pages/${a.page_id}`, {
    data: { base_rev: p.rev, title: renamed },
  });
  expect(r.ok()).toBe(true);
  await page.reload();
  await expect(title(page)).toHaveText(renamed);
  await page.goForward();
  await expect(page.locator("#backto")).toHaveText(renamed);
  await expect(jump(page)).toHaveText("Search");
});

test("A opened cold: B has ‹ A and no jump; A goes up to its parent", async ({ page }) => {
  const tag = ulid().slice(-6);
  const b = await make(page, `Cold B ${tag}`);
  const a = await make(page, `Cold A ${tag}\n\nSee [[${b.slug}|the B page]].`, "todo");
  await page.goto(`/p/${a.slug}`);
  await expect(title(page)).toHaveText(`Cold A ${tag}`);
  await page.locator(".page .body a", { hasText: "the B page" }).click();
  await expect(title(page)).toHaveText(`Cold B ${tag}`);
  await expect(page.locator("#backto")).toHaveText(`Cold A ${tag}`);
  await expect(page.locator("#jump")).toBeHidden(); // no list behind A
  await back(page).click();
  await expect(title(page)).toHaveText(`Cold A ${tag}`);
  await expect(page.locator("#backto")).toHaveText("Todos"); // a todo's parent
  await back(page).click();
  await expect(page).toHaveURL(/\/todos$/);
  // A's entry is the Todos screen now: Forward to B names that, and goes there
  await page.goForward();
  await expect(title(page)).toHaveText(`Cold B ${tag}`);
  await expect(page.locator("#backto")).toHaveText("Todos");
  await back(page).click();
  await expect(page).toHaveURL(/\/todos$/);
});

test("from the Todos screen: the jump names Todos", async ({ page }) => {
  const tag = ulid().slice(-6);
  const b = await make(page, `Todo B ${tag}`);
  await make(page, `Todo A ${tag}\n\nSee [[${b.slug}|the B page]].`, "todo");
  await page.goto("/todos?view=all");
  await page.locator(".todos a", { hasText: `Todo A ${tag}` }).click();
  await expect(page.locator("#backto")).toHaveText("Todos");
  await page.locator(".page .body a", { hasText: "the B page" }).click();
  await expect(page.locator("#backto")).toHaveText(`Todo A ${tag}`);
  await expect(jump(page)).toHaveText("Todos");
  await jump(page).click();
  await expect(page).toHaveURL(/\/todos\?view=all$/);
});

test("A opened from a list keeps its pager after Back from B", async ({ page }) => {
  const { tag } = await onB(page);
  await expect(page.locator("#pos")).toBeEmpty();
  await back(page).click();
  await expect(title(page)).toHaveText(`Crumb A ${tag}`);
  await expect(page.locator("#pos .pager")).toBeVisible();
  await expect(page.locator("#jump")).toBeHidden();
});

for (const width of [320, 360]) {
  test.describe(`at ${width} px`, () => {
    test.use({ viewport: { width, height: 740 } });

    test("a long A title is cut with …; the jump, the compact badge and Settings stay whole", async ({
      page,
    }) => {
      await queueTwo(page);
      const { name: long } = await onB(page, " with a title far too long for any phone's top bar");
      await expect(page.locator("#backto")).toHaveText(long);
      const badge = page.locator("#queue");
      await expect(badge).toHaveAccessibleName("2 queued: 1 waiting · 1 failed"); // the words, though compact
      const box = async (sel: string) =>
        (await page.locator(sel).boundingBox()) ?? { x: 0, width: 0, height: 0 };
      const [label, tolist, q, settings] = await Promise.all(
        ["#backto", "#tolist", "#queue", "#settings"].map(box),
      );
      expect(settings.x + settings.width).toBeLessThanOrEqual(width);
      expect(q.x + q.width).toBeLessThanOrEqual(settings.x);
      expect(tolist.x + tolist.width).toBeLessThanOrEqual(q.x);
      expect(label.x + label.width).toBeLessThanOrEqual(tolist.x);
      expect(settings.width).toBe(48);
      expect(q.width).toBeLessThanOrEqual(64); // the dot and the count
      expect(q.height).toBeGreaterThanOrEqual(48);
      expect(label.width).toBeGreaterThanOrEqual(width === 360 ? 130 : 100);
      const cut = await page
        .locator("#backto")
        .evaluate((el) => [el.scrollWidth > el.clientWidth, getComputedStyle(el).textOverflow]);
      expect(cut).toEqual([true, "ellipsis"]);
      const whole = await jump(page).evaluate((el) => el.scrollWidth <= el.clientWidth);
      expect(whole).toBe(true);
      const wide = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(wide).toBeLessThanOrEqual(width);
    });
  });
}

for (const width of [320, 430]) {
  test.describe(`a page with its pager at ${width} px`, () => {
    test.use({ viewport: { width, height: 740 } });

    test("the pager and the queue badge: no sideways scroll", async ({ page }) => {
      await queueTwo(page);
      const tag = ulid().slice(-6);
      const a = await make(page, `Paged A ${tag} with a title long enough to be cut`);
      await page.goto(`/search?q=${tag}`);
      await page.locator(`.hits a[href="/p/${a.slug}"]`).first().click();
      await expect(page.locator("#pos .pager")).toBeVisible();
      await expect(page.locator("#queue")).toBeVisible();
      const wide = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(wide).toBeLessThanOrEqual(width);
      const s = (await page.locator("#settings").boundingBox()) as { x: number; width: number };
      expect(s.x + s.width).toBeLessThanOrEqual(width);
    });
  });
}

test.describe("Todos at 320 px", () => {
  test.use({ viewport: { width: 320, height: 740 } });

  test("the full badge, New todo and Settings fit: no sideways scroll", async ({ page }) => {
    await queueTwo(page);
    await page.goto("/todos");
    await expect(page.locator("#new")).toBeVisible();
    await expect(page.locator("#queue")).toHaveText("1 waiting · 1 failed");
    const wide = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(wide).toBeLessThanOrEqual(320);
  });
});

test.describe("on a computer", () => {
  test.use({ viewport: { width: 1280, height: 800 }, isMobile: false, hasTouch: false });

  test("the jump too (a page has no tabs); Back goes up one level", async ({ page }) => {
    const { a, name } = await onB(page);
    await expect(page.locator("#backto")).toHaveText(name);
    await expect(jump(page)).toHaveText("Search");
    await back(page).click();
    await expect(page).toHaveURL(`/p/${a.slug}`);
  });
});

test("a Todos view switch keeps Back's marks: a todo's Back names Todos", async ({ page }) => {
  const tag = ulid().slice(-6);
  const t = await make(page, `Switch todo ${tag}`, "todo");
  await page.goto("/");
  await page.locator('nav a[href="/todos"]').click();
  await expect(page).toHaveURL(/\/todos$/);
  await page.locator(".todos label", { hasText: "All" }).click();
  await expect(page).toHaveURL(/view=all/);
  await page.locator(`.todos a[href="/p/${t.slug}"]`).first().click();
  await expect(title(page)).toHaveText(`Switch todo ${tag}`);
  await expect(page.locator("#backto")).toHaveText("Todos");
  await back(page).click();
  await expect(page).toHaveURL(/\/todos\?view=all$/);
});

test("/recent after Capture in the same tab: a hit's Back names Search", async ({ page }) => {
  const tag = ulid().slice(-6);
  const n = await make(page, `Recent hit ${tag}`);
  await page.goto("/");
  await expect(page.locator("nav")).toBeVisible();
  await page.goto("/recent");
  await expect(page).toHaveURL("/search");
  await page.locator(`.list a[href="/p/${n.slug}"]`).first().click();
  await expect(title(page)).toHaveText(`Recent hit ${tag}`);
  await expect(page.locator("#backto")).toHaveText("Search");
});

test("A renamed in place by its editor, then its link: B's Back names A as it is now", async ({
  page,
}) => {
  const tag = ulid().slice(-6);
  const b = await make(page, `Ren B ${tag}`);
  const a = await make(page, `Ren A ${tag}\n\nSee [[${b.slug}|the B page]].`);
  await page.goto(`/search?q=${tag}`);
  await page.locator(`.hits a[href="/p/${a.slug}"]`).first().click();
  await expect(title(page)).toHaveText(`Ren A ${tag}`);
  await page.locator(".page .tools").getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Title").fill(`Fresh A ${tag}`);
  await page.locator(".editor").getByRole("button", { name: "Save" }).click();
  await expect(title(page)).toHaveText(`Fresh A ${tag}`);
  await page.locator(".page .body a", { hasText: "the B page" }).click();
  await expect(title(page)).toHaveText(`Ren B ${tag}`);
  await expect(page.locator("#backto")).toHaveText(`Fresh A ${tag}`);
});

test("sessionStorage refused: B's Back still names A, the jump Search", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "sessionStorage", {
      get() {
        throw new DOMException("no", "SecurityError");
      },
    });
  });
  const { name } = await onB(page);
  await expect(page.locator("#backto")).toHaveText(name);
  await expect(jump(page)).toHaveText("Search");
});

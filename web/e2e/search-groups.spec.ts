// Search results in sections (#309): the server orders by section so a page of results never
// splits one; the Group row, the section headings and counts, Later's types and the media:
// and later: terms, the Done fold, relative due, and no sideways scroll at phone widths.
import { expect, type Page, test } from "@playwright/test";
import { lowContrast } from "./contrast";
import { filters } from "./panel";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};
const day = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
};

const mark = ulid().slice(-8).toLowerCase(); // this run's own pages, whatever else is stored
const tag = `grp${mark}`;

const mine: string[] = []; // removed at the end: other specs count the pages in the store

async function make(page: Page, text: string, kind: string, patch: Record<string, unknown> = {}) {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text, kind } });
  const made = (await r.json()) as { page_id: string; slug: string };
  mine.push(made.page_id);
  if (Object.keys(patch).length) {
    const p = await page.request.patch(`/api/pages/${made.page_id}`, { data: patch });
    expect(p.ok()).toBeTruthy();
  }
  return made;
}

const later = (media: string, status = "open") => ({
  tags: [tag],
  fields: { media_type: media, subtype: SUBTYPE[media], status },
});
const SUBTYPE: Record<string, string> = {
  book: "read",
  film: "watch",
  podcast: "listen",
  game: "play",
};

test.beforeAll(async ({ request }) => {
  const page = { request } as Page;
  await make(page, `Zebra ${mark} book`, "consume", later("book"));
  await make(page, `Apple ${mark} film`, "consume", later("film"));
  await make(page, `Mango ${mark} cast`, "consume", later("podcast"));
  await make(page, `Quince ${mark} game`, "consume", later("game"));
  await make(page, `Banana ${mark} read`, "consume", later("book", "done"));
  await make(page, `Late ${mark}`, "todo", { tags: [tag], due: day(-2) });
  await make(page, `Today ${mark}`, "todo", { tags: [tag], due: day(0) });
  await make(page, `Far ${mark}`, "todo", { tags: [tag], due: day(20) });
});

test.afterAll(async ({ request }) => {
  for (const id of mine) await request.delete(`/api/pages/${id}`);
});

const heads = (page: Page) => page.locator(".groups h2.label");

test("Later alone: grouped by type, each section counted, Done last and folded", async ({
  page,
}) => {
  await page.goto(`/search?q=${encodeURIComponent(`kind:later tag:${tag}`)}`);
  await expect(heads(page)).toHaveText([
    "To read · 1",
    "To watch · 1",
    "To listen · 1",
    "To play · 1",
  ]);
  await expect(page.locator(".donefold summary")).toHaveText("Done · 1");
  await expect(page.locator(".donefold")).not.toHaveAttribute("open");
  // the type heading is a link to that type alone
  await heads(page).nth(1).locator("a").click();
  await expect(page).toHaveURL(/later%3Awatch|later:watch/);
  await expect(page.locator(".list li a strong")).toHaveText([`Apple ${mark} film`]);
  await page.goBack();
  await expect(heads(page)).toHaveCount(4);
});

test("the Group row: A–Z, Tag and None, and the order of the page is the server's", async ({
  page,
}) => {
  await page.goto(`/search?q=${encodeURIComponent(`tag:${tag} kind:later`)}`);
  const panel = await filters(page);
  await panel.getByRole("button", { name: "Group by A–Z" }).click();
  await expect(heads(page).first()).toHaveText("A");
  const letters = await heads(page).allTextContents();
  expect(letters.map((t) => t[0])).toEqual([...letters.map((t) => t[0])].sort());
  await (await filters(page)).getByRole("button", { name: "Not grouped" }).click();
  await expect(heads(page)).toHaveCount(0);
  await expect(page.locator(".list li")).toHaveCount(5);
});

test("media: and later: narrow the list, by either spelling the server knows", async ({
  page,
  request,
}) => {
  const q = (s: string) => `/api/search?q=${encodeURIComponent(`tag:${tag} ${s}`)}`;
  const titles = async (s: string) =>
    ((await (await request.get(q(s))).json()) as { title: string }[]).map((h) => h.title).sort();
  expect(await titles("media:book")).toEqual([`Banana ${mark} read`, `Zebra ${mark} book`]);
  expect(await titles("media:film later:read")).toEqual([]);
  expect(await titles("later:listen")).toEqual([`Mango ${mark} cast`]);
  expect(await titles("-media:book kind:later")).toHaveLength(3);
  await page.goto(`/search?q=${encodeURIComponent(`tag:${tag} media:book`)}`);
  await expect(page.locator(".list li")).toHaveCount(2);
});

test("Todos: Now sections, Due sections, and a relative due: reaches the server", async ({
  page,
}) => {
  await page.goto(`/search?q=${encodeURIComponent(`kind:todo tag:${tag}`)}`);
  await expect(heads(page).first()).toHaveText(/^Overdue · 1/);
  await (await filters(page)).getByRole("button", { name: "Group by Due" }).click();
  await expect(heads(page)).toHaveText([/^Overdue/, /^Today/, /^Later/]);
  await page.goto(`/search?q=${encodeURIComponent(`kind:todo tag:${tag} due:<=7d`)}`);
  await expect(page.locator(".list li")).toHaveCount(2); // overdue and today, not 20 days on
});

test("a page of results never splits a section, and nothing scrolls sideways", async ({
  page,
  request,
}) => {
  // The first page (limit 2) holds whole sections: A–Z, so its letters never come back later
  const hits = async (offset: number) =>
    (
      (await (
        await request.get(
          `/api/search?q=${encodeURIComponent(`tag:${tag} kind:later group:letter`)}&limit=2&offset=${offset}`,
        )
      ).json()) as { title: string }[]
    ).map((h) => h.title[0]);
  const first = [...(await hits(0)), ...(await hits(2)), ...(await hits(4))];
  expect(first).toEqual([...first].sort());
  for (const width of [320, 390, 430]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`/search?q=${encodeURIComponent(`kind:later tag:${tag}`)}`);
    await expect(heads(page).first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    );
  }
});

for (const scheme of ["light", "dark"] as const) {
  test(`section headings are readable in ${scheme}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.goto(`/search?q=${encodeURIComponent(`kind:later tag:${tag}`)}`);
    await expect(heads(page).first()).toBeVisible();
    expect(await page.evaluate(lowContrast, ""), scheme).toEqual([]);
  });
}

test("the editor's Type line sets a Later page's type", async ({ page }) => {
  const made = await make(page, `Edit ${mark}`, "consume", later("book"));
  await page.goto(`/p/${made.slug}`);
  await page.getByRole("button", { name: /^Edit/ }).click();
  const line = page.locator("details.fold > summary", { hasText: /^Type/ });
  await expect(line).toContainText("Book · To read");
  await line.click();
  await page.getByLabel("Type").selectOption("film");
  await expect(line).toContainText("Film · To watch");
  await page.getByRole("button", { name: /^Save/ }).click();
  await expect(page.locator("details.fold")).toHaveCount(0); // the editor has closed
  const got = (await (await page.request.get(`/api/pages/${made.page_id}`)).json()) as {
    fields: Record<string, string>;
  };
  expect(got.fields).toMatchObject({ media_type: "film", subtype: "watch" });
});

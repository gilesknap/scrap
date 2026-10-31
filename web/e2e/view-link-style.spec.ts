// Every text link is underlined, and its colour says whose it is (design-system.md, Links): the
// owner's own text amber and underlined in its own colour; Claude's and the app's links ink, a thin
// underline in --line-strong (--ink-2 on the Claude card's --sunk, where --line-strong fails 3:1);
// rows, chips and the like not underlined. And the Claude card's Topics fold and its state line's
// gap (#375). Named to run after smoke.spec.ts, which wants an empty store.
import { expect, type Locator, type Page, test } from "@playwright/test";
import { deletedAfterEach, ulid } from "./helpers";
import { filters } from "./panel";

const word = () => ulid().slice(-6).toLowerCase();

// Every page made here is deleted after, so other specs' counts of the store's pages hold
const made = deletedAfterEach();

async function note(page: Page, text: string, tags: string[] = [], kind?: string) {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text, kind } });
  expect(r.ok()).toBe(true);
  const got = (await r.json()) as { page_id: string; slug: string };
  made.push(got.page_id);
  if (tags.length)
    expect((await page.request.patch(`/api/pages/${got.page_id}`, { data: { tags } })).ok()).toBe(
      true,
    );
  return got;
}

/** The page's answer as if Claude were on, in this state, with these related pages and topics. */
async function asRead(
  page: Page,
  slug: string,
  state: string | null,
  related: object[] = [],
  topics: object[] = [],
) {
  await page.route(`**/api/pages/${slug}`, async (r) => {
    if (r.request().method() !== "GET") return r.continue();
    const json = await (await r.fetch()).json();
    await r.fulfill({
      json: { ...json, enrich: { on: true, error: null, state, summary: null }, related, topics },
    });
  });
}

/** A design token's colour as the browser computes it (rgb), here and now. */
const token = (page: Page, name: string) =>
  page.evaluate((n) => {
    const probe = document.body.appendChild(document.createElement("span"));
    probe.style.color = `var(${n})`;
    const c = getComputedStyle(probe).color;
    probe.remove();
    return c;
  }, name);

/** A link's computed colour, decoration line, decoration colour and thickness. */
const looks = (a: Locator) =>
  a.evaluate((el) => {
    const s = getComputedStyle(el);
    return {
      color: s.color,
      line: s.textDecorationLine,
      lineColor: s.textDecorationColor,
      thickness: s.textDecorationThickness,
      weight: s.fontWeight,
    };
  });

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(colorScheme, () => {
    test.beforeEach(async ({ page }) => {
      await page.emulateMedia({ colorScheme });
    });

    test("a link in the owner's text is amber, underlined in its own colour", async ({ page }) => {
      const n = await note(page, `Owner link ${word()}\n\nSee [the docs](https://example.com/x).`);
      await page.goto(`/p/${n.slug}`);
      const link = page.locator(".page .md").getByRole("link", { name: "the docs" });
      await expect(link).toBeVisible();
      const l = await looks(link);
      expect(l.color).toBe(await token(page, "--accent-ink"));
      expect(l.line).toBe("underline");
      expect(l.lineColor).toBe(l.color);
    });

    test("Claude's Related and Topics links are ink, underlined in --ink-2 on the card", async ({
      page,
    }) => {
      const x = await note(page, `Style x ${word()}`);
      const n = await note(page, `Style host ${word()}`);
      await asRead(
        page,
        n.slug,
        "done",
        [{ id: x.page_id, slug: x.slug, title: "Style x", kind: "note", via: "claude" }],
        [{ id: x.page_id, slug: x.slug, title: "A topic", kind: "claude" }],
      );
      await page.goto(`/p/${n.slug}`);
      const ink = await token(page, "--ink");
      const line = await token(page, "--ink-2"); // --line-strong fails 3:1 on --sunk
      for (const [where, name] of [
        [".enrich .related:not(.topics)", "Style x"],
        [".enrich .topics", "A topic"],
      ]) {
        const link = page.locator(where).getByRole("link", { name });
        await expect(link, where).toBeVisible();
        const l = await looks(link);
        expect(l, where).toMatchObject({ color: ink, line: "underline", lineColor: line });
        expect(l.weight, `${where}: regular, not a heading`).toBe("400");
        expect(l.thickness, where).toBe("1px");
      }
    });

    test("Clear filters is ink-2 (a quiet control), underlined in --line-strong", async ({
      page,
    }) => {
      const w = word();
      await note(page, `Clear ${w} one`, ["clearme"]);
      await page.goto(`/search?q=${w}%20tag%3Aclearme`);
      const panel = await filters(page);
      const clear = panel.getByRole("button", { name: "Clear filters" });
      await expect(clear).toBeVisible();
      expect(await looks(clear)).toMatchObject({
        color: await token(page, "--ink-2"),
        line: "underline",
        lineColor: await token(page, "--line-strong"),
      });
    });

    test("a link card inside the owner's text is not underlined", async ({ page }) => {
      const n = await note(page, `Card ${word()}\n\nhttps://example.com/some/path`, [], "consume");
      await page.goto(`/p/${n.slug}`);
      const card = page.locator(".page .md .linkcard").first();
      await expect(card).toBeVisible();
      expect((await looks(card)).line).toBe("none");
    });

    test("a search row and a tag chip are not underlined", async ({ page }) => {
      const w = word();
      const p = await note(page, `Exempt ${w}`, [`chip${w}`]);
      await page.goto(`/search?q=${w}`);
      const row = page.locator(".hits li a").first();
      await expect(row).toBeVisible();
      expect((await looks(row)).line).toBe("none");
      await page.goto(`/p/${p.slug}`);
      const chip = page.locator(".page .tags").getByRole("link", { name: `Tag chip${w}` });
      await expect(chip).toBeVisible();
      expect((await looks(chip)).line).toBe("none");
    });
  });
}

test("Topics is a fold: open, a line per topic with its icon, and closing it is remembered", async ({
  page,
}) => {
  const [a, b] = [await note(page, `Topic a ${word()}`), await note(page, `Topic b ${word()}`)];
  const n = await note(page, `Topic host ${word()}`);
  await asRead(
    page,
    n.slug,
    "done",
    [],
    [
      { id: a.page_id, slug: a.slug, title: "First topic", kind: "claude" },
      { id: b.page_id, slug: b.slug, title: "Second topic", kind: "claude" },
    ],
  );
  await page.goto(`/p/${n.slug}`);
  const fold = page.locator(".enrich details.topics");
  await expect(fold.locator("summary")).toHaveText("Topics");
  await expect(fold).toHaveAttribute("open", "");
  await expect(fold.locator("li")).toHaveText(["First topic", "Second topic"]);
  await expect(fold.locator("li a .i")).toHaveCount(2); // each its icon
  await expect(fold.getByRole("link", { name: "First topic" })).toHaveAttribute(
    "href",
    `/p/${a.slug}`,
  );
  await fold.locator("summary").click();
  await expect(fold).not.toHaveAttribute("open", "");
  expect(await page.evaluate(() => localStorage.getItem("scrap.fold.Topics"))).toBe("shut");
  await page.reload();
  await expect(page.locator(".enrich details.topics")).not.toHaveAttribute("open", "");
  // And opened again, forgotten as shut
  await page.locator(".enrich details.topics summary").click();
  await expect(page.locator(".enrich details.topics")).toHaveAttribute("open", "");
  expect(await page.evaluate(() => localStorage.getItem("scrap.fold.Topics"))).toBeNull();
});

test("a card with only topics is the card with that one fold", async ({ page }) => {
  const a = await note(page, `Only a ${word()}`);
  const n = await note(page, `Only host ${word()}`);
  await asRead(
    page,
    n.slug,
    null,
    [],
    [{ id: a.page_id, slug: a.slug, title: "Only topic", kind: "claude" }],
  );
  await page.goto(`/p/${n.slug}`);
  const card = page.locator(".enrich");
  await expect(card.locator("details")).toHaveCount(1);
  await expect(card.locator("details.topics")).toBeVisible();
  await expect(card.getByRole("heading", { name: "About this page" })).toBeVisible();
});

test("a queued card with Topics has at least 8 px between its state line and Topics", async ({
  page,
}) => {
  const a = await note(page, `Gap a ${word()}`);
  const n = await note(page, `Gap host ${word()}`);
  await asRead(
    page,
    n.slug,
    "queued",
    [],
    [{ id: a.page_id, slug: a.slug, title: "Gap topic", kind: "claude" }],
  );
  await page.goto(`/p/${n.slug}`);
  const state = page.locator(".enrich .state");
  await expect(state).toHaveText("Waiting for Claude");
  const topics = page.locator(".enrich details.topics");
  await expect(topics).toBeVisible();
  const [s, t] = await Promise.all([state.boundingBox(), topics.boundingBox()]);
  if (!s || !t) throw new Error("not drawn");
  expect(t.y - (s.y + s.height)).toBeGreaterThanOrEqual(8);
});

// Claude's topic pages (#261): the Topics tab and its index (grouped by area, filtered, a dot on
// what changed since this device last looked), the topic page (the Topic by Claude badge, the
// owner's notes first, the synthesis in About this page, its Sources with a ✕ and Put back), a
// source's Topics line, and the Topic label in search. The topic is synthetic: e2e/topics.py
// makes one of three notes, its synthesis by a fake Claude.
import { execFileSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";
import { lowContrast } from "./contrast";

type Made = {
  slug: string;
  title: string;
  word: string;
  sources: { id: string; slug: string; title: string }[];
};

function topic(): Made {
  const data = process.env.SCRAP_E2E_DATA as string;
  const args = ["run", "--locked", "python", "web/e2e/topics.py", data];
  const out = execFileSync("uv", args, { cwd: "..", encoding: "utf8" });
  return JSON.parse(out.trim().split("\n").pop() || "null");
}

/** The page's one Claude card. */
const card = (page: Page) => page.getByRole("region", { name: "About this page" });
const row = (page: Page, title: string) => page.locator(".topics .list li", { hasText: title });

test("the Topics tab lists topics by area, filters them, and dots what changed", async ({
  page,
}) => {
  const t = topic();
  await page.goto("/");
  const tab = page.locator('nav a[href="/topics"]');
  await expect(tab).toHaveText("Topics");
  await tab.click();
  await expect(page).toHaveURL(/\/topics$/);
  await expect(tab).toHaveAttribute("aria-current");
  // Its row: the title, its synthesis's lead, how many sources and when, under its area
  const r = row(page, t.title);
  await expect(r).toContainText("builds IOCs from YAML");
  await expect(r).toContainText("3 sources ·");
  const group = page.locator(".topics section").filter({ hasText: t.title });
  await expect(group.locator("h2")).toHaveText(/^epics · \d+$/);
  // The first look ever: no dot (all would have one)
  await expect(r.locator(".new")).toHaveCount(0);
  // The filter box narrows the list as typed, and says how many
  const filter = page.getByRole("searchbox", { name: "Filter topics" });
  await filter.fill(t.word.toUpperCase());
  await expect(page.locator(".topics .list li")).toHaveCount(1);
  await expect(page.locator(".topics .count")).toHaveText(/^1 of \d+ topics/);
  await filter.fill(`${t.word} nothing-like-it`);
  await expect(page.getByText("No topics match.")).toBeVisible();
  await filter.fill(t.word);

  // Opened from it: Back names Topics and comes back to the list as filtered
  await r.getByRole("link").click();
  await expect(page.getByRole("heading", { level: 1, name: t.title })).toBeVisible();
  await expect(page.locator("#back")).toHaveAccessibleName("Back to Topics");
  await page.locator("#back").click();
  await expect(filter).toHaveValue(t.word);
  await expect(page.locator(".topics .list li")).toHaveCount(1);

  // Another topic made since this device looked: a dot on it alone, said in words too
  const u = topic();
  await page.reload();
  await page.getByRole("searchbox", { name: "Filter topics" }).fill("");
  await expect(row(page, u.title).locator(".new")).toHaveAccessibleName("new or changed");
  await expect(row(page, t.title).locator(".new")).toHaveCount(0);
  await page.screenshot({ path: "test-results/topics.png", fullPage: true });
  // Refine opens the same topics in Search, grouped by area there too (#314)
  await page.getByRole("link", { name: "Refine in Search: is:topic" }).click();
  await expect(page).toHaveURL(/\/search\?q=is(%3A|:)topic/);
  await expect(page.locator(".groups h2.label").first()).toBeVisible();
  await page.goBack();
  // Every text on the screen (the dot is no text) meets AA, in both themes
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    await page.waitForTimeout(400); // the colour transitions done
    expect(await page.evaluate(lowContrast, ""), colorScheme).toEqual([]);
  }
});

test("with no topics, the screen says what topics are and when they come", async ({ page }) => {
  await page.route("**/api/topics", (route) => route.fulfill({ json: [] }));
  await page.goto("/topics");
  await expect(page.getByText("No topics yet.")).toBeVisible();
  await expect(page.getByText(/Each week Claude looks across your pages/)).toBeVisible();
});

test("a topic page: the badge, the owner's notes first, the synthesis, its sources", async ({
  page,
}) => {
  const t = topic();
  await page.goto(`/p/${t.slug}`);
  // Claude's, said in its meta line; tapped, the Topics screen
  const badge = page.locator(".page > .meta").getByRole("link", { name: "Topic by Claude" });
  await expect(badge).toHaveAttribute("href", "/topics");
  // The owner's notes come first: empty, so where they go is said, before Claude's card
  const notes = page.locator(".page > .notes");
  await expect(notes).toContainText("Your notes on this topic");
  const s = card(page);
  const [nBox, cBox] = [await notes.boundingBox(), await s.boundingBox()];
  expect(nBox && cBox && nBox.y < cBox.y).toBe(true);
  // The synthesis: its lead the Summary, the rest In detail, open (it is what the page is for)
  await expect(s.locator(".summary")).toHaveText(/builds IOCs from YAML/);
  const detail = s.locator("details.writeup");
  await expect(detail).toHaveAttribute("open", "");
  await expect(s.getByRole("heading", { name: "Key facts" })).toBeVisible();
  await expect(s.getByRole("link", { name: `the ${t.word} schema` })).toHaveAttribute(
    "href",
    `/p/${t.sources[1].slug}`,
  );
  // Guidance for Claude, reused from the write-up
  await expect(s.getByText("Guidance for Claude")).toBeVisible();
  // Sources: each title (a link) and kind, with a ✕; not listed again under Related
  const sources = s.locator("details.sources");
  await expect(sources.locator("> summary")).toHaveText("Sources · 3");
  const items = sources.locator("li");
  await expect(items).toHaveCount(3);
  await expect(items.first()).toContainText(`${t.sources[0].title} · Note`);
  await expect(s.locator(".related")).toHaveCount(0);

  // ✕: taken out, kept and marked, with Undo and Put back; the synthesis is due again
  await sources.getByRole("button", { name: `Take out ${t.sources[2].title}` }).click();
  await expect(page.getByText(`Taken out: ${t.sources[2].title}`)).toBeVisible();
  await expect(sources.locator("> summary")).toHaveText("Sources · 2");
  const out = sources.locator("li.out");
  await expect(out).toContainText(`${t.sources[2].title} · Note · taken out`);
  const api = async () => (await (await page.request.get(`/api/pages/${t.slug}`)).json()).topic;
  expect((await api()).sources.map((x: { excluded: number }) => x.excluded)).toEqual([0, 0, 1]);
  await page.screenshot({ path: "test-results/topic-page.png", fullPage: true });
  await out.getByRole("button", { name: `Put back ${t.sources[2].title}` }).click();
  await expect(page.getByText(`Put back: ${t.sources[2].title}`)).toBeVisible();
  await expect(sources.locator("> summary")).toHaveText("Sources · 3");
  await expect(sources.locator("li.out")).toHaveCount(0);
  // Undo, from the toast, puts it back too
  await sources.getByRole("button", { name: `Take out ${t.sources[0].title}` }).click();
  await page.locator(".toast").getByRole("button", { name: "Undo" }).click();
  await expect(sources.locator("> summary")).toHaveText("Sources · 3");
  expect((await api()).sources.every((x: { excluded: number }) => !x.excluded)).toBe(true);

  // The whole page bar its toolbar and the toast (their own specs check them): the card, the
  // notes line and the meta line with its badge are all checked
  await expect(page.locator(".enrich .sources li")).toHaveCount(3);
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    await page.waitForTimeout(400); // the controls' colour transitions done
    expect(await page.evaluate(lowContrast, ".page > .tools, .toast"), colorScheme).toEqual([]);
  }
});

test("a ✕ that fails says so and can be pressed again; offline, the ✕ is off", async ({ page }) => {
  const t = topic();
  await page.goto(`/p/${t.slug}`);
  const x = card(page).getByRole("button", { name: `Take out ${t.sources[0].title}` });
  await page.route("**/topic/sources/**", (route) =>
    route.fulfill({ status: 500, json: { detail: "boom" } }),
  );
  await x.click();
  await expect(page.locator(".toast")).toContainText("Not taken out");
  await expect(x).toBeEnabled();
  await expect(card(page).locator("details.sources > summary")).toHaveText("Sources · 3");
  await page.unroute("**/topic/sources/**");
  // Offline: off, with a tooltip saying why; back online, on again
  await page.context().setOffline(true);
  await expect(x).toBeDisabled();
  await expect(x).toHaveAttribute("title", /Offline/);
  await page.context().setOffline(false);
  await expect(x).toBeEnabled();
  // Done: focus back on that source's button, now Put back
  await x.click();
  await expect(
    card(page).getByRole("button", { name: `Put back ${t.sources[0].title}` }),
  ).toBeFocused();
});

test("a topic shown from search loses its dot on the Topics screen", async ({ page }) => {
  await page.goto("/topics"); // a first look: what is seen is kept from now
  await expect(page.locator("nav a[aria-current]")).toHaveText("Topics");
  const t = topic(); // made since: a dot
  await page.goto("/topics");
  await expect(row(page, t.title).locator(".new")).toHaveCount(1);
  await page.goto(`/search?q=${t.word}`);
  await page.locator(".list.hits li a", { hasText: t.title }).click();
  await expect(page.getByRole("heading", { level: 1, name: t.title })).toBeVisible();
  await page.goto("/topics");
  await expect(row(page, t.title)).toBeVisible();
  await expect(row(page, t.title).locator(".new")).toHaveCount(0);
});

test("a source names its topics; search labels a topic page", async ({ page }) => {
  const t = topic();
  await page.goto(`/p/${t.sources[0].slug}`);
  const s = card(page);
  const line = s.locator(".topicsline");
  await expect(line).toHaveText(`Topics: ${t.title}`);
  await expect(line.getByRole("link", { name: t.title })).toHaveAttribute("href", `/p/${t.slug}`);
  // Its synthesis cites this page: in Related, both ways, marked
  await expect(s.locator(".related li", { hasText: t.title })).toContainText("in a topic");
  // A source it does not cite is in it all the same
  await page.goto(`/p/${t.sources[2].slug}`);
  await expect(card(page).locator(".topicsline")).toHaveText(`Topics: ${t.title}`);

  // Search: the topic first, labelled, with the topic's icon
  await page.goto(`/search?q=${t.word}`);
  const hits = page.locator(".list.hits > li");
  await expect(hits.first()).toContainText(t.title);
  await expect(hits.first().locator(".sub .topic")).toHaveText("Topic");
  await expect(page.locator(".list.hits .sub .topic")).toHaveCount(1);
});

test.describe("on a computer (a mouse, a wide window)", () => {
  test.use({ viewport: { width: 1000, height: 800 }, isMobile: false, hasTouch: false });

  test("at 900 px, with a long development version, the tabs clear the wordmark", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 900, height: 700 });
    await page.goto("/topics");
    await page.locator("#ver").evaluate((v) => (v.textContent = "v0.9.1.dev123+g1a2b3c4d"));
    const logo = await page.locator(".logo").boundingBox();
    const first = await page.locator("nav a").first().boundingBox();
    const last = await page.locator("nav a").last().boundingBox();
    const cog = await page.locator("#settings").boundingBox();
    expect(first && logo && first.x > logo.x + logo.width).toBe(true);
    expect(last && cog && last.x + last.width < cog.x).toBe(true);
    await page.screenshot({ path: "test-results/topics-900.png" });
    // A page (no nav) keeps its top bar on the page's 720 px column: Back over the title
    const t = topic();
    await page.goto(`/p/${t.slug}`);
    const back = await page.locator("#back").boundingBox();
    const h1 = await page.locator(".page h1").boundingBox();
    expect(back && h1 && Math.abs(back.x - h1.x) < 24).toBe(true);
  });

  test("the four tabs fit the top bar, clear of the wordmark and Settings", async ({ page }) => {
    await page.goto("/topics");
    const tabs = page.locator("nav a");
    await expect(tabs).toHaveCount(4);
    await expect(page.locator("nav a[aria-current]")).toHaveText("Topics");
    const first = await tabs.first().boundingBox();
    const last = await tabs.last().boundingBox();
    const logo = await page.locator(".logo").boundingBox();
    const cog = await page.locator("#settings").boundingBox();
    expect(first && logo && first.x > logo.x + logo.width).toBe(true);
    expect(last && cog && last.x + last.width < cog.x).toBe(true);
    // One row, in the top bar
    const ys = await tabs.evaluateAll((as) => as.map((a) => a.getBoundingClientRect().y));
    expect(new Set(ys).size).toBe(1);
  });
});

// Finding things (#84): refine chips under search results, a page's tags, browse by tag.
// Runs after smoke.spec.ts (which wants an empty store); e2e/tagged.py adds synthetic pages.
import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import { lowContrast } from "./contrast";
import { filters, filtersButton, openFold } from "./panel";

/** A photo whose reading failed (e2e/draw.py): its Retry draws the page again. */
function failedPhoto(): { slug: string } {
  const data = process.env.SCRAP_E2E_DATA as string;
  const args = ["run", "--locked", "python", "web/e2e/draw.py", data, "failed"];
  const out = execFileSync("uv", args, { cwd: "..", encoding: "utf8" });
  return JSON.parse(out.trim().split("\n").pop() || "null");
}

let slugs: string[] = [];
test.beforeAll(() => {
  const data = process.env.SCRAP_E2E_DATA as string;
  const args = ["run", "--locked", "python", "web/e2e/tagged.py", data];
  const out = execFileSync("uv", args, { cwd: "..", encoding: "utf8" });
  slugs = JSON.parse(out.trim().split("\n").pop() || "[]");
});

type Page = import("@playwright/test").Page;
type Locator = import("@playwright/test").Locator;
const hits = (page: Page) => page.locator(".hits li a strong");
const openTags = (scope: Locator) => openFold(scope, "Tags");

test("refine chips narrow a search and come off again", async ({ page }) => {
  await page.goto("/search?q=zephyr+fence");
  await expect(hits(page)).toHaveCount(3);
  await expect(page.locator(".found").getByText("3 pages")).toBeVisible();
  await expect(page.getByRole("searchbox")).not.toBeFocused(); // no keyboard over the chips
  await expect(page.getByRole("group", { name: "Filters on" })).toHaveCount(0); // none on: no row
  const panel = await filters(page);
  // The results' top tags, each with its count
  const chip = panel.getByRole("button", { name: "Filter by #zephyr/garden" });
  await expect(chip).toHaveText("#zephyr/garden2");
  const box = await chip.boundingBox();
  expect(box?.height).toBeGreaterThanOrEqual(44);
  await chip.click();
  await expect(page).toHaveURL(/q=zephyr%20fence%20tag%3Azephyr%2Fgarden$/);
  await expect(hits(page)).toHaveCount(2);
  await expect(filtersButton(page)).toHaveAccessibleName("Filters, 1 on");
  await expect(panel).toBeVisible(); // open while choosing
  // The filter on, as a chip under the box: a tap takes it out
  const off = page
    .getByRole("group", { name: "Filters on" })
    .getByRole("button", { name: "Remove #zephyr/garden" });
  await off.click();
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr fence");
  await expect(hits(page)).toHaveCount(3);
  await expect(off).toHaveCount(0);
  await page.getByRole("searchbox").fill("zephyr -fence");
  await expect(hits(page)).toHaveText(["Zephyr shed plans"]);
  await page.getByRole("searchbox").fill("zephyr");
  await page.getByRole("radiogroup", { name: "Kind" }).getByText("Later").click();
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr kind:later");
  await expect(hits(page)).toHaveText(["Zephyr fence book"]);
});

test("a page's tag searches for it, children too", async ({ page }) => {
  await page.goto(`/p/${slugs[0]}`);
  // One line under the title, most used tag first; each a 44 px target
  const row = page.locator(".page h1 + .tags");
  await expect(row.getByRole("link")).toHaveText(["#zephyr/garden", "#diy"]);
  const [line, chip] = [await row.boundingBox(), await row.getByRole("link").first().boundingBox()];
  expect(chip?.height).toBeGreaterThanOrEqual(44);
  expect(line?.height).toBeLessThan(50);
  await page.locator(".page .tags").getByRole("link", { name: "#zephyr/garden" }).click();
  await expect(page).toHaveURL(/\/search\?q=tag%3Azephyr%2Fgarden$/);
  await expect(hits(page)).toHaveCount(3); // and zephyr/garden/shed
});

test("browse tags as a tree, then search one", async ({ page }) => {
  await page.goto("/search");
  await (await filters(page)).getByRole("link", { name: "All tags" }).click();
  await expect(page).toHaveURL(/\/tags$/);
  const tree = page.locator(".tagtree");
  await expect(tree.getByRole("link", { name: "#zephyr 4" })).toBeVisible();
  await expect(tree.getByRole("link", { name: "#garden 3" })).toBeHidden();
  await tree.getByRole("button", { name: "Show tags under zephyr" }).click();
  await expect(tree.getByRole("link", { name: "#garden 3" })).toBeVisible();
  await page.getByRole("searchbox", { name: "Filter tags" }).fill("shed");
  await expect(tree.getByRole("link", { name: "#shed 1" })).toBeVisible(); // its parents open
  await expect(tree.getByRole("link", { name: "#books 1" })).toBeHidden();
  await tree.getByRole("link", { name: "#shed 1" }).click();
  await expect(hits(page)).toHaveText(["Zephyr shed plans"]);
});

test("the new views meet AA contrast, in both themes", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    await page.goto("/search?q=zephyr+tag%3Azephyr");
    await expect(page.getByRole("group", { name: "Filters on" })).toBeVisible();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} refine`).toEqual([]);
    const panel = await filters(page);
    await panel.getByRole("button", { name: "Dates…" }).click();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} filters`).toEqual([]);
    await page.goto(`/p/${slugs[0]}`);
    await page.locator(".page .tags a").first().waitFor();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} page tags`).toEqual([]);
    await page.goto("/tags");
    await page.locator(".tagtree a").first().waitFor();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} tags`).toEqual([]);
  }
});

test("a time range, from a preset or dates, by edit or creation date", async ({ page }) => {
  await page.goto("/search");
  await expect(filtersButton(page)).toHaveAccessibleName("Filters"); // no query yet
  const box = await page.getByRole("searchbox").boundingBox();
  expect(box?.width).toBeGreaterThan(300); // the whole width: nothing beside it
  await page.getByRole("searchbox").fill("zephyr");
  await expect(hits(page)).toHaveCount(4);
  const panel = await filters(page);
  await panel.getByRole("button", { name: "Edited in the past week" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr after:1w");
  await expect(panel.getByRole("button", { name: "Edited in the past week" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await panel.getByRole("button", { name: "Edited in the past month" }).click(); // one at a time
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr after:1m");
  await expect(page.getByText("No matches")).toBeVisible(); // made in January 2026
  await page.getByRole("button", { name: "Remove past month" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr");
  await panel.getByRole("button", { name: "Dates…" }).click();
  await expect(panel.getByRole("button", { name: "Dates…" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  // Applied as picked: no Apply to find
  await panel.getByLabel("From", { exact: true }).fill("2026-01-02");
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr after:2026-01-02");
  await panel.getByLabel("To", { exact: true }).fill("2026-01-03");
  await expect(page.getByRole("searchbox")).toHaveValue(
    "zephyr after:2026-01-02 before:2026-01-03",
  );
  await expect(hits(page)).toHaveCount(2);
  await panel.getByRole("button", { name: "By created date" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue(/ date:created$/);
  await expect(hits(page)).toHaveCount(2);
  await panel.getByRole("link", { name: "All tags" }).click();
  await expect(page).toHaveURL(/\/tags$/);
  await page.goBack(); // the search, as it was
  await expect(page.getByRole("searchbox")).toHaveValue(/ date:created$/);
});

test("tags are edited on the page, and in the editor (a row's swipe opens it)", async ({
  page,
}) => {
  const id = "01E2ETAGED17".padEnd(26, "0");
  const made = await page.request.post("/api/captures", { data: { id, text: "Tag me please" } });
  const { slug } = await made.json();
  await page.goto(`/p/${slug}`);
  const line = page.locator(".page h1 + .tags");
  await line.getByRole("button", { name: "Add tags" }).click();
  const box = page.getByRole("textbox", { name: "Add a tag" });
  await expect(box).toBeFocused();
  await box.fill("#Quokka Pen");
  await box.press("Enter");
  await box.fill("quokka/feed,");
  await expect(page.getByRole("button", { name: "Remove #quokka pen" })).toBeVisible();
  await page.getByRole("button", { name: "Remove #quokka pen" }).click();
  await box.fill("zebu"); // still in the box when saved: it counts
  await page.getByRole("button", { name: "Save" }).click();
  await expect(line.getByRole("link")).toHaveText(["#quokka/feed", "#zebu"]);
  await expect(line.getByRole("button", { name: "Change tags" })).toBeVisible();
  // In the editor: Cancel puts them back, Save sends them with the text
  await page.locator(".page .tools").getByRole("button", { name: "Edit" }).click();
  const editor = page.locator(".editor");
  await openTags(editor); // folded to a line: "Tags 2 · #quokka/feed #zebu"
  await expect(editor.locator("details.fold > summary", { hasText: /^Tags/ })).toContainText(
    "2 · #quokka/feed #zebu",
  );
  await editor.getByRole("button", { name: "Remove #zebu" }).click();
  await editor.getByRole("textbox", { name: "Add a tag" }).fill("quokka/water");
  await editor.getByRole("button", { name: "Save" }).click();
  await expect(editor).toBeHidden();
  await expect(line.getByRole("link")).toHaveText(["#quokka/feed", "#quokka/water"]);
  await page.goto("/search?q=tag%3Aquokka");
  await expect(hits(page)).toHaveText(["Tag me please"]);
  // Suggestions: as typed, the tags in use that match, in our own row (no datalist menu)
  await page.goto(`/p/${slug}`);
  await page.getByRole("button", { name: "Change tags" }).click();
  await expect(page.locator(".tagedit datalist")).toHaveCount(0);
  await box.fill("garden");
  const matching = page.getByRole("group", { name: "Matching tags" });
  await expect(
    matching.getByRole("button", { name: "Add #zephyr/garden", exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(lowContrast, ""), "tag editor").toEqual([]);
  await matching.getByRole("button", { name: "Add #zephyr/garden", exact: true }).click();
  await expect(box).toHaveValue(""); // what was typed is now that tag
  await expect(page.getByRole("button", { name: "Remove #zephyr/garden" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
});

test("the most used tags are offered one tap each, on a page and in the composer", async ({
  page,
}) => {
  const id = "01E2ETAGTP01".padEnd(26, "0");
  const made = await page.request.post("/api/captures", { data: { id, text: "Top tags here" } });
  const { slug, page_id } = await made.json();
  // [tag, pages under it, pages with that very tag]
  const tags = async () =>
    (await (await page.request.get("/api/tags")).json()) as [string, number, number][];
  // Children enough that their parent, which no page has, has more pages under it than any
  // tag has: ranked by that count, it would be offered first
  const most = Math.max(...(await tags()).map((r) => r[1]));
  const kids: string[] = [];
  for (let i = 0; i <= most; i++) {
    const r = await page.request.post("/api/captures", {
      data: { id: `01E2ETAGTK${String(i).padStart(2, "0")}`.padEnd(26, "0"), text: `Kid ${i}` },
    });
    const kid = (await r.json()).page_id as string;
    await page.request.patch(`/api/pages/${kid}`, { data: { tags: [`zzparent/k${i}`] } });
    kids.push(kid);
  }
  /** The most used tags not on the page, as the chips should offer them. */
  const expected = async (on: string[]) => {
    return (await tags())
      .filter((r) => r[2] > 0)
      .sort((a, b) => b[2] - a[2])
      .map(([t]) => t)
      .filter((t) => !on.includes(t))
      .slice(0, 6)
      .map((t) => `#${t}`);
  };
  await page.goto(`/p/${slug}`);
  await page.getByRole("button", { name: "Add tags" }).click();
  const top = page.getByRole("group", { name: "Most used tags" });
  const want = await expected([]);
  expect(want).toHaveLength(6);
  await expect(top.getByRole("button")).toHaveText(want);
  expect(want).not.toContain("#zzparent"); // a parent no page was given
  expect((await tags()).find((r) => r[0] === "zzparent")?.[1]).toBe(most + 1);
  // A tap adds it (no typing): a chip to remove, and it leaves the offer
  const first = want[0];
  await top.getByRole("button", { name: `Add ${first}`, exact: true }).click();
  await expect(page.getByRole("button", { name: `Remove ${first}`, exact: true })).toBeVisible();
  await expect(top.getByRole("button")).toHaveText(await expected([first.slice(1)]));
  await expect(top.getByRole("button").first()).toBeFocused(); // the chip now in its place
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".page h1 + .tags").getByRole("link")).toHaveText([first]);
  const saved = await (await page.request.get(`/api/pages/${page_id}`)).json();
  expect(saved.tags).toEqual([first.slice(1)]);
  // Off again: the other tests count that tag's pages
  await page.request.patch(`/api/pages/${page_id}`, { data: { tags: [] } });
  // The composer offers them too
  await page.goto("/");
  await page.getByRole("button", { name: "Note", exact: true }).click();
  await openTags(page.locator(".editor"));
  const offered = page.locator(".editor").getByRole("group", { name: "Most used tags" });
  await expect(offered.getByRole("button")).toHaveText(await expected([]));
  // A double tap adds one tag, not the one that slid under the finger too
  await offered.getByRole("button").nth(1).dblclick();
  await expect(page.locator(".editor .tagchips .facet")).toHaveCount(1);
  await expect(offered.getByRole("button")).toHaveCount(6);
  page.once("dialog", (d) => d.accept());
  await page.locator(".editor").getByRole("button", { name: "Cancel" }).click();
  await expect(page.locator(".editor")).toBeHidden();
  for (const kid of kids) await page.request.delete(`/api/pages/${kid}`); // for the other tests
});

test("Order writes sort: into the query, and the results follow it", async ({ page }) => {
  await page.goto("/search?q=zephyr");
  const order = (await filters(page)).getByRole("group", { name: "Order" });
  await expect(order.getByRole("button", { name: "Best match" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(order.getByRole("button", { name: "Due soonest" })).toHaveCount(0); // todos only
  await order.getByRole("button", { name: "A–Z" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr sort:title");
  await expect(hits(page)).toHaveText([
    "Zephyr fence book",
    "Zephyr fence paint",
    "Zephyr fence repair",
    "Zephyr shed plans",
  ]);
  await expect(order.getByRole("button", { name: "A–Z" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("radiogroup", { name: "Kind" }).getByText("Todos").click();
  await expect(page.getByRole("button", { name: "Remove A–Z" })).toBeVisible(); // on show
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr sort:title kind:todo");
  await expect(page).toHaveURL(/\/search\?q=zephyr%20sort%3Atitle%20kind%3Atodo$/);
  await expect(hits(page)).toHaveText(["Zephyr fence paint", "Zephyr fence repair"]);
  // A todo's orders, now the search is of todos
  await expect(order.getByRole("button", { name: "Due soonest" })).toBeVisible();
  await expect(order.getByRole("button", { name: "Priority" })).toBeVisible();
  await order.getByRole("button", { name: "Oldest" }).click(); // one order at a time
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr kind:todo -sort:created");
  await expect(hits(page)).toHaveText(["Zephyr fence repair", "Zephyr fence paint"]);
  await order.getByRole("button", { name: "Best match" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr kind:todo");
  // With nothing typed: every page, in that order
  await page.goto("/search");
  const order2 = (await filters(page)).getByRole("group", { name: "Order" });
  await expect(order2.getByRole("button", { name: "Last edited" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await order2.getByRole("button", { name: "A–Z" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("sort:title");
  await expect(hits(page).first()).toBeVisible();
  const titles = await hits(page).allTextContents();
  expect(titles.length).toBeGreaterThan(4);
  expect(titles).toEqual(
    [...titles].sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase())),
  );
  expect(await page.evaluate(lowContrast, ""), "order").toEqual([]);
});

test("an open tag edit survives the page being drawn again; Cancel and Escape close it", async ({
  page,
}) => {
  const { slug } = failedPhoto();
  await page.goto(`/p/${slug}`);
  const retry = page.getByRole("button", { name: "Retry" });
  await expect(retry).toBeVisible();
  await page.getByRole("button", { name: "Add tags" }).click();
  const box = page.getByRole("textbox", { name: "Add a tag" });
  await box.fill("wombat");
  await box.press("Enter");
  await box.fill("still typing");
  await Promise.all([page.waitForResponse("**/api/pages/*"), retry.click()]); // drawn again
  await expect(page.getByText("Waiting: Claude ingest is off")).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove #wombat" })).toBeVisible();
  await expect(box).toHaveValue("still typing");
  await page.getByRole("button", { name: "Cancel" }).click();
  const tagsButton = page.locator(".page h1 + .tags").getByRole("button", { name: "Add tags" });
  await expect(tagsButton).toBeFocused(); // back where it was
  await expect(page.getByText("Waiting: Claude ingest is off")).toBeVisible(); // the page as it is now
  await tagsButton.click();
  await box.fill("x");
  await box.press("Escape");
  await expect(box).toBeHidden();
  await expect(tagsButton).toBeFocused();
  expect((await (await page.request.get(`/api/pages/${slug}`)).json()).tags).toEqual([]);
});

test("a kept draft brings back only the tags changed in it", async ({ page }) => {
  const made = async (text: string) => {
    const r = await page.request.post("/api/captures", {
      data: { id: `01E2EDRAFT${text.length}`.padEnd(26, "0"), text },
    });
    return (await r.json()) as { page_id: string; slug: string };
  };
  const tagsOf = async (id: string) =>
    (await (await page.request.get(`/api/pages/${id}`)).json()).tags as string[];
  const editor = page.locator(".editor");
  const open = async (slug: string) => {
    await page.goto(`/p/${slug}`);
    await page.locator(".page .tools").getByRole("button", { name: /^Edit/ }).click();
    await expect(editor).toBeVisible();
    await openTags(editor);
  };
  // Only the text changed in the draft: tags set elsewhere since are kept, not overwritten
  const a = await made("Draft text only");
  await open(a.slug);
  await editor.getByRole("textbox", { name: "Body" }).fill("Draft text only, edited");
  await page.goBack(); // keeps the draft
  await page.request.patch(`/api/pages/${a.page_id}`, { data: { tags: ["elsewhere"] } });
  await open(a.slug);
  await expect(editor.getByRole("button", { name: "Remove #elsewhere" })).toBeVisible();
  await editor.getByRole("button", { name: "Save" }).click();
  await expect(editor).toBeHidden();
  expect(await tagsOf(a.page_id)).toEqual(["elsewhere"]);
  // Tags changed in the draft (one still in the box) come back, and are saved
  const b = await made("Draft with its own tags");
  await open(b.slug);
  await editor.getByRole("textbox", { name: "Add a tag" }).fill("drafted");
  await page.goBack();
  await page.request.patch(`/api/pages/${b.page_id}`, { data: { tags: ["elsewhere"] } });
  await open(b.slug);
  await expect(editor.getByRole("button", { name: "Remove #drafted" })).toBeVisible();
  await editor.getByRole("button", { name: "Save" }).click();
  await expect(editor).toBeHidden();
  expect(await tagsOf(b.page_id)).toEqual(["drafted"]);
});

// New pages with tags: the composer has the same tags box, sent with the capture
const composer = (page: import("@playwright/test").Page) => page.locator(".editor");
async function pageFor(page: import("@playwright/test").Page, word: string) {
  const find = async () =>
    (await (await page.request.get(`/api/search?q=${word}`)).json()) as { slug: string }[];
  await expect.poll(find).toHaveLength(1); // uploaded
  const [hit] = await find();
  return (await (await page.request.get(`/api/pages/${hit.slug}`)).json()) as {
    tags: string[];
    kind: string;
  };
}

test("a new note gets its tags as it is saved", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" }); // no transition caught midway below
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill("Wallaby feeder plans");
  await composer(page).locator(".kinds").getByText("Todo").click();
  await openTags(composer(page));
  const box = composer(page).getByRole("textbox", { name: "Add a tag" });
  await box.fill("#Wallaby Pen");
  await box.press("Enter"); // a tag, not a save
  await expect(composer(page)).toBeVisible();
  await box.fill("wallaby/food,");
  await box.fill("gone");
  await box.press("Enter");
  await composer(page).getByRole("button", { name: "Remove #gone" }).click();
  await expect(composer(page).getByRole("button", { name: "Remove #wallaby pen" })).toBeVisible();
  await box.fill("zephyr/gar"); // the tags in use that match, a tap each
  await expect(
    composer(page)
      .getByRole("group", { name: "Matching tags" })
      .getByRole("button", { name: "Add #zephyr/garden", exact: true }),
  ).toBeVisible();
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} composer tags`).toEqual([]);
  }
  await box.fill("wallaby/water"); // still in the box when saved: it counts
  await composer(page).getByRole("button", { name: "Save" }).click();
  await expect(composer(page)).toBeHidden();
  const saved = await pageFor(page, "wallaby+feeder");
  expect(saved.kind).toBe("todo");
  expect([...saved.tags].sort()).toEqual(["wallaby pen", "wallaby/food", "wallaby/water"]);
  await page.goto("/search?q=tag%3Awallaby");
  await expect(hits(page)).toHaveText(["Wallaby feeder plans"]); // indexed at once
});

test("tags on a photo captured offline go with it when the queue sends it", async ({
  page,
  context,
}) => {
  await page.goto("/");
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();
  await context.setOffline(true);
  await page.goto("/");
  const [gallery] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByText("Gallery").click(),
  ]);
  await gallery.setFiles({ name: "q.png", mimeType: "image/png", buffer: Buffer.alloc(900, 7) });
  await page.getByPlaceholder("Caption (optional)").fill("Quoll den offline");
  await openTags(composer(page));
  const box = composer(page).getByRole("textbox", { name: "Add a tag" });
  await box.fill("quoll, den");
  await expect(composer(page).getByRole("button", { name: "Remove #den" })).toBeVisible();
  await composer(page).getByRole("button", { name: "Save" }).click();
  await expect(page.locator("#queue")).toHaveText("1 waiting");
  await page.reload(); // the queued tags survive a reload
  await expect(page.locator("#queue")).toHaveText("1 waiting");
  await context.setOffline(false);
  await expect(page.locator("#queue")).toBeHidden();
  expect((await pageFor(page, "quoll+den")).tags.sort()).toEqual(["den", "quoll"]);
});

test("a composer's tags are kept in its draft when the app is killed", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill("Bilby burrow survey");
  await openTags(composer(page));
  const box = composer(page).getByRole("textbox", { name: "Add a tag" });
  await box.fill("bilby");
  await box.press("Enter");
  await box.fill("burrow"); // typed, not yet added: kept too
  await page.waitForTimeout(800); // the draft is kept a moment after typing
  await page.reload(); // as if the app was killed
  await page.getByRole("button", { name: "Note" }).click();
  await expect(composer(page).getByText("Restored your unsaved draft.")).toBeVisible();
  await openTags(composer(page));
  await expect(composer(page).getByRole("button", { name: "Remove #bilby" })).toBeVisible();
  await expect(composer(page).getByRole("button", { name: "Remove #burrow" })).toBeVisible();
  await composer(page).getByRole("button", { name: "Save" }).click();
  await expect(composer(page)).toBeHidden();
  expect((await pageFor(page, "bilby+burrow")).tags.sort()).toEqual(["bilby", "burrow"]);
  // Saved: the next note starts with no tags
  await page.getByRole("button", { name: "Note" }).click();
  await expect(composer(page).locator(".tagchips button")).toHaveCount(0);
});

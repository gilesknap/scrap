// Finding things (#84): refine chips under search results, a page's tags, browse by tag.
// Runs after smoke.spec.ts (which wants an empty store); e2e/tagged.py adds synthetic pages.
import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import { lowContrast } from "./contrast";

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

const hits = (page: import("@playwright/test").Page) => page.locator(".hits li a strong");
const refine = (page: import("@playwright/test").Page) =>
  page.getByRole("group", { name: "Refine" });
/** Open the Filters sheet. */
async function filters(page: import("@playwright/test").Page) {
  await refine(page)
    .getByRole("button", { name: /^Filters/ })
    .click();
  const sheet = page.getByRole("dialog", { name: "Filters" });
  await expect(sheet).toBeVisible();
  return sheet;
}

test("refine chips narrow a search and come off again", async ({ page }) => {
  await page.goto("/search?q=zephyr+fence");
  await expect(hits(page)).toHaveCount(3);
  await expect(page.locator(".found").getByText("3 pages")).toBeVisible();
  await expect(page.getByRole("searchbox")).not.toBeFocused(); // no keyboard over the chips
  const chip = refine(page).getByRole("button", { name: "#zephyr/garden 2" });
  const box = await chip.boundingBox();
  expect(box?.height).toBeGreaterThanOrEqual(44);
  await chip.click();
  await expect(page).toHaveURL(/q=zephyr%20fence%20tag%3Azephyr%2Fgarden$/);
  await expect(hits(page)).toHaveCount(2);
  const sheet = await filters(page);
  await sheet.getByRole("button", { name: "Personal 1" }).click();
  await expect(hits(page)).toHaveText(["Zephyr fence repair"]);
  await sheet.getByRole("button", { name: "Done", exact: true }).click();
  await page.getByRole("button", { name: "Remove tag:zephyr/garden" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr fence is:personal");
  await expect(hits(page)).toHaveCount(1);
  await page.getByRole("searchbox").fill("zephyr -fence");
  await expect(hits(page)).toHaveText(["Zephyr shed plans"]);
  await page.getByRole("searchbox").fill("zephyr");
  await page.getByRole("radiogroup", { name: "Kind" }).getByText("Reads").click();
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr kind:read");
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
  await (await filters(page)).getByRole("link", { name: "Browse tags" }).click();
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
    await expect(refine(page)).toBeVisible();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} refine`).toEqual([]);
    const sheet = await filters(page);
    await sheet.getByRole("button", { name: "Dates…" }).click();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} filters`).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
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
  await expect(refine(page).getByRole("button", { name: "Filters" })).toBeVisible(); // no query yet
  const box = await page.getByRole("searchbox").boundingBox();
  expect(box?.width).toBeGreaterThan(300); // the whole width: nothing beside it
  await page.getByRole("searchbox").fill("zephyr");
  await expect(hits(page)).toHaveCount(4);
  let sheet = await filters(page);
  await sheet.getByRole("button", { name: "Edited in the past week" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr after:1w");
  await expect(sheet.getByRole("button", { name: "Edited in the past week" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await sheet.getByRole("button", { name: "Edited in the past month" }).click(); // one at a time
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr after:1m");
  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
  await expect(page.getByText("No matches")).toBeVisible(); // made in January 2026
  await page.getByRole("button", { name: "Remove after:1m" }).click();
  sheet = await filters(page);
  await sheet.getByRole("button", { name: "Dates…" }).click();
  await sheet.getByLabel("From", { exact: true }).fill("2026-01-02");
  await sheet.getByLabel("To", { exact: true }).fill("2026-01-03");
  await sheet.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue(
    "zephyr after:2026-01-02 before:2026-01-03",
  );
  await expect(hits(page)).toHaveCount(2);
  await sheet.getByRole("button", { name: "By created date" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue(/ date:created$/);
  await expect(hits(page)).toHaveCount(2);
  await sheet.getByRole("link", { name: "Browse tags" }).click();
  await expect(page).toHaveURL(/\/tags$/);
  await expect(sheet).toBeHidden();
  await page.goBack(); // the search, as the sheet left it (its entry gone)
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
  const box = page.getByRole("combobox", { name: "Add a tag" });
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
  await editor.getByRole("button", { name: "Remove #zebu" }).click();
  await editor.getByRole("combobox", { name: "Add a tag" }).fill("quokka/water");
  await editor.getByRole("button", { name: "Save" }).click();
  await expect(editor).toBeHidden();
  await expect(line.getByRole("link")).toHaveText(["#quokka/feed", "#quokka/water"]);
  await page.goto("/search?q=tag%3Aquokka");
  await expect(hits(page)).toHaveText(["Tag me please"]);
  // Suggestions: the tags in use
  await page.goto(`/p/${slug}`);
  await page.getByRole("button", { name: "Change tags" }).click();
  await expect(page.locator(".tagedit datalist option[value='quokka/water']")).toHaveCount(1);
  expect(await page.evaluate(lowContrast, ""), "tag editor").toEqual([]);
});

test("Sort writes sort: into the query, and the results follow it", async ({ page }) => {
  await page.goto("/search?q=zephyr");
  await filters(page);
  const sort = page.getByRole("combobox", { name: "Sort" });
  await expect(sort).toHaveValue(""); // Best match
  await sort.selectOption({ label: "Title Z–A" });
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr -sort:title");
  await expect(hits(page)).toHaveText([
    "Zephyr shed plans",
    "Zephyr fence repair",
    "Zephyr fence paint",
    "Zephyr fence book",
  ]);
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await expect(page.getByRole("button", { name: "Remove -sort:title" })).toBeVisible(); // on show
  await page.getByRole("radiogroup", { name: "Kind" }).getByText("Todos").click();
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr -sort:title kind:todo");
  await expect(hits(page)).toHaveText(["Zephyr fence repair", "Zephyr fence paint"]);
  await filters(page);
  await sort.selectOption({ label: "Oldest" });
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr kind:todo -sort:created");
  await expect(hits(page)).toHaveText(["Zephyr fence repair", "Zephyr fence paint"]);
  await sort.selectOption({ label: "Best match" });
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr kind:todo");
  // With nothing typed: every page, in that order
  await page.goto("/search");
  await (await filters(page)).getByRole("combobox", { name: "Sort" }).selectOption({
    label: "Title A–Z",
  });
  await expect(page.getByRole("searchbox")).toHaveValue("sort:title");
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await expect(hits(page).first()).toBeVisible();
  const titles = await hits(page).allTextContents();
  expect(titles.length).toBeGreaterThan(4);
  expect(titles).toEqual(
    [...titles].sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase())),
  );
  expect(await page.evaluate(lowContrast, ""), "sort").toEqual([]);
});

test("an open tag edit survives the page being drawn again; Cancel and Escape close it", async ({
  page,
}) => {
  const { slug } = failedPhoto();
  await page.goto(`/p/${slug}`);
  const retry = page.getByRole("button", { name: "Retry" });
  await expect(retry).toBeVisible();
  await page.getByRole("button", { name: "Add tags" }).click();
  const box = page.getByRole("combobox", { name: "Add a tag" });
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
  await editor.getByRole("combobox", { name: "Add a tag" }).fill("drafted");
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
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill("Wallaby feeder plans");
  await composer(page).locator(".kinds").getByText("Todo").click();
  const box = composer(page).getByRole("combobox", { name: "Add a tag" });
  await box.fill("#Wallaby Pen");
  await box.press("Enter"); // a tag, not a save
  await expect(composer(page)).toBeVisible();
  await box.fill("wallaby/food,");
  await box.fill("gone");
  await box.press("Enter");
  await composer(page).getByRole("button", { name: "Remove #gone" }).click();
  await expect(composer(page).getByRole("button", { name: "Remove #wallaby pen" })).toBeVisible();
  await expect(composer(page).locator("datalist option[value='zephyr/garden']")).toHaveCount(1);
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
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
  const box = composer(page).getByRole("combobox", { name: "Add a tag" });
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
  const box = composer(page).getByRole("combobox", { name: "Add a tag" });
  await box.fill("bilby");
  await box.press("Enter");
  await box.fill("burrow"); // typed, not yet added: kept too
  await page.waitForTimeout(800); // the draft is kept a moment after typing
  await page.reload(); // as if the app was killed
  await page.getByRole("button", { name: "Note" }).click();
  await expect(composer(page).getByText("Restored your unsaved draft.")).toBeVisible();
  await expect(composer(page).getByRole("button", { name: "Remove #bilby" })).toBeVisible();
  await expect(composer(page).getByRole("button", { name: "Remove #burrow" })).toBeVisible();
  await composer(page).getByRole("button", { name: "Save" }).click();
  await expect(composer(page)).toBeHidden();
  expect((await pageFor(page, "bilby+burrow")).tags.sort()).toEqual(["bilby", "burrow"]);
  // Saved: the next note starts with no tags
  await page.getByRole("button", { name: "Note" }).click();
  await expect(composer(page).locator(".tagchips button")).toHaveCount(0);
});

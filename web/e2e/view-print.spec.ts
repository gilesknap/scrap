// Printing a page (css/print.css): the title, the text and Claude's card's text, with every
// fold open; no app chrome, no controls; a page break only between sections. Print media is
// emulated, so this checks what is shown and the break properties, not where Chrome breaks.
// The e2e server runs with Claude off, so the page's answer is given what Claude would have
// made of it (as view-claude-cards.spec.ts does). Named to run after smoke.spec.ts, which
// wants an empty store.
import { execFileSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";
import { ulid } from "./helpers";

async function note(page: Page, text: string) {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text } });
  expect(r.ok()).toBe(true);
  return (await r.json()) as { page_id: string; slug: string };
}

/** The page's answer as if Claude were on and had (or had not) read it. */
async function asRead(page: Page, slug: string, enrich: object, related: object[] = []) {
  await page.route(`**/api/pages/${slug}`, async (r) => {
    if (r.request().method() !== "GET") return r.continue();
    const json = await (await r.fetch()).json();
    await r.fulfill({ json: { ...json, enrich: { on: true, error: null, ...enrich }, related } });
  });
}

const breakAfter = (page: Page, selector: string) =>
  page
    .locator(selector)
    .first()
    .evaluate((el) => getComputedStyle(el).breakAfter);

test("print: the title, the text and Claude's card's text, folds open, no chrome or controls", async ({
  page,
}) => {
  const other = await note(page, `Print other ${ulid().slice(-6)}`);
  const n = await note(
    page,
    [
      `Print note ${ulid().slice(-6)}`,
      "",
      "### First part",
      "",
      "A paragraph.",
      "",
      "| A | B |",
      "| - | - |",
      "| 1 | 2 |",
      "",
      "The last block of the first part.",
      "",
      "## Second part",
      "",
      "More text.",
    ].join("\n"),
  );
  await asRead(page, n.slug, { state: "done", summary: "What the note is about." }, [
    { id: other.page_id, slug: other.slug, title: "The other note", kind: "note", via: "claude" },
  ]);
  // The Summary fold closed on screen (its stored key): it still prints open
  await page.addInitScript(() => localStorage.setItem("scrap.fold.Summary", "shut"));
  await page.goto(`/p/${n.slug}`);
  const card = page.locator(".enrich.claude");
  await expect(card.locator("details", { hasText: "Summary" })).not.toHaveAttribute("open", "");
  await expect(page.locator(".page > .tools")).toBeVisible();

  await page.emulateMedia({ media: "print" });
  await expect(page.locator(".page > h1")).toBeVisible();
  await expect(page.locator(".page .md table")).toBeVisible();
  await expect(card).toBeVisible();
  // The card's title moves into its first fold's heading (print.css says why)
  const title = await card
    .locator("summary")
    .first()
    .evaluate((el) => getComputedStyle(el, "::before").content);
  expect(title).toBe('"About this page"');
  await expect(card.getByText("What the note is about.")).toBeVisible();
  await expect(card.getByRole("link", { name: "The other note" })).toBeVisible();
  for (const hidden of [
    "header",
    "nav",
    ".page .meta",
    ".page .tags",
    ".page > .tools",
    ".page .originals",
    ".enrich .ingest",
  ])
    for (const el of await page.locator(hidden).all()) await expect(el).toBeHidden();
  for (const el of await card.locator("button, [role=status]").all()) await expect(el).toBeHidden();

  // Breaks: each block asks to stay with the next, except the one before an h2
  expect(await breakAfter(page, ".page .md > h3")).toBe("avoid");
  expect(await breakAfter(page, ".page .md > p")).toBe("avoid");
  expect(await breakAfter(page, ".page .md > :has(+ h2)")).toBe("auto");

  // Back on screen: the tools bar is there again
  await page.emulateMedia({ media: "screen" });
  await expect(page.locator(".page > .tools")).toBeVisible();
});

test("print: a card with no text (never read) is left out", async ({ page }) => {
  const n = await note(page, `Print unread ${ulid().slice(-6)}`);
  await asRead(page, n.slug, { state: null, summary: null });
  await page.goto(`/p/${n.slug}`);
  const card = page.locator(".enrich.claude");
  await expect(card.getByRole("button", { name: "Generate" })).toBeVisible();
  await page.emulateMedia({ media: "print" });
  await expect(card).toBeHidden();
  await expect(page.locator(".page > h1")).toBeVisible();
});

test("print: a board prints its photo, not its drawing, and no Photo/Drawing tabs", async ({
  page,
}) => {
  // e2e/draw.py stores a synthetic board with a fake Claude answer (as whiteboard.spec.ts does)
  const data = process.env.SCRAP_E2E_DATA as string;
  const out = execFileSync("uv", ["run", "--locked", "python", "web/e2e/draw.py", data], {
    cwd: "..",
    encoding: "utf8",
  });
  const b = JSON.parse(out.trim().split("\n").pop() || "null") as { slug: string };
  await page.goto(`/p/${b.slug}`);
  const panel = page.locator(".photo-panel");
  await expect(panel.locator(".tabs")).toBeVisible();
  await expect(panel.locator(".pair > .drawing")).toBeVisible();
  await page.emulateMedia({ media: "print" });
  await expect(panel.locator(".tabs")).toBeHidden();
  await expect(panel.locator(".pair > .drawing")).toBeHidden();
  await expect(panel.locator(".pair > .orig:not(.drawing)")).toBeVisible();
  await expect(panel.locator(".claude")).toBeHidden();
});

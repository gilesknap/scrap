// Claude's write-up of a board page (#256): In detail, a fold of the page's one Claude card
// (About this page) under the text, plainly
// Claude's, with who wrote it and when, its links as page links, the owner's guidance, its
// versions with Restore, and Regenerate. The board is synthetic: e2e/writeup.py stores it and
// two write-ups with a fake Claude. The e2e server runs with Claude off, so Regenerate is
// checked against the page answered as if Claude were on.
import { execFileSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";
import { lowContrast } from "./contrast";

function board(): { slug: string; target: string } {
  const data = process.env.SCRAP_E2E_DATA as string;
  const args = ["run", "--locked", "python", "web/e2e/writeup.py", data];
  const out = execFileSync("uv", args, { cwd: "..", encoding: "utf8" });
  return JSON.parse(out.trim().split("\n").pop() || "null");
}

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};
/** The page's one Claude card: the write-up is its In detail fold. */
const section = (page: Page) => page.getByRole("region", { name: "About this page" });
/** The write-up's fold opened, as once tapped (it is folded until then, and remembered). */
const opened = (page: Page) =>
  page.addInitScript(() => localStorage.setItem("scrap.fold.writeup", "open"));

test("a board's write-up shows apart from its text, with guidance and versions", async ({
  page,
}) => {
  const b = board();
  await page.goto(`/p/${b.slug}`);
  const s = section(page);
  await expect(s).toBeVisible();
  // In the page's one Claude card after its text (the brown card all of Claude's work is in,
  // so not the owner's): its lead is the card's Summary, the write-up a fold, In detail,
  // folded to start with
  await expect(s).toHaveClass(/\bclaude\b/);
  await expect(s.getByRole("heading", { name: "About this page" })).toBeVisible();
  await expect(page.locator(".page section.claude")).toHaveCount(1); // one card, not two
  const fold = s.locator("details.writeup");
  await expect(fold.locator("> summary")).toHaveText("In detail");
  await expect(fold).not.toHaveAttribute("open", "");
  const card = s.locator(".card");
  await expect(card).toBeHidden();
  await fold.locator("> summary").click();
  await expect(card).toBeVisible();
  // "Claude · 27 Oct, 6:59 AM · v2", the model as its tooltip
  await expect(s.locator(".by").first()).toHaveText(/^Claude\s·\s.+\s·\sv2$/);
  await expect(s.locator(".by").first()).toHaveAttribute("title", "claude-opus-5-5");
  await expect(s.getByText("The pipeline again, retries first.")).toBeVisible();
  await expect(s.getByRole("heading", { name: "Open questions" })).toBeVisible();
  // Its [[n]] citation is a link to the page, made by the server
  const link = s.getByRole("link", { name: "the retry policy" });
  await expect(link).toHaveAttribute("href", `/p/${b.target}`);
  expect(await page.locator(".page > .body").textContent()).not.toContain("retry policy");
  // Related lists the page it links to, both ways
  await expect(
    page.locator(".enrich .related li", { hasText: "Retry policy" }).getByText("in a write-up"),
  ).toBeVisible();
  // Claude is off on this server: nothing to regenerate
  await expect(s.getByRole("button", { name: "Regenerate" })).toHaveCount(0);
  await page.screenshot({ path: "test-results/writeup.png", fullPage: true });

  // Guidance: kept apart from the text, for the next write-up
  await s.getByText("Guidance for Claude").click();
  const box = s.getByRole("textbox", { name: "Guidance for Claude" });
  await box.fill("Focus on the data flow; 'Enc' means encoder");
  await s.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Saved: the next write-up follows it")).toBeVisible();
  await expect(s.getByText("Guidance for Claude (set)")).toBeVisible();
  const saved = await (await page.request.get(`/api/pages/${b.slug}`)).json();
  expect(saved.writeup.guidance).toBe("Focus on the data flow; 'Enc' means encoder");
  expect(saved.body).not.toContain("Enc");

  // Versions: the older one made current again, as a copy
  await s.getByText("Versions").click();
  const rows = s.locator(".versions li");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("current");
  await rows.nth(1).getByRole("button", { name: "Restore" }).click();
  await expect(page.getByText("Version 1 restored")).toBeVisible();
  await expect(s.locator(".by").first()).toHaveText(/\sv3\s·\srestored\sfrom\sv1$/);
  await expect(s.getByText("A capture pipeline from phone to model")).toBeVisible();

  // Opened, it stays open when the page is opened again; folded again, it stays folded
  await page.reload();
  await expect(section(page).locator(".card")).toBeVisible();
  await section(page).locator("details.writeup > summary").click();
  await expect(section(page).locator(".card")).toBeHidden();
  await page.reload();
  await expect(section(page).locator(".card")).toBeHidden();
});

test("the write-up meets AA contrast, in both themes", async ({ page }) => {
  await opened(page);
  const b = board();
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    await page.goto(`/p/${b.slug}`);
    await expect(section(page).getByRole("link", { name: "the retry policy" })).toBeVisible();
    await section(page).getByText("Versions").click();
    await expect(section(page).locator(".versions li")).toHaveCount(2);
    // The section's own text (the page's other parts are checked by their own specs)
    const theirs = ".page > :not(section), .page > section:not([aria-label])";
    expect(await page.evaluate(lowContrast, theirs), colorScheme).toEqual([]);
    await page.screenshot({ path: `test-results/writeup-${colorScheme}.png`, fullPage: true });
  }
});

test("the card's one Regenerate asks Claude to read the board again, write-up and all", async ({
  page,
}) => {
  await opened(page);
  const b = board();
  // As if Claude were on (this server runs without it), the page read once already
  type Json = { enrich: object | null; writeup: object };
  const on = (json: Json, state = "done") => ({
    ...json,
    enrich: { error: null, summary: null, ...json.enrich, on: true, state },
    writeup: { ...json.writeup, on: true },
  });
  await page.route(`**/api/pages/${b.slug}`, async (r) =>
    r.fulfill({ json: on(await (await r.fetch()).json()) }),
  );
  const asked: string[] = [];
  await page.route("**/api/pages/*/enrich", async (r) => {
    asked.push("enrich");
    const json = await (await page.request.get(`/api/pages/${b.slug}`)).json();
    await r.fulfill({ json: on(json, "queued") });
  });
  await page.route("**/api/pages/*/writeup", async (r) => {
    asked.push("writeup");
    await r.abort();
  });
  await page.goto(`/p/${b.slug}`);
  const s = section(page);
  await expect(s.getByRole("button", { name: "Regenerate" })).toHaveCount(1); // one, not two
  await s.getByRole("button", { name: "Regenerate" }).click();
  await expect(s.getByRole("status")).toHaveText("Waiting for Claude");
  await expect(s.getByRole("button", { name: "Regenerate" })).toHaveCount(0);
  expect(asked).toEqual(["enrich"]); // Ask: reads it, writes it up, finds related pages
});

test("a board's Summary is its write-up's lead, not the page's own summary", async ({ page }) => {
  const b = board();
  let lead = "";
  await page.route(`**/api/pages/${b.slug}`, async (r) => {
    const json = await (await r.fetch()).json();
    lead = json.writeup.current.summary;
    await r.fulfill({
      json: { ...json, enrich: { on: false, state: "done", error: null, summary: "Not this one" } },
    });
  });
  await page.goto(`/p/${b.slug}`);
  const summary = section(page).locator("details", { hasText: "Summary" }).first();
  await expect(summary).toHaveAttribute("open", "");
  await expect(summary.locator(".summary")).toHaveText(lead);
  await expect(section(page).getByText("Not this one")).toHaveCount(0);
});

test("a board not written up yet says what Claude would do; Generate asks", async ({ page }) => {
  const b = board();
  await page.route(`**/api/pages/${b.slug}`, async (r) => {
    const json = await (await r.fetch()).json();
    await r.fulfill({
      json: {
        ...json,
        enrich: { on: true, state: null, error: null, summary: null },
        writeup: { ...json.writeup, on: true, state: null, versions: 0, current: null },
      },
    });
  });
  await page.goto(`/p/${b.slug}`);
  const s = section(page);
  await expect(s).toContainText("Claude can describe this board in detail");
  await expect(s).not.toContainText("Claude can summarise it");
  await expect(s.getByRole("button", { name: "Generate" })).toBeVisible();
  await expect(s.getByText("Guidance for Claude")).toBeVisible();
  await expect(s.locator("details.writeup .card")).toHaveCount(0); // no write-up to read
});

test("a write-up shows no link but a page link, whatever its text holds", async ({ page }) => {
  await opened(page);
  const b = board();
  // As if the stored text had a web address and a page it doesn't link in it (the server
  // strips them: this is the PWA's own guard against linkify)
  let linked = "";
  await page.route(`**/api/pages/${b.slug}`, async (r) => {
    const json = await (await r.fetch()).json();
    linked = json.writeup.current.links[0]; // a page it does link
    json.writeup.current.text = `See https://evil.example/x, [[${linked}|that page]] and [[e2e-not-there|gone]].`;
    await r.fulfill({ json });
  });
  await page.goto(`/p/${b.slug}`);
  const s = section(page);
  await expect(s.getByText("evil.example/x")).toBeVisible();
  await expect(s.getByText("gone")).toBeVisible(); // a page it doesn't link: words only
  await expect(s.locator(".body a")).toHaveCount(1);
  await expect(s.getByRole("link", { name: "that page" })).toHaveAttribute("href", `/p/${linked}`);
});

test("a page with no board has no write-up in its card", async ({ page }) => {
  const r = await page.request.post("/api/captures", {
    data: { id: ulid(), text: "A plain note" },
  });
  await page.goto(`/p/${(await r.json()).slug}`);
  await expect(page.locator("h1")).toHaveText("A plain note");
  await expect(page.locator("details.writeup")).toHaveCount(0);
});

test("an edit since the write-up says so quietly, and nothing regenerates", async ({ page }) => {
  const b = board();
  await page.goto(`/p/${b.slug}`);
  const s = section(page);
  await expect(s).toBeVisible();
  await expect(s.locator(".stale")).toHaveCount(0); // up to date
  const p = await (await page.request.get(`/api/pages/${b.slug}`)).json();
  const r = await page.request.patch(`/api/pages/${b.slug}`, {
    data: { base_rev: p.rev, body: `${p.body}\n\nA note added later.` },
  });
  expect(r.ok()).toBe(true);
  await page.reload();
  const line = s.locator("p.stale");
  await expect(line).toHaveText(
    "The page, a page it links to, or Claude's prompt has changed since this write-up.",
  );
  await expect(s.locator(".by").first()).toHaveText(/\sv2$/); // not made again
  expect((await (await page.request.get(`/api/pages/${b.slug}`)).json()).writeup.versions).toBe(2);
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    expect(await page.evaluate(lowContrast, ""), colorScheme).toEqual([]);
  }
});

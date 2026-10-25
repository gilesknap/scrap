// Claude's write-up of a board page (#256): its own folded section under the text, plainly
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
const section = (page: Page) => page.getByRole("region", { name: "Claude's write-up" });

test("a board's write-up shows apart from its text, with guidance and versions", async ({
  page,
}) => {
  const b = board();
  await page.goto(`/p/${b.slug}`);
  const s = section(page);
  await expect(s).toBeVisible();
  // Its own fold, open to start with, after the page's text; Claude's, not the owner's
  const fold = s.locator("details.writeup");
  await expect(fold).toHaveAttribute("open", "");
  const card = s.locator(".card");
  expect(await card.evaluate((el) => getComputedStyle(el).borderTopStyle)).toBe("dashed");
  await expect(s.locator(".by").first()).toContainText("claude-opus-5-5");
  await expect(s.locator(".by").first()).toContainText("version 2");
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
  await expect(s.locator(".by").first()).toContainText("version 3 · restored from version 1");
  await expect(s.getByText("A capture pipeline from phone to model")).toBeVisible();

  // Folded, it stays folded when the page is opened again
  await fold.locator("> summary").click();
  await expect(card).toBeHidden();
  await page.reload();
  await expect(section(page).locator(".card")).toBeHidden();
  await section(page).locator("details.writeup > summary").click();
  await expect(section(page).locator(".card")).toBeVisible();
});

test("the write-up meets AA contrast, in both themes", async ({ page }) => {
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

test("Regenerate queues a new write-up and the section says it waits", async ({ page }) => {
  const b = board();
  // As if Claude were on (this server runs without it)
  const on = (json: { writeup: { on: boolean } }) => ({
    ...json,
    writeup: { ...json.writeup, on: true },
  });
  await page.route(`**/api/pages/${b.slug}`, async (r) =>
    r.fulfill({ json: on(await (await r.fetch()).json()) }),
  );
  let asked = 0;
  await page.route("**/api/pages/*/writeup", async (r) => {
    asked++;
    const json = await (await page.request.get(`/api/pages/${b.slug}`)).json();
    await r.fulfill({ json: { ...on(json), writeup: { ...on(json).writeup, state: "queued" } } });
  });
  await page.goto(`/p/${b.slug}`);
  const s = section(page);
  await s.getByRole("button", { name: "Regenerate" }).click();
  await expect(s.getByRole("status")).toHaveText("Waiting for Claude");
  await expect(s.getByRole("button", { name: "Regenerate" })).toHaveCount(0);
  expect(asked).toBe(1);
});

test("a write-up shows no link but a page link, whatever its text holds", async ({ page }) => {
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

test("a page with no board has no write-up section", async ({ page }) => {
  const r = await page.request.post("/api/captures", {
    data: { id: ulid(), text: "A plain note" },
  });
  await page.goto(`/p/${(await r.json()).slug}`);
  await expect(page.locator("h1")).toHaveText("A plain note");
  await expect(section(page)).toHaveCount(0);
});

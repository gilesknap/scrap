// Claude's reading (#521): one closed fold under each photo or file, the same line as scrap's
// other folds (the chevron before the words, a 48 px target), Regenerate inside it, never
// remembered open; and an image Claude drew (add_svg) with nothing under it, its label its alt.
import { execFileSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";
import { deletedAfterEach } from "./helpers";

const made = deletedAfterEach();

/** Run one of e2e's Python fixtures on the server's data folder: its last line, as JSON. */
function fixture<T>(script: string): T {
  const data = process.env.SCRAP_E2E_DATA as string;
  const args = ["run", "--locked", "python", `web/e2e/${script}`, data];
  const out = execFileSync("uv", args, { cwd: "..", encoding: "utf8" });
  return JSON.parse(out.trim().split("\n").pop() || "null") as T;
}

async function track(page: Page, slug: string) {
  made.push((await (await page.request.get(`/api/pages/${slug}`)).json()).id);
}

test("a photo's reading is one closed fold, opened in place and closed again next time", async ({
  page,
}) => {
  const b = fixture<{ slug: string }>("draw.py");
  await track(page, b.slug);
  await page.goto(`/p/${b.slug}`);
  const fold = page.locator(".photo-panel details.reading-fold");
  const line = fold.locator("> summary");
  await expect(line).toHaveText("Claude's reading");
  await expect(fold).not.toHaveAttribute("open", "");
  const box = await line.boundingBox();
  expect(box?.height).toBeGreaterThanOrEqual(48);
  // the chevron before the words, as scrap's other folds have it
  const before = await line.evaluate((el) => getComputedStyle(el, "::before").content);
  expect(before).toBe('""');
  await line.focus();
  await page.keyboard.press("Enter");
  await expect(fold).toHaveAttribute("open", "");
  await expect(fold.getByText("retry with backoff", { exact: false })).toBeVisible();
  const regen = fold.getByRole("button", { name: "Regenerate" });
  await expect(regen).toBeVisible();
  expect(await regen.evaluate((el) => el.classList.contains("link"))).toBe(true);
  await page.reload();
  await expect(page.locator(".photo-panel details.reading-fold")).not.toHaveAttribute("open", "");
});

test("an image Claude drew has nothing under it, even one read before, and its label is its alt", async ({
  page,
}) => {
  const m = fixture<{ slug: string; sha256: string; old: string }>("claudesvg.py");
  await track(page, m.slug);
  await page.goto(`/p/${m.slug}`);
  const figs = page.locator(".md figure.orig");
  await expect(figs).toHaveCount(2);
  await expect(figs.nth(0).locator("img")).toHaveAttribute(
    "alt",
    "Right triangle ABC, AB 5 cm, BC 12 cm",
  );
  await expect(figs.nth(1).locator("img")).toHaveAttribute("alt", "Isosceles triangle PQR");
  // no panel, fold, note or Generate: the figure alone, its old reading not shown
  await expect(page.locator(".photo-panel, .reading, .reading-state")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Generate", includeHidden: true })).toHaveCount(0);
  await expect(page.locator("main")).not.toContainText("OLD READING");
  // nothing queued for it, and search finds it by its label
  const p = await (await page.request.get(`/api/pages/${m.slug}`)).json();
  const first = p.captures.flatMap((c: { blobs: { sha256: string; ingest: unknown }[] }) =>
    c.blobs.filter((x) => x.sha256 === m.sha256),
  );
  expect(first.map((x: { ingest: unknown }) => x.ingest)).toEqual([null]);
  const hits = (await (await page.request.get("/api/search?q=triangle+ABC+12+cm")).json()) as {
    id: string;
  }[];
  expect(hits.map((h) => h.id)).toContain(p.id);
});

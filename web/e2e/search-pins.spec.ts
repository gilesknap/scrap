// Search phase 2 (#314): pins (one ordinary page of links), New from a filtered search, and the
// results header (count, Pin, Copy link) in the order the mock has it.
import { expect, type Page, test } from "@playwright/test";
import { deletePages, ulid } from "./helpers";

const mark = ulid().slice(-8).toLowerCase();
const tag = `pin${mark}`;
const mine: string[] = [];

/** The Pinned page's text, or "" before the first pin. */
async function pinned(page: Page): Promise<string> {
  const r = await page.request.get("/api/pages/pinned");
  return r.ok() ? ((await r.json()) as { body: string }).body : "";
}

/** Put the Pinned page back as it was (empty), so other specs see no launcher. */
async function reset(page: Pick<Page, "request">) {
  const r = await page.request.get("/api/pages/pinned");
  if (!r.ok()) return;
  const p = (await r.json()) as { id: string; rev: number };
  await page.request.patch(`/api/pages/${p.id}`, { data: { body: "", base_rev: p.rev } });
}

test.beforeAll(async ({ request }) => {
  for (const text of [`Alpha ${mark}`, `Beta ${mark}`]) {
    const r = await request.post("/api/captures", { data: { id: ulid(), text, kind: "note" } });
    const made = (await r.json()) as { page_id: string };
    mine.push(made.page_id);
    await request.patch(`/api/pages/${made.page_id}`, { data: { tags: [tag] } });
  }
});

test.afterAll(async ({ request }) => {
  await deletePages(request, mine);
  // The Pinned page too (to the trash: other specs count the pages in the store), emptied
  // first: the next first pin brings it back from the trash with the links it had
  await reset({ request } as Page);
  const r = await request.get("/api/pages/pinned");
  if (r.ok()) await request.delete(`/api/pages/${((await r.json()) as { id: string }).id}`);
});

const search = (page: Page, q: string) => page.goto(`/search?q=${encodeURIComponent(q)}`);

test("the results header: count at the start, 48 px Pin and Copy link, no kebab", async ({
  page,
}) => {
  await search(page, `tag:${tag}`);
  const head = page.locator(".rhead");
  await expect(head.locator(".count")).toContainText("2");
  for (const name of ["Pin search", "Copy link"]) {
    const box = await head.getByRole("button", { name }).boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual(47.5);
    expect(box?.height).toBeGreaterThanOrEqual(47.5);
  }
  await expect(head.getByRole("button", { name: /more/i })).toHaveCount(0);
  // box, kinds, chips, header, results: in that order down the screen
  const top = async (sel: string) => (await page.locator(sel).first().boundingBox())?.y ?? -1;
  const ys = [await top(".field-search"), await top(".fon"), await top(".rhead")];
  expect(ys[0]).toBeLessThan(ys[1]);
  expect(ys[1]).toBeLessThan(ys[2]);
});

test("pinning a search makes the Pinned page, shows it in the launcher, and Undo takes it back", async ({
  page,
}) => {
  await reset(page);
  await search(page, `tag:${tag}`);
  await page.getByRole("button", { name: "Pin search" }).click();
  await expect(page.locator(".toast")).toContainText("Pinned");
  await expect(page.getByRole("button", { name: "Unpin search" })).toBeVisible();
  expect(await pinned(page)).toContain(`/search?q=tag:${tag}`);

  await page.locator(".toast button", { hasText: "Undo" }).click();
  await expect(page.getByRole("button", { name: "Pin search" })).toBeVisible();
  await expect.poll(() => pinned(page)).not.toContain(tag);

  await page.getByRole("button", { name: "Pin search" }).click();
  await expect.poll(() => pinned(page)).toContain(tag);
  await page.goto("/search");
  await page.locator('input[type="search"], .field-search input').first().focus();
  const launcher = page.getByRole("group", { name: "Pinned" });
  await expect(launcher).toBeVisible();
  await expect(launcher.getByRole("link")).toHaveCount(1);
});

test("a page is pinned from its Share menu and the pin survives a rename", async ({ page }) => {
  await reset(page);
  const id = mine[0];
  const slug = ((await (await page.request.get(`/api/pages/${id}`)).json()) as { slug: string })
    .slug;
  await page.request.patch(`/api/pages/${id}`, { data: { title: `Renamed ${mark}` } });
  // (a browser with no Share menu has no Pin to Search there: the pin is made from Search)
  await page.addInitScript(() => {
    navigator.share = async () => {};
  });
  await page.goto(`/p/${slug}`);
  await page.getByRole("button", { name: "Share" }).first().click();
  await page.getByRole("button", { name: "Pin to Search" }).click();
  await expect.poll(() => pinned(page)).toContain(`(/p/${slug})`);
  await page.request.patch(`/api/pages/${id}`, { data: { title: `Again ${mark}` } });
  expect(await pinned(page)).toContain(`(/p/${slug})`);
});

test("New from a tag search opens the composer with the tag; Cancel keeps no draft", async ({
  page,
}) => {
  await search(page, `tag:${tag}`);
  const add = page.locator("#new");
  await expect(add).toBeVisible();
  await add.click();
  const ed = page.locator(".editor");
  await expect(ed.getByText(`#${tag}`).first()).toBeVisible();
  await ed.getByRole("button", { name: "Cancel" }).click();
  await expect(ed).toHaveCount(0);
  await expect(page.locator(".toast")).toHaveCount(0); // nothing was kept
});

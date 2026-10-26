// Back on a page opened cold, while the page itself is still loading (patchy WiFi: its
// /api/pages request held open): Back can't learn the kind, so after a short wait it goes up to
// Capture rather than looking dead, and the late answer doesn't move it again (#141). With the
// page drawn, Back needs no request at all.
import { expect, type Page, type Route, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

async function make(page: Page, text: string, kind = "note") {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text, kind } });
  return (await r.json()) as { page_id: string; slug: string };
}

const back = (page: Page) => page.locator("header #back");

test("Back on a cold page whose request stalls goes to Capture, quickly", async ({ page }) => {
  const p = await make(page, `Cold stall ${ulid().slice(-6)}`, "todo");
  const held: Route[] = [];
  await page.route(`**/api/pages/${p.slug}`, (r) => {
    held.push(r); // never answered until the end: a stalled link
  });
  await page.goto(`/p/${p.slug}`);
  await expect(back(page)).toBeVisible();
  await expect(page.locator("#view")).toContainText("Loading…");
  await expect(back(page)).toHaveAccessibleName("Back to Capture"); // its kind not known yet
  const t0 = Date.now();
  await back(page).click();
  await expect(page).toHaveURL("/", { timeout: 4_000 });
  expect(Date.now() - t0).toBeLessThan(3_000);
  // The late answer (a todo's: Todos) doesn't move Back on
  await page.unroute(`**/api/pages/${p.slug}`);
  for (const r of held) await r.continue().catch(() => {});
  await page.waitForTimeout(500);
  await expect(page).toHaveURL("/");
});

test("Back on a cold page that is drawn needs no request", async ({ page }) => {
  const p = await make(page, `Cold drawn ${ulid().slice(-6)}`, "todo");
  await page.goto(`/p/${p.slug}`);
  await expect(page.locator(".page h1")).toHaveText(/Cold drawn/);
  await expect(back(page)).toHaveAccessibleName("Back to Todos");
  let asked = 0;
  await page.route(`**/api/pages/${p.slug}`, (r) => {
    asked++;
    return r.abort();
  });
  await back(page).click();
  await expect(page).toHaveURL("/todos");
  expect(asked).toBe(0);
});

test("Back works with its chunk's request stalled: the service worker keeps it", async ({
  page,
  context,
}) => {
  const p = await make(page, `Cold chunk ${ulid().slice(-6)}`, "todo");
  await page.goto("/");
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload(); // now the service worker's
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true);
  // Both held at the network: Back's chunk (only the service worker's cache has it) and the page
  await context.route("**/assets/back-*.js", () => {});
  await context.route(`**/api/pages/${p.slug}`, () => {});
  await page.goto(`/p/${p.slug}`);
  await expect(back(page)).toHaveAccessibleName("Back to Capture");
  await back(page).click();
  await expect(page).toHaveURL("/", { timeout: 4_000 });
});

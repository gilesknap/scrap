// Back on a page opened cold goes where its label says, with no request of its own (#141): the
// drawn page's parent (Todos for a todo), and Capture while the page is still loading (patchy
// WiFi: its /api/pages request held open), so on a stalled link it is never a dead button. Its
// chunk is the service worker's, so a stalled link cannot hold that either.
import { expect, type Page, test } from "@playwright/test";
import { capture, ulid } from "./helpers";

const make = (page: Page, text: string, kind = "note") => capture(page, text, { kind });

const back = (page: Page) => page.locator("header #back");

test("a cold page still loading: Back is Capture, and goes there at once", async ({ page }) => {
  const p = await make(page, `Cold stall ${ulid().slice(-6)}`, "todo");
  let asked = 0;
  await page.route(`**/api/pages/${p.slug}`, () => {
    asked++; // never answered: a stalled link
  });
  await page.goto(`/p/${p.slug}`);
  await expect(page.locator("#view")).toContainText("Loading…");
  await expect(back(page)).toHaveAccessibleName("Back to Capture"); // its kind not known yet
  const before = asked; // the view's own
  const t0 = Date.now();
  await back(page).click();
  await expect(page).toHaveURL("/");
  expect(Date.now() - t0).toBeLessThan(1_000);
  expect(asked).toBe(before); // none from Back
});

test("a cold todo drawn: Back is Todos, and goes there with no request", async ({ page }) => {
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

test("a cold page drawn after it opened: Back's label and destination agree", async ({ page }) => {
  const p = await make(page, `Cold late ${ulid().slice(-6)}`, "todo");
  let release = () => {};
  const held = new Promise<void>((done) => {
    release = done;
  });
  await page.route(`**/api/pages/${p.slug}`, async (r) => {
    await held;
    await r.continue();
  });
  await page.goto(`/p/${p.slug}`);
  await expect(back(page)).toHaveAccessibleName("Back to Capture");
  release(); // the page is drawn now: a todo
  await expect(page.locator(".page h1")).toHaveText(/Cold late/);
  await expect(back(page)).toHaveAccessibleName("Back to Todos");
  await back(page).click();
  await expect(page).toHaveURL("/todos");
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

// Swipes: list rows (right edits, left deletes with Undo) and a page stepping through the list
// it was opened from (pager, swipe, arrow keys). Touches are sent through the DevTools
// protocol, as a finger would make them.
import { type CDPSession, expect, type Locator, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

async function note(page: Page, text: string) {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text } });
  return (await r.json()).slug as string;
}

/** Three new pages, newest first in Recent: [c, b, a]. */
async function three(page: Page) {
  const tag = ulid().slice(-6);
  const a = await note(page, `Swipe A ${tag}`);
  const b = await note(page, `Swipe B ${tag}`);
  const c = await note(page, `Swipe C ${tag}`);
  return [c, b, a];
}

type Pt = { x: number; y: number; id?: number };
type Touch = "touchStart" | "touchMove" | "touchEnd";
const fingers = async (cdp: CDPSession, type: Touch, points: Pt[]) =>
  cdp.send("Input.dispatchTouchEvent", { type, touchPoints: points });

/** A one-finger drag from x0 to x1 at height y, in `steps` moves `ms` apart. */
async function drag(cdp: CDPSession, y: number, x0: number, x1: number, steps = 8, ms = 16) {
  await fingers(cdp, "touchStart", [{ x: x0, y }]);
  for (let i = 1; i <= steps; i++) {
    await fingers(cdp, "touchMove", [{ x: x0 + ((x1 - x0) * i) / steps, y }]);
    await new Promise((ok) => setTimeout(ok, ms));
  }
  await fingers(cdp, "touchEnd", []);
}

/** Where to touch a row: its middle, once it is laid out (after Back the list is drawn anew). */
async function rowY(row: Locator) {
  let y = 0;
  await expect
    .poll(async () => {
      const b = await row.boundingBox();
      y = b ? b.y + b.height / 2 : 0;
      return y;
    })
    .toBeGreaterThan(0);
  return y;
}

const rowOf = (page: Page, slug: string) =>
  page.locator(".list li.swipe").filter({ has: page.locator(`a[href="/p/${slug}"]`) });

test("a row swiped left is deleted, and Undo brings it back", async ({ page }) => {
  const [c] = await three(page);
  const cdp = await page.context().newCDPSession(page);
  await page.goto("/recent");
  const row = rowOf(page, c);
  await drag(cdp, await rowY(row), 340, 100);
  await expect(page.getByText("Page deleted")).toBeVisible();
  await expect(row).toHaveCount(0);
  expect((await page.request.get(`/api/pages/${c}`)).status()).toBe(404);
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(rowOf(page, c)).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/recent");
});

test("a row swiped right opens its page in the editor; a short drag does nothing", async ({
  page,
}) => {
  const [c] = await three(page);
  const cdp = await page.context().newCDPSession(page);
  await page.goto("/recent");
  const row = rowOf(page, c);
  await drag(cdp, await rowY(row), 100, 140, 4, 120); // short and slow: settles back
  await expect(row.locator("a")).not.toHaveAttribute("style", /translate/);
  await expect(row).toHaveClass("swipe");
  // Enter on the row still opens it, though the touch moved it
  await row.locator("a").focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(`/p/${c}`);
  await page.goBack();

  await drag(cdp, await rowY(rowOf(page, c)), 100, 340);
  await expect(page.locator(".editor")).toBeVisible();
  await expect(page).toHaveURL(`/p/${c}`);
  await page.goBack(); // closes the editor
  await expect(page.locator(".editor")).toBeHidden();
  await expect(page.locator(".pager")).toContainText("1 of");
  await page.goBack();
  await expect(page).toHaveURL("/recent");
});

test("a second finger never leaves a row half swiped", async ({ page }) => {
  const [c] = await three(page);
  const cdp = await page.context().newCDPSession(page);
  await page.goto("/recent");
  const row = rowOf(page, c);
  const y = await rowY(row);
  await fingers(cdp, "touchStart", [{ x: 300, y, id: 0 }]);
  await fingers(cdp, "touchMove", [{ x: 280, y, id: 0 }]);
  await fingers(cdp, "touchMove", [{ x: 250, y, id: 0 }]);
  await fingers(cdp, "touchStart", [
    { x: 250, y, id: 0 },
    { x: 200, y, id: 1 },
  ]); // a second finger lands on the row
  await fingers(cdp, "touchEnd", [{ x: 200, y, id: 1 }]); // the first lifts
  await fingers(cdp, "touchEnd", []);
  await expect(row.locator("a")).not.toHaveAttribute("style", /translateX\(-/);
  await expect(row).toHaveCount(1); // not deleted either
});

test("a page from Recent steps through it: pager, swipe and keys; Back is the list", async ({
  page,
}) => {
  const [c, b, a] = await three(page);
  const cdp = await page.context().newCDPSession(page);
  await page.goto("/recent");
  await rowOf(page, c).locator("a").click();
  await expect(page.locator(".pager")).toContainText("1 of");
  await expect(page.getByRole("button", { name: "Previous" })).toBeDisabled();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page).toHaveURL(`/p/${b}`);
  await drag(cdp, 500, 330, 100); // swipe left: the next one
  await expect(page).toHaveURL(`/p/${a}`);
  await page.keyboard.press("ArrowLeft");
  await expect(page).toHaveURL(`/p/${b}`);
  await drag(cdp, 500, 400, 150); // from the screen's edge: the phone's, not ours
  await expect(page).toHaveURL(`/p/${b}`);
  await page.goBack();
  await expect(page).toHaveURL("/recent");
});

test("leaving a page while it loads leaves no swipes or keys behind", async ({ page }) => {
  const [c] = await three(page);
  await page.goto("/recent");
  await page.route(`**/api/pages/${c}`, async (r) => {
    await new Promise((ok) => setTimeout(ok, 1500));
    await r.continue();
  });
  await rowOf(page, c).locator("a").click();
  await page.waitForTimeout(200);
  await page.goBack();
  await expect(page).toHaveURL("/recent");
  await page.waitForTimeout(2000); // the page has loaded, too late
  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(300);
  await expect(page).toHaveURL("/recent");
});

test("a swipe's step never replaces where the nav went meanwhile", async ({ page }) => {
  const [c] = await three(page);
  const cdp = await page.context().newCDPSession(page);
  await page.goto("/recent");
  await rowOf(page, c).locator("a").click();
  await expect(page.locator(".pager")).toBeVisible();
  await drag(cdp, 500, 330, 100, 4, 8);
  await page.locator("nav a", { hasText: "Search" }).click(); // within the slide-off
  await page.waitForTimeout(500);
  await expect(page).toHaveURL(/\/search/);
  await page.goBack();
  await expect(page).toHaveURL(`/p/${c}`);
});

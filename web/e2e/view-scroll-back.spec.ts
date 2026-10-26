// Back and Forward come back to a screen scrolled where it was left: the Todos screen, and a
// page left by a link (the top bar's Back, and the phone's own).
import { expect, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

async function make(page: Page, text: string, kind = "note") {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text, kind } });
  return (await r.json()) as { page_id: string; slug: string };
}

const y = (page: Page) => page.evaluate(() => Math.round(scrollY));
/** Scrolled to `to`, and the debounced write into the entry done. */
async function scrollTo(page: Page, to: number) {
  await page.evaluate((to) => window.scrollTo(0, to), to);
  await expect.poll(() => page.evaluate(() => history.state?.y)).toBe(await y(page));
}

test("the Todos screen comes back where it was left", async ({ page }) => {
  const tag = ulid().slice(-6);
  for (let i = 0; i < 30; i++) await make(page, `Scroll todo ${tag} ${i}`, "todo");
  await page.goto("/todos?view=all");
  await expect(page.locator(".todos a", { hasText: `Scroll todo ${tag} 29` })).toBeVisible();
  await scrollTo(page, 900);
  const left = await y(page);
  expect(left).toBeGreaterThan(500);
  // A row in view: its page, then the top bar's Back
  const href = await page.evaluate(
    () =>
      [...document.querySelectorAll<HTMLAnchorElement>(".todos li a")]
        .find((a) => a.getBoundingClientRect().top > 120)
        ?.getAttribute("href") as string,
  );
  await page.locator(`.todos a[href="${href}"]`).first().click();
  await expect(page.locator(".page h1")).toBeVisible();
  expect(await y(page)).toBe(0); // a page opens at its top
  await page.locator("#back").click();
  await expect(page).toHaveURL(/\/todos/);
  await expect.poll(() => y(page)).toBe(left);
  // and by the phone's own Back
  await page.goForward();
  await expect(page.locator(".page h1")).toBeVisible();
  await page.goBack();
  await expect.poll(() => y(page)).toBe(left);
});

test("a page left by a link comes back where it was", async ({ page }) => {
  const tag = ulid().slice(-6);
  const b = await make(page, `Scroll B ${tag}`);
  const filler = Array.from({ length: 40 }, (_, i) => `Paragraph ${i} of the long page.`).join(
    "\n\n",
  );
  const a = await make(page, `Scroll A ${tag}\n\n${filler}\n\nSee [[${b.slug}|the B page]].`);
  await page.goto(`/p/${a.slug}`);
  const link = page.locator(".page .body a", { hasText: "the B page" });
  await link.scrollIntoViewIfNeeded();
  await scrollTo(page, await y(page));
  const left = await y(page);
  expect(left).toBeGreaterThan(500);
  await link.click();
  await expect(page.locator(".page h1")).toHaveText(`Scroll B ${tag}`);
  await page.locator("#back").click(); // ‹ Scroll A
  await expect(page.locator(".page h1")).toHaveText(`Scroll A ${tag}`);
  await expect.poll(() => y(page)).toBe(left);
  // Forward to B and the phone's Back: the same
  await page.goForward();
  await expect(page.locator(".page h1")).toHaveText(`Scroll B ${tag}`);
  await page.goBack();
  await expect(page.locator(".page h1")).toHaveText(`Scroll A ${tag}`);
  await expect.poll(() => y(page)).toBe(left);
});

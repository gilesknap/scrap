// On a computer, Search is scrap's home: "/" shows it, and Back on a page opened cold says
// Search and goes there (a todo's still Todos), as Delete does; Capture is one click away, on
// its nav tab (/capture), where a share lands too. A phone keeps Capture as home.
import { expect, type Page, test } from "@playwright/test";
import { capture, deletedAfterEach, ulid } from "./helpers";

const made = deletedAfterEach();
const make = async (page: Page, text: string, kind = "note") => {
  const p = await capture(page, `${text} ${ulid().slice(-6)}`, { kind });
  made.push(p.page_id);
  return p;
};
const back = (page: Page) => page.locator("header #back");
const tab = (page: Page, name: string) => page.locator("nav a", { hasText: name });

test.describe("on a computer", () => {
  test.use({ viewport: { width: 1280, height: 800 }, isMobile: false, hasTouch: false });

  test("home is Search; Capture is its tab, at /capture", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL("/search");
    await expect(page.locator(".search")).toBeVisible();
    await expect(page.locator("nav a[aria-current]")).toHaveText("Search");
    await expect(tab(page, "Capture")).toHaveAttribute("href", "/capture");
    await tab(page, "Capture").click();
    await expect(page).toHaveURL("/capture");
    await expect(page.locator(".capture .actions")).toBeVisible();
    await expect(page.locator("nav a[aria-current]")).toHaveText("Capture");
    // The wordmark goes home: Search
    await page.locator("header .logo").click();
    await expect(page).toHaveURL("/search");
    // Opened at its own address too, and after a reload
    await page.goto("/capture");
    await expect(page.locator(".capture .actions")).toBeVisible();
  });

  test("a cold page's Back says Search and goes there; a todo's says Todos", async ({ page }) => {
    const n = await make(page, "Desk cold");
    await page.goto(`/p/${n.slug}`);
    await expect(page.locator(".page h1")).toHaveText(/Desk cold/);
    await expect(back(page)).toHaveAccessibleName("Back to Search");
    await expect(page.locator("#backto")).toHaveText("Search");
    await back(page).click();
    await expect(page).toHaveURL("/search");
    await expect(page.locator(".search")).toBeVisible();

    const t = await make(page, "Desk todo", "todo");
    await page.goto(`/p/${t.slug}`);
    await expect(page.locator(".page h1")).toHaveText(/Desk todo/);
    await expect(back(page)).toHaveAccessibleName("Back to Todos");
  });

  test("a cold page still loading: Back is Search", async ({ page }) => {
    const n = await make(page, "Desk stall");
    await page.route(`**/api/pages/${n.slug}`, () => {}); // never answered
    await page.goto(`/p/${n.slug}`);
    await expect(back(page)).toHaveAccessibleName("Back to Search");
    await back(page).click();
    await expect(page).toHaveURL("/search");
  });

  test("Delete on a cold page goes to Search", async ({ page }) => {
    const n = await make(page, "Desk delete");
    await page.goto(`/p/${n.slug}`);
    await page.locator(".page > .tools").getByRole("button", { name: "Delete" }).click();
    await expect(page).toHaveURL("/search");
  });

  test("a missing page offers Back to search", async ({ page }) => {
    await page.goto(`/p/no-such-page-${ulid().slice(-6).toLowerCase()}`);
    const home = page.getByRole("link", { name: "Back to search" });
    await expect(home).toBeVisible();
    await home.click();
    await expect(page).toHaveURL("/search");
  });

  test("a share lands on Capture, at its own address", async ({ page }) => {
    await page.goto("/?shared=1");
    await expect(page).toHaveURL("/capture");
    await expect(page.locator(".capture .actions")).toBeVisible();
    await expect(page.locator(".toast")).toHaveText("Shared item saved");
    await expect(page.locator("nav a[aria-current]")).toHaveText("Capture");
  });
});

test.describe("on a phone (no change)", () => {
  test("home is Capture at /, and a cold page's Back says Capture", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL("/");
    await expect(page.locator(".capture .actions")).toBeVisible();
    await expect(page.locator("nav a[aria-current]")).toHaveText("Capture");
    await expect(tab(page, "Capture")).toHaveAttribute("href", "/");
    const n = await make(page, "Phone cold");
    await page.goto(`/p/${n.slug}`);
    await expect(page.locator(".page h1")).toHaveText(/Phone cold/);
    await expect(back(page)).toHaveAccessibleName("Back to Capture");
    await back(page).click();
    await expect(page).toHaveURL("/");
    await expect(page.locator(".capture .actions")).toBeVisible();
    await page.goto(`/p/no-such-page-${ulid().slice(-6).toLowerCase()}`);
    await expect(page.getByRole("link", { name: "Back to capture" })).toBeVisible();
  });
});

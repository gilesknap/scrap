// A computer window (a mouse, a fine pointer, 1024x1280 like the owner's workstation): the
// centred column (css/todos.css's --column) defaults to 800 px and is Settings' Maximum column
// width (column.ts, settings.ts), which a narrower window still shrinks to fit, with the usual
// gutter, never scrolling sideways. (The photo/drawing pair always using tabs, not the old
// side-by-side split, is e2e/whiteboard.spec.ts's, which already makes a board; this file never
// writes a page, so it can run anywhere in the suite, unlike smoke.spec.ts's empty-store start.)
import { expect, type Page, test } from "@playwright/test";

const COLUMN = "scrap.column";

/** A vertical scrollbar would shrink the column's containing block by its own width, which
 * has nothing to do with --column: measuring is simpler with none. */
const noScroll = (page: Page) =>
  page.addStyleTag({ content: "html { overflow-y: hidden !important }" });

/** The column's effective width: main's content box, inside its left and right padding (not
 * what was asked for: a narrower window shrinks it). */
const columnPx = (page: Page) =>
  page.evaluate(() => {
    const m = document.querySelector("main") as HTMLElement;
    const s = getComputedStyle(m);
    return m.getBoundingClientRect().width - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight);
  });
const gutterPx = (page: Page) =>
  page.evaluate(() => {
    const m = document.querySelector("main") as HTMLElement;
    return parseFloat(getComputedStyle(m).paddingLeft);
  });

/** Within a couple of px: rounding, not a wrong width. */
const near = (actual: number, expected: number) =>
  expect(Math.abs(actual - expected), `${actual} near ${expected}`).toBeLessThanOrEqual(2);

test.describe("on a computer (a mouse, a wide window)", () => {
  test.use({ viewport: { width: 1024, height: 1280 }, isMobile: false, hasTouch: false });

  test("the list screen's column is 800 px by default", async ({ page }) => {
    await page.goto("/todos");
    await noScroll(page);
    near(await columnPx(page), 800);
    await page.screenshot({ path: "test-results/list-column-800.png", fullPage: true });
  });

  test.describe("Maximum column width", () => {
    test.beforeEach(async ({ page }) => {
      await page.goto("/todos");
      await page.evaluate((k) => localStorage.removeItem(k), COLUMN);
      await page.reload();
      await noScroll(page);
    });
    test.afterEach(async ({ page }) => {
      await page.evaluate((k) => localStorage.removeItem(k), COLUMN);
    });

    const open = async (page: Page) => {
      await page.getByRole("button", { name: "Settings" }).click();
      return page.getByRole("radiogroup", { name: "Maximum column width" });
    };

    test("800 px is the default, offered alongside Narrow, Wide and Wider", async ({ page }) => {
      const group = await open(page);
      await expect(group.getByLabel("Medium (800px)")).toBeChecked();
      await page.screenshot({ path: "test-results/settings-column-width.png" });
    });

    test("a choice applies at once, survives reload, and 800 undoes it", async ({ page }) => {
      let group = await open(page);
      await group.getByText("Wider (960px)", { exact: true }).click();
      await expect.poll(() => columnPx(page)).toBeGreaterThan(900);
      near(await columnPx(page), 960);
      expect(await page.evaluate((k) => localStorage.getItem(k), COLUMN)).toBe("960");

      await page.reload(); // closes the sheet
      await noScroll(page);
      near(await columnPx(page), 960);
      group = await open(page); // reopen it
      await expect(group.getByLabel("Wider (960px)")).toBeChecked();

      await group.getByText("Medium (800px)", { exact: true }).click(); // still open: no reopen
      await expect.poll(() => columnPx(page)).toBeLessThan(900);
      near(await columnPx(page), 800);
      expect(await page.evaluate((k) => localStorage.getItem(k), COLUMN)).toBeNull();
    });

    test("the app applies a kept width even if theme-init.js didn't (a stale copy)", async ({
      page,
    }) => {
      await page.route("**/theme-init.js", (r) =>
        r.fulfill({ contentType: "text/javascript", body: "/* stale */" }),
      );
      await page.evaluate((k) => localStorage.setItem(k, "880"), COLUMN);
      await page.reload();
      await noScroll(page);
      await expect.poll(() => columnPx(page)).toBeGreaterThan(850);
      near(await columnPx(page), 880);
      await page.unroute("**/theme-init.js");
    });

    test("960 in a 1024 px window keeps the usual gutter either side", async ({ page }) => {
      await (await open(page)).getByText("Wider (960px)", { exact: true }).click();
      await page.setViewportSize({ width: 1024, height: 800 });
      await noScroll(page);
      await expect.poll(() => gutterPx(page)).toBeGreaterThanOrEqual(16);
      near(await columnPx(page), 960);
      await page.screenshot({ path: "test-results/column-960-at-1024.png" });
    });

    test("880 in a 900 px window shrinks to fit, with no horizontal scroll", async ({ page }) => {
      await (await open(page)).getByText("Wide (880px)", { exact: true }).click();
      await page.setViewportSize({ width: 900, height: 800 });
      await noScroll(page);
      // Asked for 880, but 900 only has room for 900 - 2*16 = 868 with the usual gutter
      await expect.poll(() => gutterPx(page)).toBeLessThan(20);
      near(await gutterPx(page), 16);
      near(await columnPx(page), 868);
      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(scrollWidth).toBeLessThanOrEqual(900);
      await page.screenshot({ path: "test-results/column-880-at-900-shrunk.png" });
    });
  });
});

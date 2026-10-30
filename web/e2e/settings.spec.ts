// Settings from the top bar's cog: the app theme (System, Light, Dark) and the drawings'
// theme (Light, Dark, Same as app), kept on this device and applied without a reload.
import { expect, type Page, test } from "@playwright/test";

const theme = (page: import("@playwright/test").Page) =>
  page.evaluate(() => document.documentElement.dataset.theme ?? "");
const bg = (page: import("@playwright/test").Page) =>
  page.evaluate(() => getComputedStyle(document.body).backgroundColor);

test("the cog opens Settings, which closes with Escape and Done", async ({ page }) => {
  await page.goto("/");
  const cog = page.getByRole("button", { name: "Settings" });
  await expect(cog).toBeVisible();
  const box = (await cog.boundingBox()) as { width: number; height: number };
  expect(box.width).toBeGreaterThanOrEqual(48);
  expect(box.height).toBeGreaterThanOrEqual(48);

  await cog.click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(cog).toBeFocused();

  await cog.click();
  await dialog.getByRole("button", { name: "Done" }).click();
  await expect(dialog).toHaveCount(0);
  await page.goto("/todos"); // on every screen
  await expect(page.getByRole("button", { name: "Settings" })).toBeVisible();
});

test("the app theme follows the OS until chosen, and is kept", async ({ browser }) => {
  const ctx = await browser.newContext({ colorScheme: "dark" });
  const page = await ctx.newPage();
  await page.goto("/");
  expect(await theme(page)).toBe("");
  const dark = await bg(page);

  await page.getByRole("button", { name: "Settings" }).click();
  const group = page.getByRole("radiogroup", { name: "App theme" });
  await expect(group.getByLabel("System")).toBeChecked();
  await group.getByText("Light", { exact: true }).click();
  expect(await theme(page)).toBe("light");
  expect(await bg(page)).not.toBe(dark);

  await page.reload();
  expect(await theme(page)).toBe("light"); // before the app has started
  await page.getByRole("button", { name: "Settings" }).click();
  await expect(
    page.getByRole("radiogroup", { name: "App theme" }).getByLabel("Light"),
  ).toBeChecked();

  await page
    .getByRole("radiogroup", { name: "App theme" })
    .getByText("System", { exact: true })
    .click();
  expect(await theme(page)).toBe("");
  expect(await bg(page)).toBe(dark);
  await ctx.close();
});

test("drawings are light by default, even with a dark OS", async ({ browser }) => {
  const ctx = await browser.newContext({ colorScheme: "dark" });
  const page = await ctx.newPage();
  await page.goto("/");
  await page.getByRole("button", { name: "Settings" }).click();
  const group = page.getByRole("radiogroup", { name: "Drawings theme" });
  await expect(group.getByLabel("Light")).toBeChecked();
  await group.getByText("Same as app", { exact: true }).click();
  expect(await page.evaluate(() => localStorage.getItem("scrap.drawings_theme"))).toBe("app");
  await group.getByText("Light", { exact: true }).click();
  expect(await page.evaluate(() => localStorage.getItem("scrap.drawings_theme"))).toBeNull();
  await ctx.close();
});

const SIZE = "scrap.text_size";
const rootPx = (page: Page) =>
  page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize));
const sizes = (page: Page) => page.getByRole("radiogroup", { name: "Text size" });
const open = async (page: Page) => {
  await page.getByRole("button", { name: "Settings" }).click();
  return sizes(page);
};

test.describe("Text size", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.evaluate((k) => localStorage.removeItem(k), SIZE);
    await page.reload();
  });
  test.afterEach(async ({ page }) => {
    await page.evaluate((k) => localStorage.removeItem(k), SIZE);
  });

  test("100% is the default; a size survives reload and coming back; 100% undoes it", async ({
    page,
  }) => {
    expect(await rootPx(page)).toBe(17); // 100%, as a web page is sized
    const group = await open(page);
    await expect(group.getByLabel("100%")).toBeChecked();

    await group.getByText("90%", { exact: true }).click();
    await expect.poll(() => rootPx(page)).toBeCloseTo(15.3, 1);
    // coming back to the app, and going online again, apply it again (main.ts floor)
    await page.evaluate(() => {
      dispatchEvent(new Event("online"));
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await page.waitForTimeout(300);
    expect(await rootPx(page)).toBeCloseTo(15.3, 1);

    await page.reload();
    expect(await rootPx(page)).toBeCloseTo(15.3, 1);
    await expect((await open(page)).getByLabel("90%")).toBeChecked();

    await sizes(page).getByText("130%", { exact: true }).click();
    await expect.poll(() => rootPx(page)).toBeCloseTo(22.1, 1);

    // Phone: the phone's font size (none in this browser: 17 px), marked for base.css
    await sizes(page).getByText("Phone", { exact: true }).click();
    await expect.poll(() => rootPx(page)).toBe(17);
    expect(await page.evaluate(() => document.documentElement.dataset.text)).toBe("phone");
    expect(await page.evaluate((k) => localStorage.getItem(k), SIZE)).toBe("phone");

    await sizes(page).getByText("100%", { exact: true }).click();
    await expect.poll(() => rootPx(page)).toBe(17);
    expect(await page.evaluate(() => document.documentElement.dataset.text)).toBe("");
    expect(await page.evaluate((k) => localStorage.getItem(k), SIZE)).toBeNull();
  });

  test("the app applies a kept size even if theme-init.js didn't (a stale copy)", async ({
    page,
  }) => {
    // An older theme-init.js, from before Settings had a text size, as a phone's cache once held
    await page.route("**/theme-init.js", (r) =>
      r.fulfill({ contentType: "text/javascript", body: "/* stale */" }),
    );
    await page.evaluate((k) => localStorage.setItem(k, "0.9"), SIZE);
    await page.reload();
    await expect.poll(() => rootPx(page)).toBeCloseTo(15.3, 1);
    await page.unroute("**/theme-init.js");
  });

  test("a chosen size is in place before the app starts, with no flash", async ({ page }) => {
    await page.evaluate((k) => localStorage.setItem(k, "0.8"), SIZE);
    // Record the root's size at the first moments the page can be seen, before the app's
    // module has run: theme-init.js runs from the head, so every sample is already 13.6px.
    await page.addInitScript(() => {
      const seen: string[] = [];
      (window as unknown as { seen: string[] }).seen = seen;
      const sample = () => seen.push(getComputedStyle(document.documentElement).fontSize);
      document.addEventListener("readystatechange", sample);
      document.addEventListener("DOMContentLoaded", sample);
      new MutationObserver(sample).observe(document, { childList: true, subtree: true });
    });
    await page.reload();
    const seen = await page.evaluate(() => (window as unknown as { seen: string[] }).seen);
    // the init script is registered before theme-init.js, so it samples before and after it
    const after = seen.slice(1); // the first sample may precede theme-init.js
    expect(after.length).toBeGreaterThan(0);
    for (const px of after) expect(px).toBe("13.6px");
    expect(await rootPx(page)).toBeCloseTo(13.6, 1);
  });

  test("a kept value that is not one Settings offers is 100%, on the first paint too", async ({
    page,
  }) => {
    for (const junk of ["abc", "2", "0.5"]) {
      await page.evaluate(([k, v]) => localStorage.setItem(k, v), [SIZE, junk]);
      await page.reload();
      expect(await rootPx(page)).toBe(17);
      await expect((await open(page)).getByLabel("100%")).toBeChecked();
    }
  });

  test("theme-init.js is cached by the service worker", async ({ page }) => {
    // the worker installs after the first load; wait for the shell to be in its cache
    await expect
      .poll(() => page.evaluate(async () => !!(await caches.match("/theme-init.js")) || false))
      .toBe(true);
  });
});

for (const [width, height] of [
  [1024, 1280],
  [1440, 900],
  [390, 700],
] as const) {
  test(`Settings has one scrollbar, the sheet's, with the page behind locked (${width}x${height})`, async ({
    browser,
  }) => {
    const ctx = await browser.newContext({ viewport: { width, height } });
    const page = await ctx.newPage();
    await page.goto("/");
    await page.getByRole("button", { name: "Settings" }).click();
    await expect(page.getByRole("dialog", { name: "Settings" })).toBeVisible();
    const state = await page.evaluate(() => ({
      locked: getComputedStyle(document.body).overflow === "hidden",
      docScrolls: document.documentElement.scrollHeight > document.documentElement.clientHeight,
    }));
    expect(state.locked).toBe(true); // no second scrollbar from the page behind
    expect(state.docScrolls).toBe(false);
    await page.getByRole("button", { name: "Done" }).click();
    expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).not.toBe("hidden");
    await ctx.close();
  });
}

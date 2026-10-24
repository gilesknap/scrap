// Settings from the top bar's cog: the app theme (System, Light, Dark) and the drawings'
// theme (Light, Dark, Same as app), kept on this device and applied without a reload.
import { expect, test } from "@playwright/test";

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

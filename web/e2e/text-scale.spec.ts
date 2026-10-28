// Android's font size reaches the root through the text-scale opt-in (#397); Playwright can't set
// env(preferred-text-scale), so this checks the opt-in and the rule that uses it.
import { expect, test } from "@playwright/test";

test("the page opts in to the phone's text scale, and the root size follows it", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await expect(page.locator('meta[name="text-scale"]')).toHaveAttribute("content", "scale");
  const css = await (await request.get("/")).text();
  const sheet = css.match(/href="([^"]+\.css)"/)?.[1];
  expect(sheet).toBeTruthy();
  const rules = await (await request.get(sheet as string)).text();
  expect(rules).toMatch(/env\(preferred-text-scale,\s*1\)/);
  // Without a scale from the phone the root stays at 17 px
  const root = await page.evaluate(() => getComputedStyle(document.documentElement).fontSize);
  expect(parseFloat(root)).toBeGreaterThanOrEqual(17);
});

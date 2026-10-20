// Finding things (#84): refine chips under search results, a page's tags, browse by tag.
// Runs after smoke.spec.ts (which wants an empty store); e2e/tagged.py adds synthetic pages.
import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import { lowContrast } from "./contrast";

let slugs: string[] = [];
test.beforeAll(() => {
  const data = process.env.SCRAP_E2E_DATA as string;
  const args = ["run", "--locked", "python", "web/e2e/tagged.py", data];
  const out = execFileSync("uv", args, { cwd: "..", encoding: "utf8" });
  slugs = JSON.parse(out.trim().split("\n").pop() || "[]");
});

const hits = (page: import("@playwright/test").Page) => page.locator(".hits li a strong");
const refine = (page: import("@playwright/test").Page) =>
  page.getByRole("group", { name: "Refine" });

test("refine chips narrow a search and come off again", async ({ page }) => {
  await page.goto("/search?q=zephyr+fence");
  await expect(hits(page)).toHaveCount(3);
  await expect(refine(page).getByText("3 pages")).toBeVisible();
  await expect(page.getByRole("searchbox")).not.toBeFocused(); // no keyboard over the chips
  const chip = refine(page).getByRole("button", { name: "#zephyr/garden 2" });
  const box = await chip.boundingBox();
  expect(box?.height).toBeGreaterThanOrEqual(44);
  await chip.click();
  await expect(page).toHaveURL(/q=zephyr%20fence%20tag%3Azephyr%2Fgarden$/);
  await expect(hits(page)).toHaveCount(2);
  await refine(page).getByRole("button", { name: "Personal 1" }).click();
  await expect(hits(page)).toHaveText(["Zephyr fence repair"]);
  await refine(page).getByRole("button", { name: "Remove tag:zephyr/garden" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr fence is:personal");
  await expect(hits(page)).toHaveCount(1);
  await page.getByRole("searchbox").fill("zephyr -fence");
  await expect(hits(page)).toHaveText(["Zephyr shed plans"]);
  await page.getByRole("searchbox").fill("zephyr");
  await refine(page).getByRole("button", { name: "Read 1" }).click();
  await expect(page.getByRole("searchbox")).toHaveValue("zephyr kind:read");
  await expect(hits(page)).toHaveText(["Zephyr fence book"]);
});

test("a page's tag searches for it, children too", async ({ page }) => {
  await page.goto(`/p/${slugs[0]}`);
  await page.locator(".page .tags").getByRole("link", { name: "#zephyr/garden" }).click();
  await expect(page).toHaveURL(/\/search\?q=tag%3Azephyr%2Fgarden$/);
  await expect(hits(page)).toHaveCount(3); // and zephyr/garden/shed
});

test("browse tags as a tree, then search one", async ({ page }) => {
  await page.goto("/search");
  await page.getByRole("link", { name: "Browse tags" }).first().click();
  await expect(page).toHaveURL(/\/tags$/);
  const tree = page.locator(".tagtree");
  await expect(tree.getByRole("link", { name: "#zephyr 4" })).toBeVisible();
  await expect(tree.getByRole("link", { name: "#garden 3" })).toBeHidden();
  await tree.getByRole("button", { name: "Show tags under zephyr" }).click();
  await expect(tree.getByRole("link", { name: "#garden 3" })).toBeVisible();
  await page.getByRole("searchbox", { name: "Filter tags" }).fill("shed");
  await expect(tree.getByRole("link", { name: "#shed 1" })).toBeVisible(); // its parents open
  await expect(tree.getByRole("link", { name: "#books 1" })).toBeHidden();
  await tree.getByRole("link", { name: "#shed 1" }).click();
  await expect(hits(page)).toHaveText(["Zephyr shed plans"]);
});

test("the new views meet AA contrast, in both themes", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    await page.goto("/search?q=zephyr+tag%3Azephyr");
    await expect(refine(page)).toBeVisible();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} refine`).toEqual([]);
    await page.goto(`/p/${slugs[0]}`);
    await page.locator(".page .tags a").first().waitFor();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} page tags`).toEqual([]);
    await page.goto("/tags");
    await page.locator(".tagtree a").first().waitFor();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} tags`).toEqual([]);
  }
});

import { readFileSync, writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

test("capture a note, find it, and capture offline", async ({ page, context }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill("Buy oat milk\nfrom the corner shop");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator("#queue")).toBeHidden();

  await page.getByRole("link", { name: "Recent", exact: true }).click();
  await expect(page.getByText("Buy oat milk")).toBeVisible();

  await page.getByRole("link", { name: "Search", exact: true }).click();
  await page.getByRole("searchbox").fill("corner sho");
  await expect(page.locator(".hits mark")).toHaveText(["corner", "shop"]);
  await page.locator(".hits a").first().click();
  await expect(page.getByRole("heading", { name: "Buy oat milk" })).toBeVisible();

  // Offline: the app still opens from the service worker and queues the capture.
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();
  await context.setOffline(true);
  await page.goto("/");
  await page.getByRole("button", { name: "Todo" }).click();
  await page.getByPlaceholder("Note or link").fill("Ring the plumber");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator("#queue")).toHaveText("1 waiting");
  await page.reload(); // the queue survives a reload
  await expect(page.locator("#queue")).toHaveText("1 waiting");

  await context.setOffline(false);
  await expect(page.locator("#queue")).toBeHidden();
  const pages = await (await page.request.get("/api/pages")).json();
  expect(pages.map((p: { title: string; kind: string }) => [p.title, p.kind])).toEqual([
    ["Ring the plumber", "todo"],
    ["Buy oat milk", "note"],
  ]);
});

test("the share target queues a share in the service worker", async ({ page, context }) => {
  await page.goto("/");
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();
  await context.setOffline(true); // so only the service worker can take it
  // What Android's share sheet does: a multipart POST navigation to the share_target action.
  await page.evaluate(() => {
    const form = Object.assign(document.createElement("form"), {
      method: "POST",
      action: "/share",
      enctype: "multipart/form-data",
    });
    for (const [name, value] of [
      ["title", "A story"],
      ["text", "A story https://example.com/s"],
    ]) {
      form.append(Object.assign(document.createElement("input"), { name, value }));
    }
    document.body.append(form);
    form.submit();
  });
  await expect(page.getByText("Shared item saved")).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator("#queue")).toHaveText("1 waiting");
  await context.setOffline(false);
  await expect(page.locator("#queue")).toBeHidden();
  const [hit] = await (await page.request.get("/api/search?q=story")).json();
  const shared = await (await page.request.get(`/api/pages/${hit.slug}`)).json();
  expect(shared.captures[0]).toMatchObject({
    source: "share",
    url: "https://example.com/s",
    text: "A story",
  });
});

test("a new build offers to reload", async ({ page }) => {
  const sw = new URL("../../src/scrap/static/sw.js", import.meta.url);
  const code = readFileSync(sw, "utf8");
  await page.goto("/");
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload(); // now controlled by the service worker
  try {
    writeFileSync(sw, code.replace("scrap-", "scrap-next-")); // what a new deploy looks like
    await page.evaluate(async () => (await navigator.serviceWorker.getRegistration())?.update());
    await page.getByRole("button", { name: "Reload" }).click();
    await page.waitForEvent("load");
    const caches = await page.evaluate(() => window.caches.keys());
    expect(caches).toHaveLength(1);
    expect(caches[0]).toMatch(/^scrap-next-/); // the old build's cache is gone
  } finally {
    writeFileSync(sw, code);
  }
});

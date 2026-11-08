// The login in front of scrap expired (DLS's oauth2-proxy overnight, Cloudflare Access): the
// API answers with a redirect to its sign-in, here faked as a 302 on every /api request. The
// app says so, not "Can't reach the server", with Log in again, which loads the screen marked
// login=1 (past the service worker's cache) and takes the mark off once loaded.
import { expect, type Page, test } from "@playwright/test";
import { ulid } from "./helpers";

const expire = (page: Page) =>
  page.route("**/api/**", (route) =>
    route.fulfill({ status: 302, headers: { Location: "/oauth2/start?rd=%2F" } }),
  );

test("a screen says the login expired, and Log in again loads it afresh", async ({ page }) => {
  await expire(page);
  await page.goto("/todos");
  const state = page.locator("main .empty.failed");
  await expect(state).toContainText("Your login has expired.");
  await expect(state).not.toContainText("Can't reach");
  const again = state.getByRole("button", { name: "Log in again" });
  const marked = page.waitForRequest((r) => r.isNavigationRequest() && /[?&]login=1/.test(r.url()));
  await again.click();
  await marked;
  await expect(state).toContainText("Your login has expired."); // still expired here
  await expect.poll(() => page.evaluate(() => location.pathname + location.search)).toBe("/todos");
});

test("a Save that meets the expired login says so and keeps the text", async ({ page }) => {
  const r = await page.request.post("/api/captures", {
    data: { id: ulid(), text: `Login expired save ${ulid().slice(-6)}`, kind: "note" },
  });
  const made = (await r.json()) as { page_id: string; slug: string };
  try {
    await page.goto(`/p/${made.slug}`);
    await page.locator(".page > .tools").getByRole("button", { name: "Edit" }).click();
    const box = page.locator(".editor textarea");
    await box.fill("Typed after the login expired");
    await expire(page);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    const toast = page.locator(".toast");
    await expect(toast).toContainText("Your login has expired: log in again to save.");
    await expect(toast.getByRole("button", { name: "Log in" })).toBeVisible();
    await expect(box).toHaveValue("Typed after the login expired");
  } finally {
    await page.unroute("**/api/**");
    await page.request.delete(`/api/pages/${made.page_id}`);
  }
});

// The login in front of scrap expired: every /api request is answered, as by a login proxy,
// with a 302 to its sign-in on another site. A screen then says "Your login has expired." (not
// "Can't reach the server") with Log in again, which loads the screen afresh with login=1 and
// takes the mark off the address once loaded; a page edit's Save says so with Log in, the text
// kept in the editor.
import { expect, type Page, test } from "@playwright/test";
import { ulid } from "./helpers";

const expire = (page: Page) =>
  page.route("**/api/**", (route) =>
    route.fulfill({ status: 302, headers: { Location: "https://login.invalid/start?rd=%2F" } }),
  );

test("a screen says the login expired, and Log in again loads it afresh", async ({ page }) => {
  await expire(page);
  await page.goto("/todos");
  const state = page.locator("main .empty.failed");
  await expect(state).toContainText("Your login has expired.");
  await expect(state).not.toContainText("Can't reach");
  await page.evaluate(() => {
    document.body.dataset.before = "1"; // gone once the screen has really loaded again
  });
  const loaded = page.waitForEvent(
    "framenavigated",
    (f) => f === page.mainFrame() && /[?&]login=1(&|#|$)/.test(f.url()),
  );
  await state.getByRole("button", { name: "Log in again" }).click();
  await loaded;
  await page.waitForLoadState("load");
  await expect(page.locator("body")).not.toHaveAttribute("data-before", "1");
  await expect.poll(() => page.evaluate(() => location.pathname + location.search)).toBe("/todos");
  await expect(state).toContainText("Your login has expired."); // still expired: the fake stays
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

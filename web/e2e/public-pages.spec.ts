// Public pages (#497): Share's Make public… with its warning, the Public chip and the dates
// line, Make private with Undo, links coming alive, a save published again (and not while the
// server can't be reached), and Settings' Refresh all with its one question.
//
// FIXME: written against docs/reference/public-site.md before scrap's side landed, so every
// test is test.fixme. To enable: scrap serve must have publishing on (SCRAP_PUBLISH_TO, a
// token, SCRAP_PUBLISH_SITE) with a receiver behind it (the scrap-public image's `receive`, or
// a fake that answers PUT/DELETE/manifest/sync), set in playwright.config.ts's webServer env.
import { expect, type Page, test } from "@playwright/test";
import { capture, deletedAfterEach } from "./helpers";

const made = deletedAfterEach();
test.describe.configure({ mode: "serial" });

/** A phone that shares (the Pixel's Chrome has no share sheet in tests), so Share has its menu. */
async function phone(page: Page) {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "share", { value: async () => {} });
    Object.defineProperty(navigator, "canShare", { value: () => true });
  });
}

async function newPage(page: Page, text: string, extra: Record<string, unknown> = {}) {
  const n = await capture(page, text, extra);
  made.push(n.page_id);
  return n;
}

const shareRow = (page: Page, name: RegExp | string) =>
  page
    .locator(".page > .tools")
    .getByRole("button", { name: "Share" })
    .click()
    .then(() => page.locator(".share-menu").getByRole("button", { name }).click());

const publicList = async (page: Page) =>
  (await (await page.request.get("/api/public")).json()) as {
    slug: string;
    published_at: string | null;
  }[];

test.fixme("Make public warns first, with Cancel focused, then publishes", async ({ page }) => {
  await phone(page);
  const n = await newPage(page, "Public pages e2e: a note to publish", { tags: ["e2e/public"] });
  await page.goto(`/p/${n.slug}`);
  await shareRow(page, "Make public…");
  const ask = page.getByRole("dialog", { name: "Make this page public?" });
  await expect(ask).toBeVisible();
  await expect(ask).toContainText("#e2e/public");
  await expect(ask).toContainText("Claude's write-up and summary");
  await expect(ask).toContainText("Links to private pages show their titles as plain text.");
  await expect(ask.getByRole("button", { name: "Cancel" })).toBeFocused();
  // Cancel: nothing changes
  await ask.getByRole("button", { name: "Cancel" }).click();
  await expect(ask).toHaveCount(0);
  await expect(page.locator(".pubchip")).toHaveCount(0);

  await shareRow(page, "Make public…");
  await page.getByRole("dialog").getByRole("button", { name: "Make public" }).click();
  const toast = page.locator(".toast");
  await expect(toast).toContainText("Page is public");
  await expect(toast.getByRole("button", { name: "Copy link" })).toBeVisible();
  // The chip leads the chip row and links to the page on the public site; the dates line
  // says when it was published
  const chip = page.locator(".tags > .pubchip");
  await expect(chip).toHaveText("Public");
  await expect(chip).toHaveAttribute("href", new RegExp(`/p/${n.slug}$`));
  await expect(page.locator(".dates .pubdate")).toHaveText(/^Published /);
  const listed = (await publicList(page)).find((q) => q.slug === n.slug);
  expect(listed?.published_at).toBeTruthy();
});

test.fixme("Make private acts at once, and Undo publishes it again", async ({ page }) => {
  await phone(page);
  const n = await newPage(page, "Public pages e2e: made private");
  await page.request.patch(`/api/pages/${n.page_id}`, { data: { public: true } });
  await page.goto(`/p/${n.slug}`);
  // Made public over the API: not published yet
  await expect(page.locator(".dates .pubdate")).toHaveText("Public · not published yet");
  await shareRow(page, "Make private");
  await expect(page.getByRole("dialog")).toHaveCount(0); // no question
  const toast = page.locator(".toast");
  await expect(toast).toContainText("Private: taken off");
  await expect(page.locator(".pubchip")).toHaveCount(0);
  expect((await publicList(page)).some((q) => q.slug === n.slug)).toBe(false);
  await toast.getByRole("button", { name: "Undo" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0); // no warning again
  await expect(page.locator(".dates .pubdate")).toHaveText(/^Published /);
  expect((await publicList(page)).find((q) => q.slug === n.slug)?.published_at).toBeTruthy();
});

test.fixme("making a page public publishes the public pages linking to it again", async ({
  page,
}) => {
  await phone(page);
  const target = await newPage(page, "Public pages e2e: linked to");
  const from = await newPage(page, `Public pages e2e: links to [[${target.slug}]]`);
  await page.request.patch(`/api/pages/${from.page_id}`, { data: { public: true } });
  // Published once, its link then a private page's title in plain text
  await page.goto(`/p/${from.slug}`);
  await shareRow(page, "Make private");
  await page.locator(".toast").getByRole("button", { name: "Undo" }).click();
  await expect(page.locator(".dates .pubdate")).toHaveText(/^Published /);
  // Now the page it links to goes public: the linking one is published again
  await page.goto(`/p/${target.slug}`);
  await shareRow(page, "Make public…");
  await page.getByRole("dialog").getByRole("button", { name: "Make public" }).click();
  await expect(page.locator(".toast")).toContainText("1 page linking here updated");
});

test.fixme("saving a public page publishes it again; not when scrap can't be reached", async ({
  page,
}) => {
  await phone(page);
  const n = await newPage(page, "Public pages e2e: saved");
  await page.request.patch(`/api/pages/${n.page_id}`, { data: { public: true } });
  await page.goto(`/p/${n.slug}`);
  const edit = () => page.locator(".page > .tools").getByRole("button", { name: "Edit" }).click();
  await edit();
  await page.locator(".editor textarea").fill("Public pages e2e: saved, edited");
  const sent = page.waitForRequest(
    (r) => r.method() === "PUT" && r.url().endsWith(`/api/pages/${n.page_id}/published`),
  );
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const body = (await sent).postDataJSON() as { html: string; base_rev: number; defer: boolean };
  expect(body.defer).toBe(false);
  expect(body.html.startsWith("<!DOCTYPE html>")).toBe(true);
  expect(body.html).toContain("saved, edited");
  await expect(page.locator(".dates .pubdate")).toHaveText(/^Published /);

  // The publish can't reach scrap: saved, and the toast says it isn't published
  await page.route("**/published", (r) => r.abort());
  await edit();
  await page.locator(".editor textarea").fill("Public pages e2e: saved again");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".toast")).toHaveText(
    "Saved. Not published while offline: Refresh all public pages in Settings later.",
  );
});

test.fixme("Refresh all asks once before a first publish, then refreshes every page", async ({
  page,
}) => {
  const n = await newPage(page, "Public pages e2e: never published");
  await page.request.patch(`/api/pages/${n.page_id}`, { data: { public: true } });
  const count = (await publicList(page)).length;
  await page.goto("/");
  await page.getByRole("button", { name: "Settings" }).click();
  const sheet = page.getByRole("dialog", { name: "Settings" });
  const refresh = sheet.getByRole("button", { name: /^Refresh \d+ pages?$/ });
  await expect(refresh).toHaveText(count === 1 ? "Refresh 1 page" : `Refresh ${count} pages`);
  await refresh.click();
  const ask = page.getByRole("dialog", { name: "Publish for the first time?" });
  await expect(ask).toContainText("Public pages e2e: never published");
  await ask.getByRole("button", { name: "Cancel" }).click();
  expect((await publicList(page)).find((q) => q.slug === n.slug)?.published_at).toBeNull();
  await refresh.click();
  await page
    .getByRole("dialog", { name: "Publish for the first time?" })
    .getByRole("button", { name: "OK" })
    .click();
  await expect(sheet.locator(".hint").filter({ hasText: "Refreshed" })).toContainText(
    /^Refreshed \d+ pages? at /,
  );
  expect((await publicList(page)).find((q) => q.slug === n.slug)?.published_at).toBeTruthy();
});

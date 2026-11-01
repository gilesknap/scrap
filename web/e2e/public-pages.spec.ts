// Public pages (#497), end to end: the PWA publishes through scrap to the real receiver
// (scrap-public/receiver.py), and the site is read back as nginx serves it (e2e/site.py), both
// started by playwright.config.ts. Share's Make public… with its warning, then the page on the
// site with its maths; a link coming alive; Make private taking the page off and Undo putting
// it back; a save published again, and not when scrap can't be reached; Refresh all asking
// before a first publish; and Pagefind finding a word on the home page.
import { expect, type Page, test } from "@playwright/test";
import { capture, deletedAfterEach } from "./helpers";

const made = deletedAfterEach();
test.describe.configure({ mode: "serial" });

/** The public site (playwright.config.ts: scrap's port + 2000). */
const SITE = `http://127.0.0.1:${(Number(process.env.SCRAP_E2E_PORT) || 8791) + 2000}`;
const site = (_page?: Page) => SITE;
const onSite = async (page: Page, path: string) => {
  const r = await page.request.get(`${site(page)}${path}`);
  return { status: r.status(), text: await r.text() };
};

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

const shareRow = async (page: Page, name: string) => {
  await page.locator(".page > .tools").getByRole("button", { name: "Share" }).click();
  await page.locator(".share-menu").getByRole("button", { name }).click();
};

/** Make the page shown public through Share and its warning, and wait for the toast. */
async function makePublic(page: Page) {
  await shareRow(page, "Make public…");
  await page.getByRole("dialog").getByRole("button", { name: "Make public" }).click();
  await expect(page.locator(".toast")).toContainText("Page is public");
}

test("Make public warns first, with Cancel focused, then the page is on the site", async ({
  page,
}) => {
  await phone(page);
  const word = `kumquat${Date.now().toString(36)}`;
  const n = await newPage(page, `Public e2e ${word}\n\nA formula: $x^2 + y^2$.`, {
    tags: ["e2e/public"],
  });
  await page.goto(`/p/${n.slug}`);
  await shareRow(page, "Make public…");
  const ask = page.getByRole("dialog", { name: "Make this page public?" });
  await expect(ask).toBeVisible();
  await expect(ask).toContainText(`at 127.0.0.1:${new URL(site(page)).port}`);
  await expect(ask).toContainText("#e2e/public");
  await expect(ask).toContainText("Links to private pages show their titles as plain text.");
  await expect(ask.getByRole("button", { name: "Cancel" })).toBeFocused();
  await ask.getByRole("button", { name: "Cancel" }).click();
  await expect(ask).toHaveCount(0);
  await expect(page.locator(".pubchip")).toHaveCount(0);
  expect((await onSite(page, `/p/${n.slug}`)).status).toBe(404);

  await shareRow(page, "Make public…");
  await page.getByRole("dialog").getByRole("button", { name: "Make public" }).click();
  const toast = page.locator(".toast");
  await expect(toast).toContainText("Page is public");
  await expect(toast.getByRole("button", { name: "Copy link" })).toBeVisible();
  const chip = page.locator(".tags > .pubchip");
  await expect(chip).toHaveText("Public");
  await expect(chip).toHaveAttribute("href", `${site(page)}/p/${n.slug}`);
  await expect(page.locator(".dates .pubdate")).toHaveText(/^Published /);

  // On the site: the page, its maths as KaTeX's markup with KaTeX's CSS, its tag a link
  const got = await onSite(page, `/p/${n.slug}`);
  expect(got.status).toBe(200);
  expect(got.text).toContain(word);
  expect(got.text).toContain('<span class="katex">');
  expect(got.text).toContain('<link rel="stylesheet" href="/assets/katex.css">');
  expect(got.text).toMatch(/<a href="\/t\/e2e-public-[0-9a-f]{8}">#e2e\/public<\/a>/);
  expect(got.text).not.toMatch(/scrap-(blob|tag):|\/api\//);
  for (const css of ["/assets/page.css", "/assets/katex.css"])
    expect((await onSite(page, css)).status).toBe(200);
  // Opened in a browser: drawn with the site's CSS and KaTeX's fonts
  await page.goto(`${site(page)}/p/${n.slug}`);
  await expect(page.locator(".katex-html").first()).toBeVisible();
  await expect(page.locator(".site.foot")).toContainText("from scrap · All pages");

  // Pagefind, on the home page, finds the word
  await page.goto(`${site(page)}/`);
  await expect(page.locator(".site-list")).toContainText(`Public e2e ${word}`);
  await page.locator(".pagefind-ui__search-input").fill(word);
  await expect(page.locator(".pagefind-ui__result-link").first()).toHaveAttribute(
    "href",
    new RegExp(`/p/${n.slug}`),
  );
});

test("making a page public publishes the public pages linking to it again", async ({ page }) => {
  await phone(page);
  const target = await newPage(page, "Public e2e linked to");
  const from = await newPage(page, `Public e2e linking\n\nLinks to [[${target.slug}]] here.`);
  await page.goto(`/p/${from.slug}`);
  await makePublic(page);
  // The page it links to is private: its title in plain text
  let got = await onSite(page, `/p/${from.slug}`);
  expect(got.text).toContain("<span>Public e2e linked to</span>");
  expect(got.text).not.toContain(target.slug);

  await page.goto(`/p/${target.slug}`);
  await shareRow(page, "Make public…");
  await page.getByRole("dialog").getByRole("button", { name: "Make public" }).click();
  await expect(page.locator(".toast")).toContainText(
    "Page is public · 1 page linking here updated",
  );
  got = await onSite(page, `/p/${from.slug}`);
  expect(got.text).toContain(`<a href="/p/${target.slug}">Public e2e linked to</a>`);
});

test("Make private takes the page off at once, and Undo puts it back", async ({ page }) => {
  await phone(page);
  const n = await newPage(page, "Public e2e made private");
  await page.goto(`/p/${n.slug}`);
  await makePublic(page);
  expect((await onSite(page, `/p/${n.slug}`)).status).toBe(200);

  await shareRow(page, "Make private");
  await expect(page.getByRole("dialog")).toHaveCount(0); // no question
  const toast = page.locator(".toast");
  await expect(toast).toContainText("Private: taken off 127.0.0.1");
  await expect(page.locator(".pubchip")).toHaveCount(0);
  expect((await onSite(page, `/p/${n.slug}`)).status).toBe(404);

  await toast.getByRole("button", { name: "Undo" }).click();
  await expect(page.locator(".dates .pubdate")).toHaveText(/^Published /);
  await expect(page.getByRole("dialog")).toHaveCount(0); // no warning again
  expect((await onSite(page, `/p/${n.slug}`)).status).toBe(200);
});

test("saving a public page publishes it again; not when scrap can't be reached", async ({
  page,
}) => {
  await phone(page);
  const n = await newPage(page, "Public e2e saved");
  await page.goto(`/p/${n.slug}`);
  await makePublic(page);
  const edit = () => page.locator(".page > .tools").getByRole("button", { name: "Edit" }).click();
  await edit();
  await page.locator(".editor textarea").fill("Public e2e saved, edited");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".page .body")).toContainText("edited");
  await expect
    .poll(async () => (await onSite(page, `/p/${n.slug}`)).text)
    .toContain("Public e2e saved, edited");

  // The publish can't reach scrap: saved, and the toast says it isn't published
  await page.route("**/published", (r) => r.abort());
  await edit();
  await page.locator(".editor textarea").fill("Public e2e saved again");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".toast")).toHaveText(
    "Saved. Not published while offline: Refresh all public pages in Settings later.",
  );
  expect((await onSite(page, `/p/${n.slug}`)).text).not.toContain("saved again");
});

test("Refresh all asks once before a first publish, then publishes every page", async ({
  page,
}) => {
  const n = await newPage(page, "Public e2e never published");
  // Made public over the API (as MCP would): the flag only, nothing published
  await page.request.patch(`/api/pages/${n.page_id}`, { data: { public: true } });
  await page.goto(`/p/${n.slug}`);
  await expect(page.locator(".dates .pubdate")).toHaveText("Public · not published yet");
  expect((await onSite(page, `/p/${n.slug}`)).status).toBe(404);

  await page.getByRole("button", { name: "Settings" }).click();
  const sheet = page.getByRole("dialog", { name: "Settings" });
  const refresh = sheet.getByRole("button", { name: /^Refresh \d+ pages?$/ });
  await refresh.click();
  const ask = page.getByRole("dialog", { name: "Publish for the first time?" });
  await expect(ask).toContainText("Public e2e never published");
  await ask.getByRole("button", { name: "Cancel" }).click();
  await expect(ask).toHaveCount(0);
  await expect(sheet).toBeVisible();
  expect((await onSite(page, `/p/${n.slug}`)).status).toBe(404);

  await refresh.click();
  await ask.getByRole("button", { name: "OK" }).click();
  await expect(sheet.locator(".hint").filter({ hasText: "Refreshed" })).toContainText(
    /^Refreshed \d+ pages? at /,
  );
  expect((await onSite(page, `/p/${n.slug}`)).status).toBe(200);
});

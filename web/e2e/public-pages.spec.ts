// Public pages (#497), end to end: the PWA publishes through scrap to the real receiver
// (scrap-public/receiver.py), and the site is read back as nginx serves it (e2e/site.py), both
// started by playwright.config.ts. Share's Make public… with its warning, then the page on the
// site with its maths; a link coming alive; Make private taking the page off and Undo putting
// it back; a save published again, and not when scrap can't be reached; Refresh all asking
// before a first publish (and nothing else publishing one); Pagefind finding a word on the
// home page; a photo and an attached file published with the page; and, with publishing off
// on the server, no Make public and no Settings section. The reader's theme and column width
// (#519), kept across reloads and pages, light by default; a photo's drawing (#520) with its
// Photo | Drawing tabs (pure CSS, so with JavaScript off too), the drawing alone with no photo
// in it (#524), fetched from the site and opened as a scene by Excalidraw's own loadFromBlob as
// excalidraw.com opens it (#526); scrap's icons in every head (#527); a Mermaid diagram (#525)
// drawn light and dark, one shown by the theme, its words found by search, and a code block's
// /api/ path as written (#529). The site sends nginx's headers, so a page that breaks its CSP
// fails here.
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { expect, type Page, type Route, test } from "@playwright/test";
import { capture, deletedAfterEach, png, ulid } from "./helpers";
import { SITE as SITE_PORT } from "./ports";

const made = deletedAfterEach();
test.describe.configure({ mode: "serial" });

/** The public site (e2e/ports.ts). */
const SITE = `http://127.0.0.1:${SITE_PORT}`;
const site = (_page?: Page) => SITE;
const onSite = async (page: Page, path: string) => {
  const r = await page.request.get(`${site(page)}${path}`);
  return { status: r.status(), text: await r.text() };
};

/** Every CSP violation the browser reports, for the test to say there were none. */
function violations(page: Page): string[] {
  const seen: string[] = [];
  page.on("console", (m) => {
    if (/Content Security Policy|Refused to/i.test(m.text())) seen.push(m.text());
  });
  return seen;
}

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
  // scrap's icons (#527): named in the head of the page and of home, served as themselves,
  // and /favicon.ico (asked for on its own) sent to the SVG one
  const icons =
    '<link rel="icon" href="/assets/icon.svg" type="image/svg+xml">\n' +
    '<link rel="apple-touch-icon" href="/assets/icon-192.png">';
  expect(got.text).toContain(icons);
  expect((await onSite(page, "/")).text).toContain(icons);
  for (const [path, type] of [
    ["/assets/icon.svg", "image/svg+xml"],
    ["/assets/icon-192.png", "image/png"],
  ]) {
    const icon = await page.request.get(`${SITE}${path}`);
    expect(icon.status()).toBe(200);
    expect(icon.headers()["content-type"]).toBe(type);
  }
  const shipped = await page.request.get(`${SITE}/assets/icon.svg`);
  expect(await shipped.text()).toBe(readFileSync("public/icon.svg", "utf8"));
  const ico = await page.request.get(`${SITE}/favicon.ico`, { maxRedirects: 0 });
  expect(ico.status()).toBe(302);
  expect(ico.headers().location).toBe("/assets/icon.svg");
  // Opened in a browser, under nginx's CSP: drawn with the site's CSS and KaTeX's fonts
  const csp = violations(page);
  const markLoaded = page.waitForResponse(`${SITE}/assets/icon.svg`);
  await page.goto(`${site(page)}/p/${n.slug}`);
  await expect(page.locator(".katex-html").first()).toBeVisible();
  await expect(page.locator(".site.foot")).toContainText("from scrap · All pages");
  // scrap's mark left of the site's name (#527), from the site's own icon, under its CSP
  expect((await markLoaded).status()).toBe(200);
  await expectMark(page, ".site.top > a:first-child");

  // Pagefind, on the home page, finds the word; home has the mark too
  await page.goto(`${site(page)}/`);
  await expectMark(page, ".site-head > a:first-child");
  await expect(page.locator(".site-list")).toContainText(`Public e2e ${word}`);
  await page.locator(".pagefind-ui__search-input").fill(word);
  await expect(page.locator(".pagefind-ui__result-link").first()).toHaveAttribute(
    "href",
    new RegExp(`/p/${n.slug}`),
  );
  expect(csp).toEqual([]);
});

/** scrap's mark before a header link (#527): the site's icon, about the line's height. */
async function expectMark(page: Page, link: string) {
  const mark = await page.locator(link).evaluate((a) => {
    const m = getComputedStyle(a, "::before");
    return {
      image: m.backgroundImage,
      width: Number.parseFloat(m.width),
      size: Number.parseFloat(getComputedStyle(a).fontSize),
    };
  });
  expect(mark.image).toMatch(/^url\("http:\/\/127\.0\.0\.1:\d+\/assets\/icon\.svg"\)$/);
  expect(mark.width).toBeGreaterThanOrEqual(mark.size); // about the line's height
  expect(mark.width).toBeLessThanOrEqual(mark.size * 1.5);
}

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
  // A save here doesn't publish it: that waits for the owner's yes
  await page.locator(".page > .tools").getByRole("button", { name: "Edit" }).click();
  await page.locator(".editor textarea").fill("Public e2e never published, edited");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".page .body")).toContainText("edited");
  await expect(page.locator(".dates .pubdate")).toHaveText("Public · not published yet");
  expect((await onSite(page, `/p/${n.slug}`)).status).toBe(404);
  // and scrap refuses a first publish the owner didn't confirm
  const page_ = await (await page.request.get(`/api/pages/${n.page_id}`)).json();
  const refused = await page.request.put(`/api/pages/${n.page_id}/published`, {
    data: { html: "<!DOCTYPE html>", base_rev: page_.rev },
  });
  expect(refused.status()).toBe(409);
  expect((await refused.json()).error).toBe("unconfirmed");

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

test("a photo and an attached file are published with the page", async ({ page }) => {
  await phone(page);
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", "Public e2e with files\n\nA photo and a file.");
  form.append(
    "file",
    new Blob([new Uint8Array(png(64, 48, 90))], { type: "image/png" }),
    "board.png",
  );
  form.append("file", new Blob(["Plain words"], { type: "text/plain" }), "words.txt");
  const n = (await (await page.request.post("/api/captures", { multipart: form })).json()) as {
    page_id: string;
    slug: string;
  };
  made.push(n.page_id);
  await page.goto(`/p/${n.slug}`);
  await makePublic(page);
  const got = await onSite(page, `/p/${n.slug}`);
  const img = new RegExp(`/p/${n.slug}/(img-1-[0-9a-f]{10}\\.(?:png|jpg))`).exec(got.text);
  const file = new RegExp(`/p/${n.slug}/(file-1-[0-9a-f]{10}\\.txt)`).exec(got.text);
  expect(img, got.text).toBeTruthy();
  expect(file, got.text).toBeTruthy();
  expect(got.text).not.toMatch(/scrap-blob:|\/api\//);
  const served = await page.request.get(`${SITE}/p/${n.slug}/${file?.[1]}`);
  expect(await served.text()).toBe("Plain words");
  expect(served.headers()["content-security-policy"]).toContain("sandbox");
  const csp = violations(page);
  await page.goto(`${SITE}/p/${n.slug}`);
  await expect(page.locator("figure img, .body img").first()).toBeVisible();
  expect(
    await page
      .locator("img")
      .first()
      .evaluate((i) => (i as HTMLImageElement).naturalWidth),
  ).toBeGreaterThan(0);
  expect(csp).toEqual([]);
});

test.describe("publishing off", () => {
  // (no service worker: it would answer /healthz past page.route)
  test.use({ serviceWorkers: "block" });
  test("with publishing off on the server, no Make public and no Settings section", async ({
    page,
  }) => {
    await phone(page);
    await page.route("**/healthz", async (rt) => {
      const r = await rt.fetch();
      const j = await r.json();
      await rt.fulfill({ json: { ...j, publish: { ...j.publish, enabled: false } } });
    });
    const n = await newPage(page, "Public e2e publishing off");
    await page.goto(`/p/${n.slug}`);
    await page.locator(".page > .tools").getByRole("button", { name: "Share" }).click();
    const menu = page.locator(".share-menu");
    await expect(menu.getByRole("button", { name: "Pin to Search" })).toBeVisible();
    await expect(menu.getByRole("button", { name: /Make p/ })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Settings" }).click();
    const sheet = page.getByRole("dialog", { name: "Settings" });
    await expect(sheet.getByRole("heading", { name: "Store" })).toBeVisible();
    await expect(sheet.getByRole("heading", { name: "Public pages" })).toHaveCount(0);
  });
});

/** The page made public, opened on the site: the reader's view of it. */
async function publicOne(page: Page, text: string) {
  await phone(page);
  const n = await newPage(page, text);
  await page.goto(`/p/${n.slug}`);
  await makePublic(page);
  return n;
}

const LIGHT_BG = "rgb(246, 243, 236)"; // tokens.css --bg, light and dark
const DARK_BG = "rgb(22, 20, 17)";
const bg = (page: Page) => page.evaluate(() => getComputedStyle(document.body).backgroundColor);

test.describe("the reader's theme and width (#519)", () => {
  test.use({ colorScheme: "dark" }); // a dark phone: the site is still light until chosen

  test("light by default, dark when chosen, kept across a reload and pages, no flash", async ({
    page,
  }) => {
    const n = await publicOne(page, "Public e2e theme");
    const csp = violations(page);
    // Each paint's theme, from the first: prefs.js is render-blocking, so a kept dark is on
    await page.addInitScript(() => {
      const seen: string[] = [];
      (window as unknown as { painted: string[] }).painted = seen;
      const look = () => {
        seen.push(document.documentElement.dataset.theme ?? "none");
        if (seen.length < 3) requestAnimationFrame(look);
      };
      requestAnimationFrame(look);
    });
    await page.goto(`${SITE}/p/${n.slug}`);
    expect(await bg(page)).toBe(LIGHT_BG);
    const theme = page.getByRole("button", { name: "Dark theme" });
    await expect(theme).toHaveAttribute("aria-pressed", "false");
    const box = await theme.boundingBox();
    expect(box?.height).toBeGreaterThanOrEqual(48);
    expect(box?.width).toBeGreaterThanOrEqual(48);
    await theme.focus();
    await page.keyboard.press("Enter");
    await expect(theme).toHaveAttribute("aria-pressed", "true");
    expect(await bg(page)).toBe(DARK_BG);

    await page.reload();
    // the first frame painted after the reload (the load event can come before it)
    const first = await page.waitForFunction(
      () => (window as unknown as { painted: string[] }).painted[0],
    );
    expect(await first.jsonValue()).toBe("dark");
    expect(await bg(page)).toBe(DARK_BG);
    await expect(page.getByRole("button", { name: "Dark theme" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // the home page, tag list and a 404 have it too, and keep the choice
    for (const path of ["/", "/tags", "/p/no-such-page"]) {
      await page.goto(`${SITE}${path}`);
      expect(await bg(page), path).toBe(DARK_BG);
      await expect(page.getByRole("button", { name: "Dark theme" })).toBeVisible();
    }
    await page.getByRole("button", { name: "Dark theme" }).click();
    expect(await bg(page)).toBe(LIGHT_BG);
    await page.goto(`${SITE}/p/${n.slug}`);
    expect(await bg(page)).toBe(LIGHT_BG);
    expect(csp).toEqual([]);
  });

  test("the column's width cycles and is kept; no button where it makes no difference", async ({
    page,
  }) => {
    const n = await publicOne(page, "Public e2e column width");
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`${SITE}/p/${n.slug}`);
    const column = () =>
      page.evaluate(() => {
        const s = getComputedStyle(document.body);
        return (
          document.body.clientWidth -
          Number.parseFloat(s.paddingLeft) -
          Number.parseFloat(s.paddingRight)
        );
      });
    const width = page.getByRole("button", { name: /^Column width: / });
    await expect(width).toHaveAccessibleName("Column width: Medium (800px)");
    expect(await column()).toBe(800);
    await width.click();
    await expect(width).toHaveAccessibleName("Column width: Wide (880px)");
    expect(await column()).toBe(880);
    await width.click();
    await expect(width).toHaveAccessibleName("Column width: Wider (960px)");
    await page.reload();
    await expect(width).toHaveAccessibleName("Column width: Wider (960px)");
    expect(await column()).toBe(960);
    await width.click();
    await expect(width).toHaveAccessibleName("Column width: Narrow (720px)");
    expect(await column()).toBe(720);
    await width.click(); // back to the default
    expect(await column()).toBe(800);
    // a phone: the column is the screen less its gutters whatever is chosen, so no button
    await page.setViewportSize({ width: 412, height: 800 });
    await expect(width).toBeHidden();
    await expect(page.getByRole("button", { name: "Dark theme" })).toBeVisible();
  });

  test("the header keeps one row at 308 px and 130 % text: a long name is cut (#527)", async ({
    page,
  }) => {
    const n = await publicOne(page, "Public e2e long name");
    await page.setViewportSize({ width: 308, height: 800 });
    await page.goto(`${SITE}/p/${n.slug}`);
    const theme = page.getByRole("button", { name: "Dark theme" });
    await expect(theme).toBeVisible();
    // the phone's 130 % text, and a site name far too long for the row
    const row = await page.evaluate(() => {
      document.documentElement.style.fontSize = "22.1px";
      const a = document.querySelector(".site.top > a") as HTMLElement;
      a.textContent = "a-very-long-public-site-name.pages.example.org";
      const switches = document.querySelector(".site.top .prefs") as HTMLElement;
      const [r, p] = [a.getBoundingClientRect(), switches.getBoundingClientRect()];
      return {
        cut: a.scrollWidth > a.clientWidth,
        ellipsis: getComputedStyle(a).textOverflow,
        sameRow: Math.abs(r.top + r.height / 2 - (p.top + p.height / 2)) < 4,
        clear: r.right <= p.left,
      };
    });
    expect(row).toEqual({ cut: true, ellipsis: "ellipsis", sameRow: true, clear: true });
    await expectMark(page, ".site.top > a:first-child");
  });
});

test("a table looks as the app's: sized to its words, shaded header, scrolling sideways (#530)", async ({
  page,
}) => {
  const n = await publicOne(
    page,
    "Public e2e table\n\n| Tier | Hostnames | Who gets through |\n|---|---|---|\n" +
      "| **Demo** | `argocd`, `grafana`, `argocd-monitor` | Cluster owner, plus viewers (including `diamond.ac.uk` addresses) |\n" +
      "| **Admin** | everything else under `*.gkcluster.org` (headlamp, ssh, alertmanager, scrap UI, open-webui) | Cluster owner only, and only via a **GitHub login with 2FA** |",
  );
  const read = () =>
    page.evaluate(() => {
      const box = document.querySelector(".table") as HTMLElement;
      const first = document.querySelector("tbody td") as HTMLElement;
      const strong = first.querySelector("strong") as HTMLElement;
      const th = getComputedStyle(document.querySelector("th") as HTMLElement);
      const body = Number.parseFloat(getComputedStyle(document.body).fontSize);
      const column = document.querySelector(".body") as HTMLElement;
      return {
        // "Demo" whole, on one line (it broke as "Dem/o" at 880 px)
        oneLine: strong.getClientRects().length === 1,
        shaded: th.backgroundColor !== "rgba(0, 0, 0, 0)",
        smaller: Number.parseFloat(getComputedStyle(first).fontSize) < body,
        fits: box.getBoundingClientRect().width < column.getBoundingClientRect().width,
        scrolls: box.scrollWidth > box.clientWidth,
        pageScrolls: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      };
    });
  // a computer, the owner's 880 px column: sized to its content, not the column
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`${SITE}/p/${n.slug}`);
  await page.evaluate(() => document.documentElement.style.setProperty("--column", "880px"));
  expect(await read()).toMatchObject({ oneLine: true, shaded: true, smaller: true, fits: true });
  // the owner's phone (308 px, 130 % text): the table scrolls in its box, the page does not
  await page.setViewportSize({ width: 308, height: 800 });
  await page.evaluate(() => {
    document.documentElement.style.removeProperty("--column");
    document.documentElement.style.fontSize = "22.1px";
  });
  expect(await read()).toMatchObject({ oneLine: true, scrolls: true, pageScrolls: false });
});

test("with JavaScript off a page is light, at the default width, with no switches", async ({
  page,
  browser,
}) => {
  const n = await publicOne(page, "Public e2e no script");
  const off = await browser.newContext({ javaScriptEnabled: false, colorScheme: "dark" });
  const plain = await off.newPage();
  await plain.goto(`${SITE}/p/${n.slug}`);
  expect(await bg(plain)).toBe(LIGHT_BG);
  await expect(plain.locator(".pref")).toHaveCount(0);
  // the header is no flex row then: at 308 px and 130 % text a long name is still cut in the
  // column (#527), not run off the screen
  await plain.setViewportSize({ width: 308, height: 800 });
  const cut = await plain.evaluate(() => {
    document.documentElement.style.fontSize = "22.1px";
    const a = document.querySelector(".site.top > a") as HTMLElement;
    a.textContent = "a-very-long-public-site-name.pages.example.org";
    const r = a.getBoundingClientRect();
    return {
      cut: a.scrollWidth > a.clientWidth,
      inside: r.left >= 0 && r.right <= document.documentElement.clientWidth,
      noScroll: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    };
  });
  expect(cut).toEqual({ cut: true, inside: true, noScroll: true });
  // home's "Pages · Tags", the mark before Pages: the two words on one baseline
  await plain.goto(`${SITE}/`);
  // (the words' own text boxes, not the links': off by 5 to 7 px when it clipped above the line)
  const [pages, tags] = await plain.locator(".site-head > a").evaluateAll((as) =>
    as.map((a) => {
      const words = document.createRange();
      words.selectNodeContents(a);
      return words.getClientRects()[0].bottom;
    }),
  );
  expect(Math.abs(pages - tags)).toBeLessThanOrEqual(1);
  await off.close();
});

interface Board {
  slug: string;
  capture_id: string;
  sha256: string;
}

/** A photo of a whiteboard with Claude's drawing of it (e2e/draw.py, as whiteboard.spec.ts). */
async function boardPage(page: Page): Promise<Board> {
  const data = process.env.SCRAP_E2E_DATA as string;
  const args = ["run", "--locked", "python", "web/e2e/draw.py", data];
  const out = execFileSync("uv", args, { cwd: "..", encoding: "utf8" });
  const b = JSON.parse(out.trim().split("\n").pop() || "null") as Board;
  made.push((await (await page.request.get(`/api/pages/${b.slug}`)).json()).id);
  return b;
}

/** Excalidraw's own reader of a file (the board chunk's loadFromBlob), run in the app's page on
 * a Blob as excalidraw.com makes one for #url= (#526): the browser's own fetch of the published
 * SVG, so the Blob's type is the site's Content-Type as the browser reads it. The site lets only
 * excalidraw.com read it across origins, so the app's page fetches it at a path of its own that
 * the test answers with the site's response, headers and all, as it is. What the scene holds,
 * or the error. */
async function openAsScene(page: Page, url: string) {
  const chunk = readdirSync("../src/scrap/static/assets").find((f) =>
    /^excalidraw-[\w-]+\.js$/.test(f),
  );
  const local = `/e2e-site${new URL(url).pathname}`;
  // (on the context: the app's service worker may make the fetch, past page.route)
  const proxy = async (route: Route) => route.fulfill({ response: await route.fetch({ url }) });
  await page.context().route(`**${local}`, proxy);
  try {
    return await page.evaluate(
      async ({ chunk, local }) => {
        const m = await import(chunk);
        const blob = await (await fetch(local)).blob();
        const s = await m.loadFromBlob(blob, null, null).catch((e: Error) => e);
        if (s instanceof Error) return { type: blob.type, error: s.message, types: [], files: [] };
        return {
          type: blob.type,
          error: null,
          types: s.elements.map((e: { type: string }) => e.type) as string[],
          files: Object.keys(s.files ?? {}),
        };
      },
      { chunk: `/assets/${chunk}`, local },
    );
  } finally {
    await page.context().unroute(`**${local}`, proxy);
  }
}

test("a photo's drawing is published, shown with tabs, and downloads as a scene (#520)", async ({
  page,
  browser,
}) => {
  test.slow(); // Excalidraw's chunk, and its fonts inlined in the SVG
  await phone(page);
  const b = await boardPage(page);
  await page.goto(`/p/${b.slug}`);
  await expect(page.locator(".drawing-card.ready")).toBeVisible({ timeout: 20_000 });
  await shareRow(page, "Make public…");
  const ask = page.getByRole("dialog", { name: "Make this page public?" });
  await expect(ask).toContainText("its 1 drawing, downloadable");
  await ask.getByRole("button", { name: "Make public" }).click();
  await expect(page.locator(".toast")).toContainText("Page is public", { timeout: 20_000 });

  const got = await onSite(page, `/p/${b.slug}`);
  const svgPath = new RegExp(`/p/${b.slug}/img-\\d-[0-9a-f]{10}\\.svg`).exec(got.text)?.[0];
  expect(svgPath, got.text).toBeTruthy();
  expect(got.text).toContain(
    `<a href="${svgPath}" download>Download, then open in excalidraw.com to edit</a>`,
  );
  expect(got.text).not.toContain("scrap-excalidraw"); // the e2e site is not https: no Open link
  expect(got.text).not.toMatch(/scrap-(blob|drawing):|\/api\//);
  const served = await page.request.get(`${SITE}${svgPath}`);
  expect(served.headers()["access-control-allow-origin"]).toBe("https://excalidraw.com");
  expect(served.headers()["content-security-policy"]).toContain("sandbox");
  // exactly this, no charset: excalidraw.com's loadFromBlob takes an SVG only so (#526)
  expect(served.headers()["content-type"]).toBe("image/svg+xml");
  // the drawing replaces the photo, as in the app (#524): no image in it at all
  const published = await served.text();
  expect(published).not.toMatch(/<image|data:image\/|href="#image-/);
  // white over the whole frame, as the photo was (no see-through margins in a download)
  const [, w, h] = /<svg[^>]* width="(\d+)" height="(\d+)"/.exec(published) ?? [];
  expect(published).toMatch(new RegExp(`<rect [^>]*width="${w}" height="${h}" fill="#ffffff"`));

  // On the site: the drawing shows (chosen, as in the app), Photo then Drawing switch them
  const csp = violations(page);
  await page.goto(`${SITE}/p/${b.slug}`);
  const drawing = page.locator("figure.drawing img");
  const photoFig = page.locator(".pair > figure.orig");
  await expect(drawing).toBeVisible();
  await expect(photoFig).toBeHidden();
  expect(await drawing.evaluate((i) => (i as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  const group = page.getByRole("radiogroup", { name: "Show" });
  await group.getByText("Photo", { exact: true }).click();
  await expect(photoFig).toBeVisible();
  await expect(drawing).toBeHidden();
  await expect(group.getByRole("radio", { name: "Photo" })).toBeChecked();
  await page.keyboard.press("ArrowRight"); // a radio group: the arrow keys move in it
  await expect(drawing).toBeVisible();
  await expect(photoFig).toBeHidden();
  const label = await group.getByText("Drawing", { exact: true }).boundingBox();
  expect(label?.height).toBeGreaterThanOrEqual(42); // 48 with the track round it
  expect(csp).toEqual([]);

  // Downloaded: the published SVG, with the scene in it, and no photo bytes
  const [file] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: /^Download/ }).click(),
  ]);
  const svg = readFileSync((await file.path()) as string, "utf8");
  expect(svg).toBe(published);
  expect(svg).toContain("<!-- payload-type:application/vnd.excalidraw+json -->");
  const original = Buffer.from(await (await page.request.get(`/api/blobs/${b.sha256}`)).body());
  const preview = Buffer.from(
    await (await page.request.get(`/api/blobs/${b.sha256}/preview?size=2048`)).body(),
  );
  for (const bytes of [original, preview])
    expect(svg).not.toContain(bytes.toString("base64").slice(100, 400));
  // Opened as excalidraw.com opens it (#526): fetched from the site, the Blob's type as sent,
  // and read by Excalidraw's loadFromBlob: the drawing's elements, and no photo (#524)
  await page.goto(`/p/${b.slug}`); // the app, where Excalidraw's chunk is
  const scene = await openAsScene(page, `${SITE}${svgPath}`);
  expect(scene.error).toBeNull();
  expect(scene.type).toBe("image/svg+xml");
  expect(scene.types).toEqual(expect.arrayContaining(["rectangle", "arrow", "text", "ellipse"]));
  expect(scene.types).not.toContain("image");
  expect(scene.files).toEqual([]);

  // With JavaScript off: the same tabs, in CSS alone
  const off = await browser.newContext({ javaScriptEnabled: false });
  const plain = await off.newPage();
  await plain.goto(`${SITE}/p/${b.slug}`);
  await expect(plain.locator("figure.drawing img")).toBeVisible();
  await expect(plain.locator(".pair > figure.orig")).toBeHidden();
  await plain.getByText("Photo", { exact: true }).click();
  await expect(plain.locator(".pair > figure.orig")).toBeVisible();
  await expect(plain.locator("figure.drawing img")).toBeHidden();
  await off.close();
});

test("a Mermaid diagram is published drawn, light and dark, and search finds its words (#525)", async ({
  page,
  browser,
}) => {
  test.slow(); // Mermaid's chunk, drawn twice
  await phone(page);
  const word = `quince${Date.now().toString(36)}`;
  const text = [
    "Public e2e diagram",
    "",
    "```mermaid",
    "flowchart LR",
    `  Phone -->|share| Q[${word}]`,
    "  Q --> API[/api/captures/]",
    '  API --> P["GET /api/pages/x"]',
    "```",
    "",
    "```sh",
    "curl -X POST /api/captures/",
    "```",
  ].join("\n");
  const n = await newPage(page, text);
  await page.goto(`/p/${n.slug}`);
  await expect(page.locator(".md .diagram svg")).toBeVisible();
  await makePublic(page);

  // On the site: the two images and no source; the code block's /api/ path as written (#529)
  const got = await onSite(page, `/p/${n.slug}`);
  const img = (theme: string) =>
    new RegExp(
      `<img class="${theme}" src="(/p/${n.slug}/img-\\d-[0-9a-f]{10}\\.svg)" alt="Diagram: [^"]*${word}[^"]*">`,
    );
  const light = img("light").exec(got.text)?.[1];
  const dark = img("dark").exec(got.text)?.[1];
  expect(light && dark && light !== dark, got.text).toBeTruthy();
  expect(got.text).toContain('<figure class="diagram">');
  expect(got.text).not.toContain("language-mermaid");
  expect(got.text).toContain("curl -X POST /api/captures/");
  expect(got.text).not.toMatch(/scrap-diagram:|\/api\/blobs/);
  for (const path of [light, dark]) {
    const served = await page.request.get(`${SITE}${path}`);
    expect(served.headers()["content-security-policy"]).toContain("sandbox");
    const svg = await served.text();
    expect(svg).toContain(word);
    expect(svg).toContain("api/captures");
    expect(svg).toContain("/api/pages/x"); // a label's /api/ path as written (#529)
    expect(svg).not.toMatch(/<script|<foreignObject|\son\w+=/i);
  }

  // In a browser: the light one, then the dark one when the reader chooses dark
  const csp = violations(page);
  await page.goto(`${SITE}/p/${n.slug}`);
  const shown = (theme: string) => page.locator(`figure.diagram img.${theme}`);
  await expect(shown("light")).toBeVisible();
  await expect(shown("dark")).toBeHidden();
  const size = await shown("light").evaluate((i) => (i as HTMLImageElement).naturalWidth);
  expect(size).toBeGreaterThan(0);
  await page.getByRole("button", { name: "Dark theme" }).click();
  await expect(shown("dark")).toBeVisible();
  await expect(shown("light")).toBeHidden();
  expect(await shown("dark").evaluate((i) => (i as HTMLImageElement).naturalWidth)).toBe(size);
  await page.getByRole("button", { name: "Dark theme" }).click(); // back to light, as kept
  await expect(shown("light")).toBeVisible();
  expect(csp).toEqual([]);

  // Pagefind finds a word drawn in it
  await page.goto(`${SITE}/`);
  await page.locator(".pagefind-ui__search-input").fill(word);
  await expect(page.locator(".pagefind-ui__result-link").first()).toHaveAttribute(
    "href",
    new RegExp(`/p/${n.slug}`),
  );

  // With JavaScript off: light, by CSS alone
  const off = await browser.newContext({ javaScriptEnabled: false });
  const plain = await off.newPage();
  await plain.goto(`${SITE}/p/${n.slug}`);
  await expect(plain.locator("figure.diagram img.light")).toBeVisible();
  await expect(plain.locator("figure.diagram img.dark")).toBeHidden();
  await off.close();
});

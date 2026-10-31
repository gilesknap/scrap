// A photo's Excalidraw drawing: the inert preview on the page, the full-screen viewer, edits
// (drafts, save, conflict, undo), history and export. Runs after smoke.spec.ts (which wants an
// empty store). The board is synthetic: e2e/draw.py stores it with a fake Claude answer.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";
import { lowContrast } from "./contrast";

interface Board {
  slug: string;
  capture_id: string;
  sha256: string;
}

function board(state?: "failed" | "pause" | "resume"): Board {
  const data = process.env.SCRAP_E2E_DATA as string;
  const args = ["run", "--locked", "python", "web/e2e/draw.py", data, ...(state ? [state] : [])];
  const out = execFileSync("uv", args, { cwd: "..", encoding: "utf8" });
  return JSON.parse(out.trim().split("\n").pop() || "null");
}

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};
// This test idles for seconds between API calls (page loads, `uv run` shell-outs), longer than the
// server keeps an idle connection (uvicorn closes it after 5 s). A call that reuses a pooled socket
// the server is closing fails with "socket hang up" (#333), so each call opens its own.
const fresh = { headers: { Connection: "close" } };
const drawingUrl = (b: Board) => `/api/captures/${b.capture_id}/photos/${b.sha256}/drawing`;
const dialog = (page: Page) => page.getByRole("dialog", { name: "Drawing" });
const tool = (page: Page, name: string) => dialog(page).getByRole("button", { name, exact: true });

/** Excalidraw only ever loads in its own chunk. */
function chunkLoads(page: Page) {
  const seen: string[] = [];
  page.on("request", (r) => {
    if (/\/assets\/excalidraw-[\w-]+\.js$/.test(r.url())) seen.push(r.url());
  });
  return seen;
}

/** Problems in the page, less Chrome's reports that the content security policy keeps
 * Excalidraw's CDN fallbacks for fonts out (they are never fetched). */
function problems(page: Page) {
  const seen: string[] = [];
  page.on("pageerror", (e) => seen.push(String(e)));
  page.on("console", (m) => {
    if (m.type() === "error" && !m.text().includes("esm.sh")) seen.push(m.text());
  });
  return seen;
}

async function open(page: Page) {
  await page.locator(".drawing-card").click();
  await expect(dialog(page).locator(".excalidraw canvas").first()).toBeVisible();
  await expect(dialog(page).getByRole("button", { name: /^Edit/ })).toBeEnabled();
}

/** Draw a rectangle on the canvas with the rectangle tool. */
async function rectangle(page: Page, at = 0.3) {
  await page.getByTitle(/^Rectangle/).click();
  const box = (await dialog(page).locator(".board").boundingBox()) as {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  const x = box.x + box.width * at;
  const y = box.y + box.height * 0.75;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 60, y + 40, { steps: 5 });
  await page.mouse.up();
}

const saved = (page: Page) =>
  page.waitForRequest((r) => r.method() === "PUT" && r.url().includes("/drawing"));

test("the preview is an inert image, the viewer is lazy and Back closes it", async ({ page }) => {
  const b = board();
  const loads = chunkLoads(page);
  const errors = problems(page);
  await page.goto("/");
  await page.goto("/recent");
  await page.goto(`/p/${b.slug}`);
  // the drawing's frame is known before it renders: no layout shift
  const card = page.locator(".drawing-card");
  await expect(card).toHaveAttribute("style", /aspect-ratio: 1600 \/ 1200/);
  await expect(page.locator(".drawing-card.ready svg")).toBeVisible();
  expect(loads).toHaveLength(1); // fetched for this page's preview, not on the other screens
  // Claude's card, titled by what it holds; no state pill once read
  const claude = page.locator(".photo-panel .claude");
  await expect(claude.getByRole("heading", { name: "What's in the photo" })).toBeVisible();
  await expect(claude.getByRole("status")).toHaveCount(0);
  // Its text is folded until opened
  const read = claude.locator("details", { hasText: "Text in the photo" });
  await expect(read).not.toHaveAttribute("open", "");
  await read.locator("summary").click();
  await expect(read.getByText("retry with backoff", { exact: false })).toBeVisible();

  // No live canvas on the page; a finger drag over the preview scrolls the page
  await expect(page.locator(".page canvas, .page .excalidraw")).toHaveCount(0);
  expect(await card.evaluate((el) => getComputedStyle(el).touchAction)).toBe("manipulation");
  const cdp = await page.context().newCDPSession(page);
  const r = (await card.boundingBox()) as { x: number; y: number; width: number; height: number };
  const before = await page.evaluate(() => scrollY);
  const x = Math.round(r.x + r.width / 2);
  let y = Math.round(r.y + r.height * 0.8);
  const touch = (type: "touchStart" | "touchMove" | "touchEnd") =>
    cdp.send("Input.dispatchTouchEvent", {
      type,
      touchPoints: type === "touchEnd" ? [] : [{ x, y }],
    });
  await touch("touchStart");
  for (let n = 0; n < 10; n++) {
    y -= 20;
    await touch("touchMove");
  }
  await touch("touchEnd");
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => scrollY)).toBeGreaterThan(before + 100);
  await expect(dialog(page)).toHaveCount(0);

  // A tap opens the full-screen viewer, in view mode: no drawing tools
  await open(page);
  await expect(page.getByTitle(/^Rectangle/)).toHaveCount(0);
  await expect(tool(page, "Save")).toHaveCount(0);
  // The bar's buttons side by side inside the screen (More once stretched over the rest),
  // and none of Excalidraw's own menu, whose links lead off to its site
  const boxes = await dialog(page)
    .locator(".drawing-bar > *")
    .evaluateAll((els) =>
      els.map((e) => {
        const r = e.getBoundingClientRect();
        return [r.left, r.right, r.width];
      }),
    );
  expect(boxes).toHaveLength(5);
  const vw = page.viewportSize()?.width ?? 0;
  for (const [i, [left, right, width]] of boxes.entries()) {
    expect(left).toBeGreaterThanOrEqual(0);
    expect(right).toBeLessThanOrEqual(vw);
    expect(width).toBeLessThan(vw / 2);
    if (i) expect(left).toBeGreaterThanOrEqual(boxes[i - 1][1]);
  }
  await expect(dialog(page).locator(".main-menu-trigger")).toBeHidden();
  await page.goBack(); // the phone's Back
  await expect(dialog(page)).toHaveCount(0);
  expect(new URL(page.url()).pathname).toBe(`/p/${b.slug}`);
  expect(errors).toEqual([]);
});

test("edits are kept as a draft, saved, and a stale save offers both", async ({ page }) => {
  const b = board();
  await page.goto(`/p/${b.slug}`);
  await open(page);
  await tool(page, "Edit").click();
  await rectangle(page);
  await page.waitForTimeout(800); // the draft is kept half a second after a change
  await page.goBack();
  await expect(page.getByText("Kept as a draft")).toBeVisible();

  await page.reload();
  await open(page);
  await expect(tool(page, "Edit (unsaved draft)")).toBeVisible();
  await tool(page, "Edit (unsaved draft)").click();
  await expect(dialog(page).getByText("Restored your unsaved drawing")).toBeVisible();
  const original = (await (await page.request.get(drawingUrl(b))).json()).data.elements.length;
  let put = saved(page);
  await tool(page, "Save").click();
  const sent = (await put).postDataJSON();
  expect(sent.base_version).toBe(1);
  expect(sent.scene.width).toBe(1600); // the photo's frame goes with it
  await expect(page.getByText("Saved as version 2")).toBeVisible();
  await expect(tool(page, "Edit")).toBeVisible(); // back in view mode
  const now = await (await page.request.get(drawingUrl(b))).json();
  expect(now.producer).toBe("human");
  // Claude's labels are elements now: each shape and its bound text, plus the rectangle
  expect(now.data.elements.length).toBeGreaterThan(original);

  // Someone else saves meanwhile: saving shows the conflict, and Save mine adds a version
  await tool(page, "Edit").click();
  await rectangle(page, 0.6);
  await page.request.put(drawingUrl(b), { data: { base_version: 2, scene: { elements: [] } } });
  await tool(page, "Save").click();
  await expect(dialog(page).getByText(/changed elsewhere \(now version 3\)/)).toBeVisible();
  put = saved(page);
  await tool(page, "Save mine").click();
  expect((await put).postDataJSON().base_version).toBe(3);
  await expect(page.getByText("Saved as version 4")).toBeVisible();

  // Undo takes back the last change before saving
  await tool(page, "Edit").click();
  const count = (await (await page.request.get(drawingUrl(b))).json()).data.elements.length;
  await rectangle(page, 0.45);
  // ours, in the top bar, presses Excalidraw's own (in its footer): works on iOS too
  await expect(dialog(page).locator('.excalidraw button[aria-label="Undo"]')).toHaveCount(1);
  await dialog(page).locator(".drawing-bar").getByRole("button", { name: "Undo" }).click();
  put = saved(page);
  await tool(page, "Save").click();
  expect((await put).postDataJSON().scene.elements).toHaveLength(count);
});

test("history restores a version, and the drawing exports", async ({ page }) => {
  const b = board();
  await page.request.put(drawingUrl(b), {
    data: { base_version: 1, scene: { elements: [{ type: "text", x: 1, y: 1, text: "mine" }] } },
  });
  await page.goto(`/p/${b.slug}`);
  await open(page);
  await dialog(page).getByText("More").click();
  await tool(page, "History").click();
  await expect(dialog(page).getByText(/^v2 · edited by/)).toBeVisible();
  await dialog(page).getByRole("button", { name: "Restore version 1" }).click();
  await expect(page.getByText("Version 1 restored as version 3")).toBeVisible();
  const now = await (await page.request.get(drawingUrl(b))).json();
  expect([now.version, now.restored_from, now.data.format]).toEqual([3, 1, "skeleton"]);

  for (const [label, ext] of [
    ["Export .excalidraw", "excalidraw"],
    ["Export PNG", "png"],
    ["Export SVG", "svg"],
  ]) {
    await dialog(page).getByText("More").click();
    const [file] = await Promise.all([page.waitForEvent("download"), tool(page, label).click()]);
    expect(file.suggestedFilename()).toBe(`${b.slug}-drawing-v3.${ext}`);
    if (ext === "excalidraw") {
      const scene = JSON.parse(readFileSync(await file.path(), "utf8"));
      expect(scene.type).toBe("excalidraw");
      expect(scene.elements.some((e: { text?: string }) => e.text === "Queue")).toBe(true);
    }
  }
});

test("the viewer's More menu leads with Share a PNG, only where the phone can share", async ({
  page,
}) => {
  const b = board();
  await page.addInitScript(() =>
    Object.defineProperty(navigator, "share", { value: undefined, configurable: true }),
  );
  await page.goto(`/p/${b.slug}`);
  await open(page);
  await dialog(page).getByText("More").click();
  await expect(tool(page, "History")).toBeVisible();
  await expect(tool(page, "Share")).toHaveCount(0);
  await page.reload();
  await page.evaluate(() => {
    const w = window as unknown as { shared: { title: string; files: File[] }[] };
    w.shared = [];
    Object.defineProperty(navigator, "canShare", { value: () => true, configurable: true });
    Object.defineProperty(navigator, "share", {
      value: async (d: { title: string; files: File[] }) => void w.shared.push(d),
      configurable: true,
    });
  });
  await open(page);
  await dialog(page).getByText("More").click();
  await expect(dialog(page).locator(".menu button").first()).toHaveText("Share");
  await tool(page, "Share").click();
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { shared: unknown[] }).shared.length))
    .toBe(1);
  const f = await page.evaluate(() => {
    const [d] = (window as unknown as { shared: { files: File[] }[] }).shared;
    return [d.files[0].name, d.files[0].type, d.files[0].size > 0];
  });
  expect(f).toEqual([`${b.slug}-drawing-v1.png`, "image/png", true]);
});

test("More has no Share where the phone can't share files: Export PNG saves it", async ({
  page,
}) => {
  const b = board();
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "canShare", { value: () => false, configurable: true });
    Object.defineProperty(navigator, "share", { value: async () => {}, configurable: true });
  });
  await page.goto(`/p/${b.slug}`);
  await open(page);
  await dialog(page).getByText("More").click();
  await expect(tool(page, "History")).toBeVisible();
  await expect(tool(page, "Share")).toHaveCount(0);
  const saved = page.waitForEvent("download");
  await tool(page, "Export PNG").click();
  expect((await saved).suggestedFilename()).toBe(`${b.slug}-drawing-v1.png`);
});

test("the inline drawing card follows the drawings theme, not the app's", async ({ page }) => {
  const b = board();
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto(`/p/${b.slug}`);
  const card = page.locator(".drawing-card.ready");
  const paper = () => card.evaluate((el) => getComputedStyle(el).backgroundColor);
  const strokes = () => card.locator("svg").evaluate((el) => el.outerHTML.includes("#1e1e1e"));
  // Dark app, light drawings by default: paper with dark strokes
  await expect(card.locator("svg")).toBeVisible();
  await expect(card).toHaveAttribute("data-scheme", "light");
  expect(await paper()).toBe("rgb(255, 255, 255)");
  expect(await strokes()).toBe(true);

  await page.getByRole("button", { name: "Settings" }).click();
  await page
    .getByRole("radiogroup", { name: "Drawings theme" })
    .getByText("Dark", { exact: true })
    .click();
  await expect(card).toHaveAttribute("data-scheme", "dark");
  await expect.poll(paper).toBe("rgb(18, 18, 18)"); // after the colour transition
  await expect(card.locator("svg")).toHaveAttribute("filter", /.+/); // the dark export
});

test("a failed render leaves no stale preview on the new paper", async ({ page }) => {
  const b = board();
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto(`/p/${b.slug}`);
  const card = page.locator(".drawing-card");
  await expect(card.locator("svg")).toBeVisible();
  await page.route("**/photos/*/drawing", (r) => r.abort());
  await page.getByRole("button", { name: "Settings" }).click();
  await page
    .getByRole("radiogroup", { name: "Drawings theme" })
    .getByText("Dark", { exact: true })
    .click();
  await expect(card).toHaveAttribute("data-scheme", "dark");
  await expect(card).toHaveClass(/failed/);
  await expect(card).not.toHaveClass(/ready/);
  await expect(card.locator("svg")).toHaveCount(0);
  await expect(card.locator(".drawing-status")).toContainText("Can't show the drawing");
  // Back to Light: its preview is cached, and the earlier failure leaves no mark
  await page
    .getByRole("radiogroup", { name: "Drawings theme" })
    .getByText("Light", { exact: true })
    .click();
  await expect(card).toHaveAttribute("data-scheme", "light");
  await expect(card.locator("svg")).toBeVisible();
  await expect(card).not.toHaveClass(/failed/);

  // A failure that lands after the switch back is no longer about this card
  await page.unroute("**/photos/*/drawing");
  let hold: (() => void) | undefined;
  await page.route("**/photos/*/drawing", (r) => {
    hold = () => void r.abort();
  });
  await page
    .getByRole("radiogroup", { name: "Drawings theme" })
    .getByText("Dark", { exact: true })
    .click();
  await expect.poll(() => hold).toBeDefined();
  await page
    .getByRole("radiogroup", { name: "Drawings theme" })
    .getByText("Light", { exact: true })
    .click();
  await expect(card.locator("svg")).toBeVisible();
  hold?.();
  await page.waitForTimeout(300);
  await expect(card).not.toHaveClass(/failed/);
  await expect(card.locator("svg")).toBeVisible();
});

test("dark mode, and a Regenerate that asks before replacing an edit", async ({ page }) => {
  const b = board();
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => localStorage.setItem("scrap.drawings_theme", "app")); // Same as app
  await page.request.put(drawingUrl(b), {
    data: { base_version: 1, scene: { elements: [{ type: "text", x: 1, y: 1, text: "mine" }] } },
  });
  await page.goto(`/p/${b.slug}`);
  await expect(page.locator(".drawing-card.ready svg")).toHaveAttribute("filter", /.+/);
  await open(page);
  await expect(dialog(page).locator(".excalidraw.theme--dark")).toBeVisible();
  await page.goBack();

  const again = page.locator(".photo-panel").getByRole("button", { name: "Regenerate" });
  await again.click();
  await again.click(); // asked once, not twice
  await expect(page.getByText("You edited its drawing: replace it?")).toHaveCount(1);
  const asked = page.waitForRequest((r) => r.url().endsWith("/reprocess"));
  await page.getByRole("button", { name: "Replace mine" }).click();
  expect((await asked).postDataJSON()).toEqual({ photo: b.sha256, replace_human: true });
  await expect(page.getByRole("status").filter({ hasText: "Claude ingest is off" })).toBeVisible();
});

test.describe("on a 390 px phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("Edit closes History, and new text is readable at the fitted zoom", async ({ page }) => {
    const b = board();
    await page.goto(`/p/${b.slug}`);
    await open(page);
    await dialog(page).getByText("More").click();
    await tool(page, "History").click();
    await expect(dialog(page).getByText(/^v1 · drawn by/)).toBeVisible();
    await tool(page, "Edit").click();
    // no Restore under an edit: it would swap the scene being edited
    await expect(dialog(page).getByText(/^v1 · drawn by/)).toHaveCount(0);
    await expect(dialog(page).getByRole("button", { name: /^Restore/ })).toHaveCount(0);

    // The frame is 1600 photo pixels in a 390 px screen: new text is sized to stay legible
    await page.getByTitle(/^Text/).click();
    const box = (await dialog(page).locator(".board").boundingBox()) as { x: number; y: number };
    await page.mouse.click(box.x + 60, box.y + 500);
    const typing = dialog(page).locator("textarea.excalidraw-wysiwyg");
    await typing.fill("legible");
    // Excalidraw scales its text box with a transform: its box on screen is one line
    const line = await typing.evaluate((el) => el.getBoundingClientRect().height);
    expect(line).toBeGreaterThanOrEqual(14);
    expect(line).toBeLessThanOrEqual(40);
  });
});

test("every text of the drawing screens meets AA contrast, in both themes", async ({ page }) => {
  test.setTimeout(90_000);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const b = board();
  const failed = board("failed");
  const waiting = await (
    await page.request.post("/api/captures", {
      ...fresh,
      multipart: {
        id: ulid(),
        text: "A waiting board",
        file: { name: "w.png", mimeType: "image/png", buffer: Buffer.alloc(100, 1) },
      },
    })
  ).json();
  // Excalidraw's own interface is its own; ours around it is checked
  const check = async (where: string) =>
    expect(await page.evaluate(lowContrast, ".excalidraw"), where).toEqual([]);
  for (const colorScheme of ["light", "dark", "dark, drawings dark"] as const) {
    await page.emulateMedia({ colorScheme: colorScheme === "light" ? "light" : "dark" });
    if (colorScheme.includes("drawings")) {
      await page.addInitScript(() => localStorage.setItem("scrap.drawings_theme", "dark"));
    }
    await page.goto(`/p/${b.slug}`);
    await expect(page.locator(".drawing-card.ready svg")).toBeVisible();
    await check(`${colorScheme} page: done, preview, tabs`);
    await page.getByRole("tab", { name: "Photo" }).click();
    await check(`${colorScheme} page: photo tab`);
    await page.getByRole("tab", { name: "Drawing" }).click();
    await page.goto(`/p/${failed.slug}`);
    await check(`${colorScheme} page: failed`);
    await page.goto(`/p/${waiting.slug}`);
    await check(`${colorScheme} page: waiting`);
    board("pause");
    await page.reload();
    await expect(page.getByRole("button", { name: "Resume" }).first()).toBeVisible();
    await check(`${colorScheme} page: paused`);
    board("resume");

    await page.goto(`/p/${b.slug}`);
    await open(page);
    await check(`${colorScheme} viewer`);
    await dialog(page).getByText("More").click();
    await check(`${colorScheme} viewer: menu`);
    await tool(page, "History").click();
    await check(`${colorScheme} viewer: history`);
    await tool(page, "Photo").click();
    await check(`${colorScheme} viewer: photo`);
    await tool(page, "Photo").click();
    await tool(page, "Edit").click();
    await rectangle(page);
    await page.waitForTimeout(800);
    await check(`${colorScheme} editor`);
    await page.goBack(); // keeps a draft
    await open(page);
    await dialog(page).getByRole("button", { name: /^Edit/ }).click();
    await check(`${colorScheme} editor: restored draft`);
    const now = (await (await page.request.get(drawingUrl(b), fresh)).json()).version;
    await page.request.put(drawingUrl(b), {
      ...fresh,
      data: { base_version: now, scene: { elements: [] } },
    });
    await tool(page, "Save").click();
    await expect(dialog(page).locator(".conflict")).toBeVisible();
    await check(`${colorScheme} editor: conflict`);
    await tool(page, "Discard mine, show theirs").click();
    await expect(tool(page, "Edit")).toBeVisible(); // no draft left behind
    await page.goBack();
  }
});

test("high contrast mode shows the chosen tab and a pressed Photo", async ({ page }) => {
  const b = board();
  await page.emulateMedia({ forcedColors: "active" });
  await page.goto(`/p/${b.slug}`);
  await expect(page.getByRole("tab", { selected: true })).toHaveCSS("outline-style", "solid");
  await open(page);
  await tool(page, "Photo").click();
  await expect(tool(page, "Photo")).toHaveCSS("outline-style", "solid");
});

test.describe("on a computer (a mouse, a wide window)", () => {
  test.use({ viewport: { width: 1024, height: 1280 }, isMobile: false, hasTouch: false });

  test("a page's photo and drawing are always tabbed, never side by side", async ({ page }) => {
    const b = board();
    await page.goto(`/p/${b.slug}`);
    const tabs = page.getByRole("tablist", { name: "Show" });
    await expect(tabs).toBeVisible();
    const photo = page.locator(".pair > .orig:not(.drawing)");
    const drawing = page.locator(".pair > .orig.drawing");
    // Starts on Drawing: the photo tab's panel is hidden, not beside it (the old side-by-side
    // rule showed both at once at this width)
    await expect(drawing).toBeVisible();
    await expect(photo).toBeHidden();
    await page.getByRole("tab", { name: "Photo" }).click();
    await expect(photo).toBeVisible();
    await expect(drawing).toBeHidden();
    await page.screenshot({ path: "test-results/page-pair-tabs-1024.png", fullPage: true });
  });
});

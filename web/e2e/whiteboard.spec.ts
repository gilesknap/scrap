// A photo's Excalidraw drawing: the inert preview on the page, the full-screen viewer, edits
// (drafts, save, conflict, undo), history and export. Runs after smoke.spec.ts (which wants an
// empty store). The board is synthetic: e2e/draw.py stores it with a fake Claude answer.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";

interface Board {
  slug: string;
  capture_id: string;
  sha256: string;
}

function board(): Board {
  const out = execFileSync(
    "uv",
    ["run", "--locked", "python", "web/e2e/draw.py", process.env.SCRAP_E2E_DATA as string],
    { cwd: "..", encoding: "utf8" },
  );
  return JSON.parse(out.trim().split("\n").pop() as string);
}

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
  await expect(page.getByRole("status").filter({ hasText: "Read by Claude" })).toBeVisible();
  await page.getByText("Text Claude read").click();
  await expect(page.getByText("retry with backoff", { exact: false }).first()).toBeVisible();

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
  // ours, in the top bar (Excalidraw has its own at the bottom)
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

test("dark mode, and a Reprocess that asks before replacing an edit", async ({ page }) => {
  const b = board();
  await page.emulateMedia({ colorScheme: "dark" });
  await page.request.put(drawingUrl(b), {
    data: { base_version: 1, scene: { elements: [{ type: "text", x: 1, y: 1, text: "mine" }] } },
  });
  await page.goto(`/p/${b.slug}`);
  await expect(page.locator(".drawing-card.ready svg")).toHaveAttribute("filter", /.+/);
  await open(page);
  await expect(dialog(page).locator(".excalidraw.theme--dark")).toBeVisible();
  await page.goBack();

  await page.getByRole("button", { name: "Reprocess" }).click();
  await expect(page.getByText("You edited its drawing: replace it?")).toBeVisible();
  const asked = page.waitForRequest((r) => r.url().endsWith("/reprocess"));
  await page.getByRole("button", { name: "Replace mine" }).click();
  expect((await asked).postDataJSON()).toEqual({ photo: b.sha256, replace_human: true });
  await expect(page.getByRole("status").filter({ hasText: "Claude ingest is off" })).toBeVisible();
});

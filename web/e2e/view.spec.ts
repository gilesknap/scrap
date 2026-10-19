// The page view: editing, downloads, the photo viewer and Markdown (runs after smoke.spec.ts,
// which expects an empty store).
import { deflateSync } from "node:zlib";
import { expect, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

async function note(page: Page, text: string) {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text } });
  return (await r.json()).slug as string;
}

test("Save and Cancel stay on screen while editing; Ctrl+Enter saves", async ({ page }) => {
  const slug = await note(page, "Edit me\nfirst body");
  await page.goto(`/p/${slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  const body = page.getByLabel("Body");
  await body.fill(`edited\n${"line\n".repeat(80)}`);
  await body.press("End");
  await page.mouse.wheel(0, 5000);
  await expect(page.getByRole("button", { name: "Save" })).toBeInViewport();
  await expect(page.getByRole("button", { name: "Cancel" })).toBeInViewport();
  const patch = page.waitForRequest((r) => r.method() === "PATCH");
  await body.press("Control+Enter");
  expect((await patch).postDataJSON()).not.toHaveProperty("title"); // untouched: not sent
  await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
  const saved = await (await page.request.get(`/api/pages/${slug}`)).json();
  expect(saved.body.startsWith("edited\nline\n")).toBe(true);
});

test("a page and its photos download", async ({ page }) => {
  const slug = await note(page, "Plain note");
  await page.goto(`/p/${slug}`);
  const [md] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Download" }).click(),
  ]);
  expect(md.suggestedFilename()).toBe("plain-note.md");
  await expect(page.getByText(/^Downloaded plain-note\.md \(1 kB\)/)).toBeVisible();
  await page.route("**/download", (r) => r.fulfill({ status: 404, json: { detail: "gone" } }));
  await page.getByRole("link", { name: "Download" }).click();
  await expect(page.getByText("Download failed: gone")).toBeVisible();
  await page.unroute("**/download");

  const r = await page.request.post("/api/captures", {
    multipart: {
      id: ulid(),
      text: "With a photo",
      file: { name: "pic.png", mimeType: "image/png", buffer: Buffer.alloc(100, 1) },
    },
  });
  await page.goto(`/p/${(await r.json()).slug}`);
  const [zip] = await Promise.all([
    page.waitForEvent("download"),
    page.locator(".page > .bar").getByRole("link", { name: "Download" }).click(),
  ]);
  expect(zip.suggestedFilename()).toBe("with-a-photo.zip");
  const [orig] = await Promise.all([
    page.waitForEvent("download"),
    page.locator(".originals").getByRole("link", { name: "Download" }).click(),
  ]);
  expect(orig.suggestedFilename()).toBe("pic.png");
  await expect(page.getByText(/^Downloaded pic\.png/)).toBeVisible();
});

/** A solid w x h PNG, so the viewer has real pixels to fit. */
function png(w: number, h: number, shade: number): Buffer {
  const crc = (b: Buffer) => {
    let c = ~0;
    for (const x of b) {
      c ^= x;
      for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
    }
    return ~c >>> 0;
  };
  const chunk = (type: string, data: Buffer) => {
    const body = Buffer.concat([Buffer.from(type), data]);
    const out = Buffer.alloc(body.length + 8);
    out.writeUInt32BE(data.length, 0);
    body.copy(out, 4);
    out.writeUInt32BE(crc(body), body.length + 4);
    return out;
  };
  const head = Buffer.alloc(13);
  head.writeUInt32BE(w, 0);
  head.writeUInt32BE(h, 4);
  head.set([8, 0, 0, 0, 0], 8); // 8-bit greyscale
  const rows = Buffer.alloc((w + 1) * h, shade);
  for (let y = 0; y < h; y++) rows[y * (w + 1)] = 0;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", head),
    chunk("IDAT", deflateSync(rows)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const scale = (page: Page) =>
  page.locator(".stage img").evaluate((i) => new DOMMatrix(getComputedStyle(i).transform).a);

test("the photo viewer fits, zooms, pans, pages and closes on Back", async ({ page }) => {
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", "Two photos");
  form.append(
    "file",
    new Blob([new Uint8Array(png(2000, 1000, 90))], { type: "image/png" }),
    "wide.png",
  );
  form.append(
    "file",
    new Blob([new Uint8Array(png(600, 1200, 200))], { type: "image/png" }),
    "tall.png",
  );
  const ref = await (await page.request.post("/api/captures", { multipart: form })).json();
  await page.goto(`/p/${ref.slug}`);
  await page.locator(".originals img").first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("1 / 2")).toBeVisible();
  const vw = page.viewportSize()?.width ?? 0;
  await expect.poll(() => scale(page)).toBeCloseTo(vw / 2000, 3); // fitted to the width

  const stage = page.locator(".stage");
  await stage.dblclick({ position: { x: 100, y: 300 } });
  await expect.poll(() => scale(page)).toBeGreaterThan(vw / 2000 + 0.1);
  await dialog.getByRole("button", { name: "Fit" }).click();
  await expect.poll(() => scale(page)).toBeCloseTo(vw / 2000, 3);

  // A two-finger pinch, as a phone sends it.
  const cdp = await page.context().newCDPSession(page);
  const touch = (type: "touchStart" | "touchMove" | "touchEnd", pts: [number, number][]) =>
    cdp.send("Input.dispatchTouchEvent", {
      type,
      touchPoints: pts.map(([x, y], id) => ({ x, y, id })),
    });
  await touch("touchStart", [
    [150, 400],
    [250, 400],
  ]);
  for (const d of [60, 100, 140]) {
    await touch("touchMove", [
      [200 - d, 400],
      [200 + d, 400],
    ]);
  }
  await touch("touchEnd", []);
  await expect.poll(() => scale(page)).toBeGreaterThan((vw / 2000) * 2.5);

  await dialog.getByRole("button", { name: "Next photo" }).click();
  await expect(dialog.getByText("2 / 2")).toBeVisible();
  await expect.poll(() => scale(page)).toBeCloseTo(Math.min(vw / 600, 1), 1); // the next, fitted
  const [orig] = await Promise.all([
    page.waitForEvent("download"),
    dialog.getByRole("link", { name: "Download" }).click(),
  ]);
  expect(orig.suggestedFilename()).toBe("tall.png");

  await page.goBack(); // the phone's Back button
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("heading", { name: "Two photos" })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/p/${ref.slug}$`));
});

const WIDTHS = [320, 360, 390, 412];

async function photoPage(page: Page) {
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", "Layout photos with a fairly long title that goes on and on");
  for (const n of [1, 2]) {
    form.append("file", new Blob([new Uint8Array(png(800, 600, 50 * n))]), `p${n}.png`);
  }
  return (await (await page.request.post("/api/captures", { multipart: form })).json()).slug;
}

const inside = async (page: Page, el: ReturnType<Page["locator"]>) => {
  const box = await el.boundingBox();
  const vp = page.viewportSize();
  expect(box && vp).toBeTruthy();
  if (!box || !vp) return;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(vp.width + 0.5);
  expect(box.y + box.height).toBeLessThanOrEqual(vp.height + 0.5);
  // and nothing (the bottom nav, say) lies over it
  const hit = await el.evaluate((e) => {
    const r = e.getBoundingClientRect();
    return e.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2));
  });
  expect(hit).toBe(true);
};

test("Save stays visible above the keyboard in the composer and the editor", async ({ page }) => {
  const typing = `${"a line of text\n".repeat(40)}end`;
  // The keyboard as Chrome does it with resizes-content: the whole viewport shrinks.
  const keyboard = async () => {
    const vp = page.viewportSize() as { width: number; height: number };
    await page.setViewportSize({ width: vp.width, height: Math.round(vp.height / 2) });
  };
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  await keyboard();
  await page.getByPlaceholder("Note or link").fill(typing);
  await page.getByPlaceholder("Note or link").press("End");
  await inside(page, page.getByRole("button", { name: "Save" }));
  await inside(page, page.getByRole("button", { name: "Cancel" }));
  await expect(page.locator("nav")).toBeHidden();

  await page.setViewportSize({ width: 412, height: 839 });
  const slug = await note(page, "Keyboard test");
  await page.goto(`/p/${slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  await keyboard();
  await page.getByLabel("Body").fill(typing);
  await page.getByLabel("Body").press("End");
  await inside(page, page.getByRole("button", { name: "Save" }));
});

test("the editor follows the visual viewport when only that moves", async ({ page }) => {
  // With resizes-visual (Chrome's default) the keyboard shrinks and pans only the visual
  // viewport, as a zoom does: zoom in, pan down, and check Save is still in sight.
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setPageScaleFactor", { pageScaleFactor: 2 });
  await page.mouse.move(100, 300);
  await page.mouse.wheel(0, 400); // pans the zoomed visual viewport down
  const seen = () =>
    page.evaluate(() => {
      const vv = window.visualViewport as VisualViewport;
      const save = [...document.querySelectorAll(".editor button")].find(
        (b) => b.textContent === "Save",
      ) as HTMLElement;
      const r = save.getBoundingClientRect();
      return {
        scale: vv.scale,
        offsetTop: vv.offsetTop,
        inside: r.top >= vv.offsetTop - 1 && r.bottom <= vv.offsetTop + vv.height + 1,
      };
    });
  await expect.poll(async () => (await seen()).scale).toBeGreaterThan(1.5);
  await expect.poll(async () => (await seen()).offsetTop).toBeGreaterThan(100); // panned down
  await expect.poll(async () => (await seen()).inside).toBe(true);
});

for (const width of WIDTHS) {
  test(`nothing is wider than a ${width} px phone; the viewer's controls fit`, async ({ page }) => {
    await page.setViewportSize({ width, height: 740 });
    const slug = await photoPage(page);
    const wide = () =>
      page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    for (const path of ["/", "/recent", "/search", `/p/${slug}`]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      expect(await wide(), path).toBeLessThanOrEqual(0);
    }
    await page.getByRole("button", { name: "Edit" }).click();
    expect(await wide(), "edit").toBeLessThanOrEqual(0);
    await page.goto("/");
    await page.getByRole("button", { name: "Todo" }).click();
    expect(await wide(), "composer").toBeLessThanOrEqual(0);

    await page.goto(`/p/${slug}`);
    await page.locator(".originals img").first().click();
    const dialog = page.getByRole("dialog");
    for (const name of ["Fit", "100%", "Close", "Previous photo", "Next photo"]) {
      await inside(page, dialog.getByRole("button", { name }));
    }
    await inside(page, dialog.getByRole("link", { name: "Download" }));
    expect(await wide(), "viewer").toBeLessThanOrEqual(0);
  });
}

test("Markdown: formatted page text, raw switch, and Preview while editing", async ({ page }) => {
  const slug = await note(page, "Md page\n\n**bold** and [link](javascript:alert(1)) <b>x</b>");
  await page.goto(`/p/${slug}`);
  await expect(page.locator(".body strong")).toHaveText("bold");
  await expect(page.locator(".body a")).toHaveCount(0); // no javascript: link
  await expect(page.locator(".body")).toContainText("<b>x</b>"); // shown, not run
  await page.getByRole("button", { name: "Raw text" }).click();
  await expect(page.locator(".body")).toContainText("**bold**");
  await page.reload(); // remembered
  await expect(page.locator(".body")).toContainText("**bold**");
  await page.getByRole("button", { name: "Formatted" }).click();

  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Body").fill("# Heading\n\n- one\n- two");
  await page.getByRole("button", { name: "Preview" }).click();
  await expect(page.locator(".preview h1")).toHaveText("Heading");
  await expect(page.locator(".preview li")).toHaveCount(2);
  await expect(page.getByLabel("Body")).toBeHidden();
  await page.locator(".editor").getByRole("button", { name: "Edit", exact: true }).click();
  await expect(page.getByLabel("Body")).toBeVisible();
  await page.getByRole("button", { name: "Save" }).click();
  const saved = await (await page.request.get(`/api/pages/${slug}`)).json();
  expect(saved.body).toBe("# Heading\n\n- one\n- two"); // stored as typed

  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill("*composer* preview");
  await page.getByRole("button", { name: "Preview" }).click();
  await expect(page.locator(".preview em")).toHaveText("composer");
});

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
  await expect(page.locator(".editor")).toBeHidden();
  const saved = await (await page.request.get(`/api/pages/${slug}`)).json();
  expect(saved.body).toBe("# Heading\n\n- one\n- two"); // stored as typed

  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill("*composer* preview");
  await page.getByRole("button", { name: "Preview" }).click();
  await expect(page.locator(".preview em")).toHaveText("composer");
});

test("an unsaved note survives a reload, photos too; Discard and Cancel drop it", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Todo" }).click();
  await page.getByPlaceholder("Note or link").fill("half a thought");
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByText("+ Gallery").click(),
  ]);
  await chooser.setFiles({ name: "p.png", mimeType: "image/png", buffer: png(40, 30, 99) });
  await page.waitForTimeout(600); // the draft is kept 0.4 s after typing stops
  await page.reload(); // as if the app was killed
  await page.getByRole("button", { name: "Note" }).click();
  await expect(page.getByText("Restored your unsaved draft.")).toBeVisible();
  await expect(page.getByPlaceholder("Caption (optional)")).toHaveValue("half a thought");
  await expect(page.locator(".thumb img")).toHaveCount(1);
  await expect(page.getByRole("radio", { name: "Todo" })).toBeChecked();

  // Cancel with changes asks first; saying no keeps the editor
  page.once("dialog", (d) => d.dismiss());
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.locator(".editor")).toBeVisible();
  await page.getByRole("button", { name: "Discard it" }).click();
  await expect(page.getByPlaceholder("Note or link")).toHaveValue("");
  await expect(page.locator(".thumb img")).toHaveCount(0);
  await page.getByRole("button", { name: "Cancel" }).click(); // nothing to lose: no question
  await expect(page.locator(".editor")).toBeHidden();
  await page.getByRole("button", { name: "Note" }).click();
  await expect(page.getByText("Restored your unsaved draft.")).toBeHidden();
  await expect(page.getByPlaceholder("Note or link")).toHaveValue("");
});

test("Back closes the editor, not the page, and keeps the edit as a draft", async ({ page }) => {
  const slug = await note(page, "Back test\nfirst");
  await page.goto("/recent");
  await page.goto(`/p/${slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Body").fill("Back test\nchanged");
  await page.goBack(); // the phone's Back button
  await expect(page.locator(".editor")).toBeHidden();
  await expect(page).toHaveURL(new RegExp(`/p/${slug}$`));
  await expect(page.getByText("Kept as a draft")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Edit (unsaved draft)" }).click();
  await expect(page.getByLabel("Body")).toHaveValue("Back test\nchanged");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".editor")).toBeHidden();
  await expect(page.getByRole("button", { name: "Edit", exact: true })).toBeVisible(); // draft gone
  const saved = await (await page.request.get(`/api/pages/${slug}`)).json();
  expect(saved.body).toBe("Back test\nchanged");
  await page.goBack(); // the editor's history entry is gone: Back leaves the page
  await expect(page).toHaveURL(/\/recent$/);
});

test("photos the server can't preview fall back to the file", async ({ page }) => {
  const r = await page.request.post("/api/captures", {
    multipart: {
      id: ulid(),
      text: "Unpreviewable",
      file: { name: "x.svg", mimeType: "image/svg+xml", buffer: Buffer.from("<svg/>") },
    },
  });
  const { slug } = await r.json();
  await page.goto("/recent");
  await expect(
    page.locator(".list li", { hasText: "Unpreviewable" }).locator(".noimg"),
  ).toBeVisible();
  await page.goto(`/p/${slug}`);
  await expect(page.locator(".originals a.file", { hasText: "x.svg" })).toBeVisible();
  await expect(page.locator(".originals img")).toHaveCount(0);
});

test("Share sends a page's text, or a photo as a file, to the share sheet", async ({ page }) => {
  // A stand-in share sheet: records what it was given; "abort" acts as closing it.
  await page.addInitScript(() => {
    const w = window as unknown as { shared: unknown[]; canFiles: boolean; abort: boolean };
    w.shared = [];
    w.canFiles = true;
    w.abort = false;
    let tapped = 0;
    addEventListener("click", () => (tapped = performance.now()), true);
    navigator.share = async (d?: ShareData) => {
      if (w.abort) throw new DOMException("closed", "AbortError");
      // As Chrome: only within ~5 s of a tap (not navigator.userActivation, which
      // Playwright's own evaluate calls renew)
      if (performance.now() - tapped > 5000)
        throw new DOMException("Must be handling a user gesture", "NotAllowedError");
      w.shared.push({ ...d, files: d?.files?.map((f) => [f.name, f.type, f.size]) });
    };
    navigator.canShare = () => w.canFiles;
  });
  const shared = () => page.evaluate(() => (window as unknown as { shared: unknown[] }).shared);
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", "Share me\nsome text");
  form.append(
    "file",
    new Blob([new Uint8Array(png(300, 200, 120))], { type: "image/png" }),
    "pic.png",
  );
  const { slug } = await (await page.request.post("/api/captures", { multipart: form })).json();
  await page.goto(`/p/${slug}`);
  await page.locator(".page > .bar").getByRole("button", { name: "Share" }).click();
  await expect.poll(shared).toEqual([{ title: "Share me", text: "Share me\nsome text" }]);

  await page.locator(".originals img").click();
  await page.getByRole("dialog").getByRole("button", { name: "Share" }).click();
  await expect.poll(async () => (await shared()).length).toBe(2);
  expect((await shared())[1]).toEqual({
    title: "pic.png",
    files: [["pic.png", "image/png", expect.any(Number)]],
  });

  await page.evaluate(() => {
    (window as unknown as { abort: boolean }).abort = true;
  });
  await page.getByRole("dialog").getByRole("button", { name: "Share" }).click();
  await expect(page.getByRole("dialog").getByRole("button", { name: "Share" })).toBeEnabled();
  await expect(page.getByText(/failed/)).toHaveCount(0); // closing the sheet is not an error
  await page.evaluate(() => {
    const w = window as unknown as { abort: boolean; canFiles: boolean };
    w.abort = false;
    w.canFiles = false;
  });
  await page.getByRole("dialog").getByRole("button", { name: "Share" }).click();
  await expect(page.getByText("Sharing files is not supported here")).toBeVisible();

  // A download slower than the tap's 5 s: the file is kept and shared on a fresh tap.
  await page.evaluate(() => {
    (window as unknown as { canFiles: boolean }).canFiles = true;
  });
  let fetched = 0;
  await page.route("**/api/blobs/*", async (r) => {
    fetched++;
    await new Promise((ok) => setTimeout(ok, 6000));
    await r.continue();
  });
  await page.getByRole("dialog").getByRole("button", { name: "Share" }).click();
  const ready = page.locator(".toast", { hasText: "Photo ready" });
  await expect(ready).toBeVisible({ timeout: 15_000 });
  await ready.getByRole("button", { name: "Share" }).click();
  await expect.poll(async () => (await shared()).length).toBe(3);
  expect(fetched).toBe(1); // not downloaded again
  await page.unroute("**/api/blobs/*");

  await page.setViewportSize({ width: 320, height: 640 }); // five tools still fit
  for (const name of ["Fit", "100%", "Share", "Close"])
    await inside(page, page.getByRole("dialog").getByRole("button", { name }));
});

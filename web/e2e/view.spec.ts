// The page view: editing, downloads, the photo viewer and Markdown (runs after smoke.spec.ts,
// which expects an empty store).
import { deflateSync } from "node:zlib";
import { expect, type Page, test } from "@playwright/test";
import { lowContrast } from "./contrast";

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
  await expect(page.locator(".editor")).toBeHidden(); // saved: the PATCH has been answered
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
    page.locator(".md .orig").getByRole("link", { name: "Download" }).click(),
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
  await page.locator("figure.orig img").first().click();
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
  // Over the top bar, which doesn't scroll (the fields under it may: their own scroll is not
  // the viewport's), the wheel pans the zoomed visual viewport down
  await page.mouse.move(100, 20);
  await page.mouse.wheel(0, 400);
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
    await page.getByRole("button", { name: "Note" }).click();
    expect(await wide(), "composer").toBeLessThanOrEqual(0);

    await page.goto(`/p/${slug}`);
    await page.locator("figure.orig img").first().click();
    const dialog = page.getByRole("dialog");
    for (const name of ["Fit", "100%", "Close", "Previous photo", "Next photo"]) {
      await inside(page, dialog.getByRole("button", { name }));
    }
    await inside(page, dialog.getByRole("link", { name: "Download" }));
    expect(await wide(), "viewer").toBeLessThanOrEqual(0);
  });
}

test("Markdown: formatted page text, and Preview while editing", async ({ page }) => {
  const slug = await note(page, "Md page\n\n**bold** and [link](javascript:alert(1)) <b>x</b>");
  await page.goto(`/p/${slug}`);
  await expect(page.locator(".body strong")).toHaveText("bold");
  await expect(page.locator(".body a")).toHaveCount(0); // no javascript: link
  await expect(page.locator(".body")).toContainText("<b>x</b>"); // shown, not run

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
  await page.getByRole("button", { name: "Note" }).click();
  await page.locator(".kinds").getByText("Todo").click();
  await page.getByPlaceholder("What needs doing?").fill("half a thought");
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.locator(".editor").getByRole("button", { name: "Gallery" }).click(),
  ]);
  await chooser.setFiles({ name: "p.png", mimeType: "image/png", buffer: png(40, 30, 99) });
  await page.waitForTimeout(600); // the draft is kept 0.4 s after typing stops
  await page.reload(); // as if the app was killed
  // Kept: a row over Capture's tiles, which resumes it
  await page.getByRole("button", { name: "Draft: half a thought" }).click();
  await expect(page.getByText("Restored your unsaved draft.")).toBeVisible();
  await expect(page.getByPlaceholder("Caption (optional)")).toHaveValue("half a thought");
  await expect(page.locator(".thumb img")).toHaveCount(1);
  await expect(page.locator(".kinds")).toBeHidden(); // photos: ingest decides the kind

  // Cancel with changes asks first; saying no keeps the editor
  page.once("dialog", (d) => d.dismiss());
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.locator(".editor")).toBeVisible();
  await page.getByRole("button", { name: "Discard it" }).click();
  await expect(page.getByPlaceholder("Note or link")).toHaveValue("");
  await expect(page.locator(".thumb img")).toHaveCount(0);
  await expect(page.getByRole("radio", { name: "Note" })).toBeChecked();
  await page.getByRole("button", { name: "Cancel" }).click(); // nothing to lose: no question
  await expect(page.locator(".editor")).toBeHidden();
  await expect(page.locator(".capture .draft")).toBeHidden(); // no draft left
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
  await page.getByRole("button", { name: "Edit draft (unsaved)" }).click();
  await expect(page.getByLabel("Body")).toHaveValue("Back test\nchanged");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".editor")).toBeHidden();
  await expect(page.getByRole("button", { name: "Edit", exact: true })).toBeVisible(); // draft gone
  const saved = await (await page.request.get(`/api/pages/${slug}`)).json();
  expect(saved.body).toBe("Back test\nchanged");
  await page.goBack(); // the editor's history entry is gone: Back leaves the page
  await expect(page).toHaveURL(/\/search$/); // /recent is the search screen now
});

test("embedded images are figures: viewer, name, Download and Ask Claude", async ({ page }) => {
  // A photo beside a PDF: a file capture, so Claude has not been asked about the photo
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", "Embeds");
  form.append(
    "file",
    new Blob([new Uint8Array(png(300, 200, 60))], { type: "image/png" }),
    "a.png",
  );
  form.append("file", new Blob(["%PDF-1.4"], { type: "application/pdf" }), "doc.pdf");
  form.append(
    "file",
    new Blob([new Uint8Array(png(200, 300, 160))], { type: "image/png" }),
    "b.png",
  );
  const { slug } = await (await page.request.post("/api/captures", { multipart: form })).json();
  await page.goto(`/p/${slug}`);
  const figs = page.locator(".md figure.orig");
  await expect(figs).toHaveCount(2);
  await expect(figs.locator("figcaption span")).toHaveText(["a.png", "b.png"]);
  await expect(page.locator(".originals a.file")).toHaveText("doc.pdf"); // only the PDF below
  await expect(page.locator(".originals img")).toHaveCount(0);

  await figs.nth(1).locator("img").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("2 / 2")).toBeVisible();
  await page.goBack();
  await expect(dialog).toBeHidden();

  const ask = page.waitForRequest((r) => r.url().endsWith("/reprocess"));
  await figs.first().getByRole("button", { name: "Ask Claude" }).click();
  expect((await ask).postDataJSON()).toEqual({ photo: expect.stringMatching(/^[0-9a-f]{64}$/) });
  const panel = page.locator(".md .photo-panel");
  await expect(panel.getByRole("status")).toHaveText(/^Waiting/);
  await expect(panel.locator("figcaption span")).toHaveText("a.png");
  await expect(page.getByRole("button", { name: "Ask Claude" })).toHaveCount(1); // b.png's
});

test("an image added by an edit is a figure at once; one in a list or a line stays", async ({
  page,
}) => {
  const photo = await page.request.post("/api/captures", {
    multipart: {
      id: ulid(),
      file: { name: "p.png", mimeType: "image/png", buffer: png(40, 30, 99) },
    },
  });
  const other = await (await page.request.get(`/api/pages/${(await photo.json()).slug}`)).json();
  const sha = other.captures[0].blobs[0].sha256;
  const slug = await note(page, "Text only");
  await page.goto(`/p/${slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  const embed = `![](/api/blobs/${sha})`;
  await page.getByLabel("Body").fill(`Text only\n\n${embed}\n\n- ${embed}\n\nsee ${embed} here`);
  await page.getByRole("button", { name: "Save" }).click();
  // Another page's file: a figure without Ask Claude, named by its sha
  const fig = page.locator(".md > figure.orig");
  await expect(fig).toHaveCount(1);
  await expect(fig.locator("figcaption span")).toHaveText(`Image ${sha.slice(0, 8)}`);
  await expect(page.getByRole("button", { name: "Ask Claude" })).toHaveCount(0);
  await expect(page.locator(".md li img, .md p img")).toHaveCount(2); // left as they are
  await expect(page.locator(".md figure figure, .md p figure, .md li figure")).toHaveCount(0);
});

test("every photo of the page can be opened, saved and sent, wherever the text puts it", async ({
  page,
}) => {
  const form = new FormData();
  form.append("id", ulid());
  const names = ["list", "line1", "line2", "beside", "quote"];
  for (const [i, n] of names.entries())
    form.append(
      "file",
      new Blob([new Uint8Array(png(30, 20, 20 + i * 40))], { type: "image/png" }),
      `${n}.png`,
    );
  form.append("file", new Blob(["%PDF-1.4"], { type: "application/pdf" }), "doc.pdf"); // not sent to Claude
  const { page_id, slug } = await (
    await page.request.post("/api/captures", { multipart: form })
  ).json();
  const url = `/api/pages/${page_id}`;
  const blobs = (await (await page.request.get(url)).json()).captures[0].blobs;
  const e = (i: number) => `![](/api/blobs/${blobs[i].sha256}/preview?size=2048)`;
  const body = `Text\n\n- ${e(0)}\n\n${e(1)}\n${e(2)}\n\nsee ${e(3)} here\n\n> ${e(4)}`;
  await page.request.patch(url, { data: { base_rev: 1, body } });
  await page.goto(`/p/${slug}`);
  // Two lines of images alone: a figure each, in the text
  await expect(page.locator(".md > figure.orig figcaption span")).toHaveText([
    "line1.png",
    "line2.png",
  ]);
  // In a list, beside text or in a quote: as typed, and below the text with the rest
  await expect(page.locator(".md li img, .md p img, .md blockquote img")).toHaveCount(3);
  const below = page.locator(".originals figure.orig");
  await expect(below.locator("figcaption span")).toHaveText([
    "list.png",
    "beside.png",
    "quote.png",
  ]);
  await expect(page.getByRole("button", { name: "Ask Claude" })).toHaveCount(5);
  await expect(page.locator("figure.orig").getByRole("link", { name: "Download" })).toHaveCount(5);
  await below.nth(2).locator("img").click();
  await expect(page.getByRole("dialog").getByText("5 / 5")).toBeVisible();
  await page.goBack();
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
  await expect(page.locator(".md a.file", { hasText: "x.svg" })).toBeVisible();
  await expect(page.locator("figure.orig img")).toHaveCount(0);
});

test("Share sends a page's link or text, or a photo file, to the share sheet", async ({ page }) => {
  // A stand-in share sheet: records what it was given; "abort" acts as closing it.
  await page.addInitScript(() => {
    const w = window as unknown as {
      shared: unknown[];
      canFiles: boolean;
      abort: boolean;
      block: boolean;
    };
    w.shared = [];
    w.canFiles = true;
    w.abort = false;
    w.block = false; // a refusal that is not the tap's expiry (a blocked file type)
    let tapped = 0;
    addEventListener("click", () => (tapped = performance.now()), true);
    // As Chrome: a tap's permission lasts ~5 s (the real userActivation is renewed by
    // Playwright's own evaluate calls, so it is stood in for)
    const live = () => performance.now() - tapped <= 5000;
    Object.defineProperty(navigator, "userActivation", { get: () => ({ isActive: live() }) });
    navigator.share = async (d?: ShareData) => {
      if (w.abort) throw new DOMException("closed", "AbortError");
      if (w.block) throw new DOMException("blocked type", "NotAllowedError");
      if (!live()) throw new DOMException("Must be handling a user gesture", "NotAllowedError");
      w.shared.push({ ...d, files: d?.files?.map((f) => [f.name, f.type, f.size]) });
    };
    navigator.canShare = () => w.canFiles;
  });
  const shared = () => page.evaluate(() => (window as unknown as { shared: unknown[] }).shared);
  // Share asks which (Link, or the content); each choice is a tap of its own
  const shareAs = async (where: string, choice: string) => {
    await page.locator(where).getByRole("button", { name: "Share" }).click();
    await page.locator(".share-menu").getByRole("button", { name: choice }).click();
    await expect(page.locator(".share-menu")).toHaveCount(0);
  };
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
  const link = new URL(`/p/${slug}`, page.url()).href;
  await shareAs(".page > .bar", "Text");
  await expect.poll(shared).toEqual([{ title: "Share me", text: "Share me\nsome text" }]);
  // A second tap on Share closes its menu; Link sends the page's address, nothing fetched
  const bar = page.locator(".page > .bar");
  await bar.getByRole("button", { name: "Share" }).click();
  await expect(page.locator(".share-menu")).toBeVisible();
  await inside(page, page.locator(".share-menu"));
  await bar.getByRole("button", { name: "Share" }).click();
  await expect(page.locator(".share-menu")).toHaveCount(0);
  // A tap elsewhere closes it, and so does Escape; Share says whether it is open
  const shareBtn = bar.getByRole("button", { name: "Share" });
  await shareBtn.click();
  await expect(shareBtn).toHaveAttribute("aria-expanded", "true");
  await page.locator(".page h1").click();
  await expect(page.locator(".share-menu")).toHaveCount(0);
  await expect(shareBtn).toHaveAttribute("aria-expanded", "false");
  await shareBtn.click();
  await expect(page.locator(".share-menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".share-menu")).toHaveCount(0);
  expect(await shared()).toHaveLength(1);
  // By keyboard: focus moves to the first row, arrows move between rows, Escape returns to Share
  await shareBtn.focus();
  await page.keyboard.press("Enter");
  const rows = page.locator(".share-menu button");
  await expect(rows.first()).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(rows.nth(1)).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(rows.first()).toBeFocused();
  await page.keyboard.press("ArrowUp"); // wraps to the last row (Download)
  await expect(page.locator(".share-menu > :last-child")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator(".share-menu")).toHaveCount(0);
  await expect(shareBtn).toBeFocused();
  let asked = 0;
  page.on("request", () => asked++);
  await shareAs(".page > .bar", "Link");
  await expect.poll(async () => (await shared()).length).toBe(2);
  expect((await shared())[1]).toEqual({ title: "Share me", url: link });
  expect(asked).toBe(0);
  page.removeAllListeners("request");

  await page.locator("figure.orig img").click();
  // In the viewer the menu is inside its dialog, and Escape closes the menu, not the viewer
  const viewerShare = page.getByRole("dialog").getByRole("button", { name: "Share" });
  await viewerShare.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog").locator(".share-menu")).toBeVisible();
  await expect(page.locator(".share-menu button").first()).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator(".share-menu")).toHaveCount(0);
  await expect(viewerShare).toBeFocused();
  await expect(page.getByRole("dialog")).toBeVisible();
  await shareAs('[role="dialog"]', "Link");
  await expect.poll(async () => (await shared()).length).toBe(3);
  expect((await shared())[2]).toEqual({ title: "pic.png", url: link });
  await shareAs('[role="dialog"]', "Photo");
  await expect.poll(async () => (await shared()).length).toBe(4);
  expect((await shared())[3]).toEqual({
    title: "pic.png",
    files: [["pic.png", "image/png", expect.any(Number)]],
  });

  await page.evaluate(() => {
    (window as unknown as { abort: boolean }).abort = true;
  });
  await shareAs('[role="dialog"]', "Photo");
  await expect(page.getByRole("dialog").getByRole("button", { name: "Share" })).toBeEnabled();
  await expect(page.getByText(/failed/)).toHaveCount(0); // closing the sheet is not an error
  await page.evaluate(() => {
    const w = window as unknown as { abort: boolean; canFiles: boolean };
    w.abort = false;
    w.canFiles = false;
  });
  await shareAs('[role="dialog"]', "Photo");
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
  await shareAs('[role="dialog"]', "Photo");
  const ready = page.locator(".toast", { hasText: "Photo ready" });
  await expect(ready).toBeVisible({ timeout: 15_000 });
  await ready.getByRole("button", { name: "Share" }).click();
  await expect.poll(async () => (await shared()).length).toBe(5);
  expect(fetched).toBe(1); // not downloaded again
  await page.unroute("**/api/blobs/*");
  // A refusal while the tap is live is the real error, not "Photo ready"
  await page.evaluate(() => {
    (window as unknown as { block: boolean }).block = true;
  });
  await shareAs('[role="dialog"]', "Photo");
  await expect(page.locator(".toast", { hasText: "Share failed: blocked type" })).toBeVisible();
  await expect(ready).toHaveCount(0);

  await page.setViewportSize({ width: 320, height: 640 }); // five tools still fit
  for (const name of ["Fit", "100%", "Share", "Close"])
    await inside(page, page.getByRole("dialog").getByRole("button", { name }));
});

test("without the Popover API, Share sends the content at once", async ({ page }) => {
  await page.addInitScript(() => {
    const w = window as unknown as { shared: unknown[] };
    w.shared = [];
    // A browser from before popovers
    delete (HTMLElement.prototype as Partial<HTMLElement>).showPopover;
    navigator.share = async (d?: ShareData) => void w.shared.push(d);
  });
  const shared = () => page.evaluate(() => (window as unknown as { shared: unknown[] }).shared);
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", "Old phone\nplain share");
  const { slug } = await (await page.request.post("/api/captures", { multipart: form })).json();
  await page.goto(`/p/${slug}`);
  const share = page.locator(".page > .bar").getByRole("button", { name: "Share" });
  await expect(share).not.toHaveAttribute("aria-expanded");
  await share.click();
  await expect.poll(shared).toEqual([{ title: "Old phone", text: "Old phone\nplain share" }]);
  await expect(page.locator(".share-menu")).toHaveCount(0);
});

test("placeholders stop pulsing once photos load, or fail", async ({ page }) => {
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", "Pulse check");
  form.append(
    "file",
    new Blob([new Uint8Array(png(300, 600, 80))], { type: "image/png" }),
    "t.png",
  );
  form.append("file", new Blob(["<svg/>"], { type: "image/svg+xml" }), "x.svg"); // no preview
  const { slug } = await (await page.request.post("/api/captures", { multipart: form })).json();
  // Only this capture's row and page: other specs' photos may still be loading on a busy box
  const settled = (scope: string) =>
    page.evaluate((scope) => {
      const root = document.querySelector(scope);
      if (!root) return "no view yet"; // Loading… is shown while the view waits
      const images = [...root.querySelectorAll("img")];
      if (!images.length || !images.every((i) => i.complete && i.naturalWidth)) return "loading";
      const pulsing = document
        .getAnimations()
        .filter((a) => a.playState === "running")
        .filter((a) => {
          const el = (a.effect as KeyframeEffect | null)?.target;
          return el instanceof Element && root.contains(el);
        });
      return pulsing.length ? `${pulsing.length} pulsing` : "settled";
    }, scope);
  for (const [path, scope] of [
    ["/recent", `.list li:has(a[href="/p/${slug}"])`],
    [`/p/${slug}`, ".page"],
  ]) {
    await page.goto(path);
    await expect.poll(() => settled(scope), { message: path, timeout: 15_000 }).toBe("settled");
  }
});

test("high contrast mode still shows which kind is chosen", async ({ page }) => {
  await page.emulateMedia({ forcedColors: "active" });
  await page.goto("/");
  await page.getByRole("button", { name: "Note", exact: true }).click();
  await page.locator(".kinds").getByText("Todo").click();
  const chosen = page.locator(".chips label", { has: page.getByRole("radio", { checked: true }) });
  await expect(chosen).toHaveText("Todo");
  await expect(chosen).toHaveCSS("outline-style", "solid");
});

test("every visible text meets AA contrast, in both themes", async ({ page }) => {
  test.setTimeout(60_000);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", "Contrast sweep\n\n## Plan\n\n- **bold** and `code`\n\n> a quote");
  form.append("hint", "todo"); // the older field, still accepted
  form.append(
    "file",
    new Blob([new Uint8Array(png(400, 300, 220))], { type: "image/png" }),
    "c.png",
  );
  const { slug } = await (await page.request.post("/api/captures", { multipart: form })).json();
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    const check = async (where: string) =>
      expect(await page.evaluate(lowContrast, ""), where).toEqual([]);
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await check(`${colorScheme} capture`);
    await page.getByRole("button", { name: "Note", exact: true }).click();
    await page.locator(".editor textarea").fill("x **y**");
    await check(`${colorScheme} composer`);
    await page.locator(".editor").getByRole("button", { name: "Preview" }).click();
    await check(`${colorScheme} preview`);
    page.once("dialog", (d) => d.accept());
    await page.locator(".editor").getByRole("button", { name: "Cancel" }).click();
    await page.goto("/recent");
    await page.waitForLoadState("networkidle");
    await check(`${colorScheme} recent`);
    await page.goto(`/p/${slug}`);
    await page.waitForLoadState("networkidle");
    await check(`${colorScheme} page`);
    await page.locator(".page > .tools").getByRole("link", { name: "Download" }).click();
    await page.getByText(/^Downloaded/).waitFor();
    await check(`${colorScheme} toast`);
    await page.locator("figure.orig img").click();
    await check(`${colorScheme} viewer`);
    await page.goBack();
    await page.goto("/search?q=contrast");
    await page.locator(".hits a").first().waitFor();
    await check(`${colorScheme} search`);
    await page.goto("/p/no-such-page");
    await page.getByText("Not found").waitFor();
    await check(`${colorScheme} not found`);
  }
});

test("at the largest text size the Camera button is on the first screen", async ({ page }) => {
  for (let i = 0; i < 4; i++) await note(page, `Latest row ${i} with a longish title`);
  for (const size of [
    { width: 206, height: 457 }, // a 412 px phone at 200 % text
    { width: 320, height: 640 },
    { width: 844, height: 390 }, // landscape
  ]) {
    await page.setViewportSize(size);
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await inside(page, page.getByRole("button", { name: "Camera" }));
    await expect(page.locator(".capture .list li").first()).toBeAttached(); // the list is there
  }
});

test("kinds: chosen in the editor, a link suggests Later, todos tick, the kind row filters", async ({
  page,
}) => {
  const link = await note(page, "https://example.com/kinds");
  await note(page, "Kinds: an unfiled note");
  await page.goto(`/p/${link}`);
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByRole("radio", { name: "Later" })).toBeChecked(); // a bare URL
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".editor")).toBeHidden();
  const api = async () => (await page.request.get(`/api/pages/${link}`)).json();
  expect((await api()).kind).toBe("consume");

  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByRole("radio", { name: "Whiteboard" })).toBeAttached(); // full names
  for (const width of [320, 360, 412]) {
    await page.setViewportSize({ width, height: 800 });
    const tops = await page
      .locator(".kinds label")
      .evaluateAll((ls) => new Set(ls.map((l) => l.getBoundingClientRect().top)).size);
    expect(tops, `kinds in one row at ${width} px`).toBe(1);
    await page.screenshot({ path: test.info().outputPath(`kinds-${width}.png`) });
  }
  await page.locator(".kinds").getByText("Todo").click();
  await page.getByRole("button", { name: "Save" }).click();
  await page.getByRole("button", { name: "Mark done" }).click();
  await expect(page.getByRole("button", { name: "Reopen" })).toBeVisible();
  expect(await api()).toMatchObject({ kind: "todo", kind_fixed: 1, fields: { status: "done" } });

  await page.goto("/recent?kind=todo"); // an old address: the Todos screen, on Now
  await expect(page).toHaveURL(/\/todos$/);
  await expect(page.getByRole("radio", { name: "Now" })).toBeChecked();
  await page.goto("/search?q=kind%3Atodo"); // a search of todos: still the search screen
  const kinds = page.locator(".kindrow");
  await expect(kinds.getByRole("radio", { name: "Todos" })).toBeChecked();
  await kinds.getByText("All").click();
  await expect(page).toHaveURL(/\/search$/);
  await kinds.getByText("Todos").click(); // in place, as the other kinds: not the Todos screen
  await expect(page).toHaveURL(/\/search\?q=kind%3Atodo$/);
  await expect(kinds.getByRole("radio", { name: "Todos" })).toBeChecked();
  await kinds.getByText("All").click();
  await expect(page).toHaveURL(/\/search$/);
  await expect(kinds.getByRole("radio", { name: "All" })).toBeChecked();
  await expect(
    page.locator(".list li").filter({ hasText: "an unfiled note" }).first(),
  ).toBeVisible();
  await page.getByRole("searchbox").fill("kind:todo");
  await expect(page).toHaveURL(/\/search\?q=kind%3Atodo$/);
  const rows = page.locator(".list li");
  await expect(rows.filter({ hasText: "example.com/kinds" })).toContainText("done");
  await expect(rows.filter({ hasText: "an unfiled note" })).toHaveCount(0);
  await page.reload(); // the filter stays
  await expect(kinds.getByRole("radio", { name: "Todos" })).toBeChecked();
  await expect(rows.filter({ hasText: "an unfiled note" })).toHaveCount(0);
  await kinds.getByText("Todos").click(); // another clears it
  await expect(page).toHaveURL(/\/search$/);
  await expect(kinds.getByRole("radio", { name: "All" })).toBeChecked();
  await expect(rows.filter({ hasText: "an unfiled note" })).toHaveCount(1);
  await rows.filter({ hasText: "an unfiled note" }).getByRole("link").click();
  await expect(page.locator(".pager")).toHaveAttribute("aria-label", "In Latest"); // not "All"
  for (const width of [320, 360]) {
    await page.goto("/search");
    await page.setViewportSize({ width, height: 800 });
    const tops = await kinds
      .locator("label")
      .evaluateAll((ls) =>
        ls.map((l) => [
          l.getBoundingClientRect().top,
          l.clientHeight,
          l.scrollWidth - l.clientWidth,
        ]),
      );
    expect(new Set(tops.map((t) => t[0])).size, `the kind row in one row at ${width} px`).toBe(1);
    expect(
      Math.max(...tops.map((t) => t[2])),
      `no label clipped at ${width} px`,
    ).toBeLessThanOrEqual(0);
    expect(
      Math.min(...tops.map((t) => t[1])),
      "42 px kind segments (their ::after makes the 48 px target)",
    ).toBeGreaterThanOrEqual(42);
  }

  // A slow answer for a kind left meanwhile is dropped, not shown
  await page.goto("/search");
  await page.route("**/api/pages?limit=100&kind=consume", async (route) => {
    await new Promise((ok) => setTimeout(ok, 1500));
    await route.continue();
  });
  await kinds.getByText("Later").click();
  await kinds.getByText("All").click();
  await page.waitForTimeout(2500);
  await expect(page).toHaveURL(/\/search$/);
  await expect(rows.filter({ hasText: "an unfiled note" })).toHaveCount(1);
});

test("a Note chosen for a link is kept, not made Later", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill("https://example.com/kept-note");
  await expect(page.getByRole("radio", { name: "Later" })).toBeChecked(); // suggested
  await page.locator(".kinds").getByText("Note").click();
  await page.getByRole("button", { name: "Save" }).click();
  const kept = async () => {
    const pages = await (await page.request.get("/api/pages")).json();
    return pages.find((p: { title: string }) => p.title.endsWith("/kept-note"));
  };
  await expect.poll(kept).toMatchObject({ kind: "note", kind_fixed: 1 });
  const saved = await kept();
  await page.goto(`/p/${saved.slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByRole("radio", { name: "Note" })).toBeChecked();

  // An untouched draft with a link restored later still gets Later suggested
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill("not a link yet");
  await page.waitForTimeout(600); // kept as a draft
  await page.reload();
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill("https://example.com/later");
  await expect(page.getByRole("radio", { name: "Later" })).toBeChecked();
});

test("a draft keeps only a kind the user picked, not one suggested", async ({ page }) => {
  const slug = await note(page, "https://example.com/draft-kind");
  await page.goto(`/p/${slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByRole("radio", { name: "Later" })).toBeChecked(); // suggested only
  await page.getByLabel("Title").fill("A link to read");
  await page.waitForTimeout(600); // kept as a draft
  await page.goBack(); // closes the editor, keeping the draft
  await expect(page.locator(".editor")).toBeHidden();
  const url = `/api/pages/${slug}`;
  await page.request.patch(url, { data: { kind: "todo" } }); // chosen elsewhere meanwhile
  await page.reload();
  await page.getByRole("button", { name: "Edit draft (unsaved)" }).click();
  await expect(page.getByLabel("Title")).toHaveValue("A link to read");
  await expect(page.getByRole("radio", { name: "Todo" })).toBeChecked();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".editor")).toBeHidden();
  expect(await (await page.request.get(url)).json()).toMatchObject({ kind: "todo" });

  // On an unfiled note the suggestion follows the text, as in the composer
  const other = await note(page, "https://example.com/commented");
  await page.goto(`/p/${other}`);
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByRole("radio", { name: "Later" })).toBeChecked();
  await page.getByLabel("Body").fill("https://example.com/commented\n\nmy own thoughts");
  await expect(page.getByRole("radio", { name: "Note" })).toBeChecked();
});

test("a photo page shows its thumbnail however the list found it", async ({ page }) => {
  const tag = ulid().slice(-6);
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", `Thumbed ${tag}`);
  form.append(
    "file",
    new Blob([new Uint8Array(png(300, 200, 120))], { type: "image/png" }),
    "t.png",
  );
  const { slug } = await (await page.request.post("/api/captures", { multipart: form })).json();
  const row = page.locator(".list li").filter({ has: page.locator(`a[href="/p/${slug}"]`) });
  for (const q of ["", "kind:note", tag, "after:1w", `${tag} after:1w`, "is:work"]) {
    await page.goto(q ? `/search?q=${encodeURIComponent(q)}` : "/search");
    const img = row.locator("img");
    await expect(img, q || "empty box").toBeVisible();
    await expect
      .poll(() => img.evaluate((i: HTMLImageElement) => i.naturalWidth), q)
      .toBeGreaterThan(0);
    await expect(row.locator(".noimg"), q).toHaveCount(0);
  }
  await expect(row.locator(".snip mark")).toHaveCount(0); // a filter alone: no words to mark
});

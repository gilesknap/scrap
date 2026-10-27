// Edit opens the text where the page was being read (#389), not at its top; a page not
// scrolled past its title opens at the top; a list's row swiped right opens the editor as it
// always has; Cancel and Back leave the page where it was.
import { deflateSync } from "node:zlib";
import { type CDPSession, expect, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

/** A grey PNG, w by h: an image that is drawn, so the view is taller than the text's lines. */
function png(w: number, h: number): Buffer {
  const crc = (b: Buffer) => {
    let c = ~0;
    for (const x of b) {
      c ^= x;
      for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
    }
    return ~c >>> 0;
  };
  const chunk = (type: string, data: Buffer) => {
    const t = Buffer.concat([Buffer.from(type), data]);
    const out = Buffer.alloc(t.length + 8);
    out.writeUInt32BE(data.length, 0);
    t.copy(out, 4);
    out.writeUInt32BE(crc(t), t.length + 4);
    return out;
  };
  const head = Buffer.alloc(13);
  head.writeUInt32BE(w, 0);
  head.writeUInt32BE(h, 4);
  head.set([8, 0, 0, 0, 0], 8); // 8-bit greyscale
  const rows = Buffer.alloc((w + 1) * h, 160);
  for (let y = 0; y < h; y++) rows[y * (w + 1)] = 0; // no filter
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", head),
    chunk("IDAT", deflateSync(rows)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const words = "the quick brown fox jumps over the lazy dog and keeps on running";
/** A long page: headings, paragraphs (some of several lines), a list and a photo near its top. */
async function longPage(page: Page, title: string) {
  const r = await page.request.post("/api/captures", {
    multipart: {
      id: ulid(),
      text: title,
      file: { name: "photo.png", mimeType: "image/png", buffer: png(400, 600) },
    },
  });
  const { page_id, slug } = (await r.json()) as { page_id: string; slug: string };
  const p = await (await page.request.get(`/api/pages/${page_id}`)).json();
  const embed = (p.body as string).match(/!\[[^\]]*\]\(\/api\/blobs\/[^)]+\)/)?.[0];
  expect(embed).toBeTruthy();
  const parts = [title, ""];
  for (let i = 0; i < 20; i++) {
    parts.push(`## Section ${i}`, "");
    for (let j = 0; j < 3; j++)
      parts.push(`Para ${i}.${j} ${words} ${words}.`, `Line two of ${i}.${j}.`, "");
    if (i === 2) parts.push(embed as string, "");
    if (i === 5) parts.push(...Array.from({ length: 6 }, (_, k) => `- item ${k} of the list`), "");
  }
  const body = parts.join("\n");
  const saved = await page.request.patch(`/api/pages/${page_id}`, {
    data: { base_rev: p.rev, body },
  });
  expect(saved.ok()).toBe(true);
  return { slug, body };
}

/** Tap Edit where it is, in the page's bar at the foot of the screen (click() would first
 * scroll the window to where the bar sits in the page, which a tap does not). */
const edit = (page: Page) =>
  page.getByRole("button", { name: "Edit" }).evaluate((b: HTMLElement) => b.click());

const y = (page: Page) => page.evaluate(() => Math.round(scrollY));
/** The editor closed: the page (drawn again, main.ts) back where it was left, its photo too. */
async function settled(page: Page, at: number) {
  await page.waitForLoadState("networkidle");
  await expect(page.locator(".page .body img")).toBeVisible();
  await expect.poll(() => y(page)).toBe(at);
}

/** Scroll the view so the block starting `text` is at its top, just under the top bar, as
 * when it is being read. */
async function readAt(page: Page, text: string, block = "p") {
  const para = page.locator(`.page .body ${block}`, { hasText: text });
  await expect(para).toBeVisible();
  // Until it is there (the page drawn again after the editor closes can move it meanwhile):
  // where it starts, from the top bar's foot, scrolled 8 px into it
  const under = () =>
    para.evaluate(
      (el) =>
        el.getBoundingClientRect().top -
        (document.querySelector("body > header")?.getBoundingClientRect().bottom ?? 0),
    );
  await expect(async () => {
    const by = (await under()) + 8;
    await page.evaluate((by) => window.scrollBy(0, by), by);
    expect(Math.abs((await under()) + 8)).toBeLessThan(2);
  }).toPass();
  await expect.poll(() => page.evaluate(() => history.state?.y)).toBe(await y(page));
}

/** In the editor's box: where `text`'s line is, from the box's visible top, in lines (a copy of
 * the box's lines above it, laid out as a div). */
async function linesFromTop(page: Page, text: string) {
  return page.getByLabel("Body").evaluate((t: HTMLTextAreaElement, text) => {
    const at = t.value.indexOf(text);
    const s = getComputedStyle(t);
    const div = document.createElement("div");
    for (const p of ["family", "size", "weight", "style"].map((k) => `font-${k}`))
      div.style.setProperty(p, s.getPropertyValue(p));
    for (const p of ["line-height", "letter-spacing", "word-spacing", "tab-size"])
      div.style.setProperty(p, s.getPropertyValue(p));
    for (const p of ["top", "right", "bottom", "left"].map((k) => `padding-${k}`))
      div.style.setProperty(p, s.getPropertyValue(p));
    Object.assign(div.style, {
      position: "absolute",
      visibility: "hidden",
      whiteSpace: "pre-wrap",
      overflowWrap: "break-word",
      boxSizing: "border-box",
      width: `${t.clientWidth}px`, // its padding, not its border nor scrollbar
    });
    div.textContent = t.value.slice(0, at);
    const mark = div.appendChild(document.createElement("span"));
    mark.textContent = "x";
    document.body.append(div);
    const top = mark.offsetTop - Number.parseFloat(s.paddingTop);
    div.remove();
    return (top - t.scrollTop) / Number.parseFloat(s.lineHeight);
  }, text);
}

test("Edit opens the text where the page was being read; Cancel and Back leave it there", async ({
  page,
}) => {
  const { slug } = await longPage(page, `Long read ${ulid().slice(-6)}`);
  await page.goto(`/p/${slug}`);
  await expect(page.locator(".page .body img")).toBeVisible();
  await page.waitForLoadState("networkidle"); // the photo drawn: the view's heights settled
  await readAt(page, "Para 9.1 ");
  const left = await y(page);
  expect(left).toBeGreaterThan(1000);

  await edit(page);
  const body = page.getByLabel("Body");
  await expect(body).toBeVisible();
  await expect
    .poll(() => body.evaluate((t: HTMLTextAreaElement) => t.scrollTop))
    .toBeGreaterThan(500);
  // That paragraph's line at the top of the box (a line's slack either way), the caret on it
  const from = await linesFromTop(page, "Para 9.1 ");
  expect(from).toBeGreaterThanOrEqual(-1);
  expect(from).toBeLessThan(1.5);
  expect(
    await body.evaluate((t: HTMLTextAreaElement) =>
      t.value.slice(t.selectionStart, t.selectionStart + 9),
    ),
  ).toBe("Para 9.1 ");

  // Cancel: the page where it was left
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(body).toBeHidden();
  await settled(page, left);

  // Further down, then the phone's Back from the editor: the same
  await readAt(page, "Para 14.0 ");
  const later = await y(page);
  await edit(page);
  await expect(body).toBeVisible();
  await expect.poll(() => linesFromTop(page, "Para 14.0 ")).toBeLessThan(1.5);
  expect(await linesFromTop(page, "Para 14.0 ")).toBeGreaterThanOrEqual(-1);
  await page.goBack();
  await expect(body).toBeHidden();
  await settled(page, later);

  // Inside the list: its item
  await readAt(page, "item 3 of", "li");
  await edit(page);
  await expect(body).toBeVisible();
  await expect.poll(() => linesFromTop(page, "- item 3 of")).toBeLessThan(1.5);
  expect(await linesFromTop(page, "- item 3 of")).toBeGreaterThanOrEqual(-1);
  // Saved unchanged: the page is still where it was
  const there = await y(page);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(body).toBeHidden();
  await settled(page, there);
});

test("a page not scrolled past its title opens the editor at the top", async ({ page }) => {
  const { slug } = await longPage(page, `Short read ${ulid().slice(-6)}`);
  await page.goto(`/p/${slug}`);
  await expect(page.locator(".page .body img")).toBeVisible();
  expect(await y(page)).toBe(0);
  await edit(page);
  const body = page.getByLabel("Body");
  await expect(body).toBeVisible();
  // its top, the caret there too (not at the end, where the focused box would scroll to)
  expect(await body.evaluate((t: HTMLTextAreaElement) => [t.scrollTop, t.selectionStart])).toEqual([
    0, 0,
  ]);
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(body).toBeHidden();
  await settled(page, 0);
});

test("a draft kept with other text opens where the page is being read", async ({ page }) => {
  const { slug } = await longPage(page, `Draft read ${ulid().slice(-6)}`);
  await page.goto(`/p/${slug}`);
  await expect(page.locator(".page .body img")).toBeVisible();
  await page.waitForLoadState("networkidle");
  await readAt(page, "Para 9.1 ");
  await edit(page);
  const body = page.getByLabel("Body");
  await expect(body).toBeVisible();
  await body.pressSequentially("Edited "); // at the caret: the start of Para 9.1's line
  await page.goBack(); // keeps it as a draft
  await expect(body).toBeHidden();
  await settled(page, await y(page));
  await expect(page.getByRole("button", { name: "Edit draft" })).toBeVisible();

  // Further down: the draft (as many lines as the page) opens there too
  await readAt(page, "Para 14.0 ");
  await edit(page);
  await expect(body).toBeVisible();
  await expect(page.getByText("Restored your unsaved draft.")).toBeVisible();
  await expect(body).toHaveValue(/Edited Para 9\.1 /);
  await expect.poll(() => linesFromTop(page, "Para 14.0 ")).toBeLessThan(1.5);
  expect(await linesFromTop(page, "Para 14.0 ")).toBeGreaterThanOrEqual(-1);
  page.once("dialog", (d) => void d.accept()); // Discard your changes?
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(body).toBeHidden();
});

test("a row swiped right opens the editor as it always has, not read from a view", async ({
  page,
}) => {
  const { slug } = await longPage(page, `Swiped read ${ulid().slice(-6)}`);
  const cdp: CDPSession = await page.context().newCDPSession(page);
  await page.goto("/recent");
  const row = page.locator(".list li.swipe").filter({ has: page.locator(`a[href="/p/${slug}"]`) });
  await expect(row).toBeVisible();
  const box = await row.boundingBox();
  const at = (box?.y ?? 0) + (box?.height ?? 0) / 2;
  // A finger dragged right across the row (swipe.spec.ts)
  const touch = (type: string, x?: number) =>
    cdp.send("Input.dispatchTouchEvent", {
      type: type as "touchStart",
      touchPoints: x === undefined ? [] : [{ x, y: at }],
    });
  await touch("touchStart", 100);
  for (let i = 1; i <= 8; i++) {
    await touch("touchMove", 100 + 30 * i);
    await page.waitForTimeout(16);
  }
  await touch("touchEnd");
  const body = page.getByLabel("Body");
  await expect(body).toBeVisible();
  await expect(page).toHaveURL(`/p/${slug}`);
  // The caret where the box puts it (at the end of the text), not moved to a line
  await page.waitForTimeout(300);
  expect(await body.evaluate((t: HTMLTextAreaElement) => t.selectionStart === t.value.length)).toBe(
    true,
  );
  await page.goBack(); // closes the editor
  await expect(body).toBeHidden();
});

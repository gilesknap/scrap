// Design polish, round 2: the top bar's Back, the editor's embed chips and keys, Capture's
// draft row, Capture offline, and search rows without a snippet that repeats the title.
import { expect, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

async function make(page: Page, text: string, kind = "note") {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text, kind } });
  return (await r.json()) as { page_id: string; slug: string };
}

const back = (page: Page) => page.locator("header #back");

test("every phone and browser: a page's top bar has Back, named for where it goes", async ({
  page,
}) => {
  const note = await make(page, `Named back ${ulid().slice(-6)}`);
  await page.goto(`/p/${note.slug}`);
  await expect(page.locator(".page h1")).toBeVisible();
  await expect(back(page)).toBeVisible();
  await expect(back(page)).toHaveAccessibleName("Back to Capture");
  await expect(page.locator("header .logo")).toBeHidden();
  await expect(page.locator("nav")).toBeHidden(); // the page's toolbar is the bottom bar
  await page.goto("/");
  await expect(back(page)).toBeHidden(); // a list has the wordmark
  await expect(page.locator("header .logo")).toBeVisible();
});

test("Back goes straight to the list, past the pages followed from it", async ({ page }) => {
  const tag = ulid().slice(-6);
  const far = await make(page, `Far page ${tag}`);
  const near = await make(page, `Near page ${tag}\n\nSee [the far one](/p/${far.slug}).`);
  await page.goto(`/search?q=${encodeURIComponent(`Near page ${tag}`)}`);
  await page.locator(".hits a", { hasText: `Near page ${tag}` }).click();
  await expect(page).toHaveURL(`/p/${near.slug}`);
  await page.locator(".page .body a", { hasText: "the far one" }).click();
  await expect(page).toHaveURL(`/p/${far.slug}`);
  await expect(page.locator("#backto")).toHaveText("Search"); // the list it came from
  await back(page).click();
  await expect(page).toHaveURL(/\/search\?q=/);
  await expect(page.getByRole("searchbox")).toHaveValue(`Near page ${tag}`);
  // The phone's own Back still goes one at a time
  await page.goForward();
  await expect(page).toHaveURL(`/p/${near.slug}`);
});

test("Back on a page opened cold goes to its parent; from a list, back to it", async ({ page }) => {
  const tag = ulid().slice(-6);
  const todo = await make(page, `Back todo ${tag}`, "todo");
  const note = await make(page, `Back note ${tag}`);

  // A todo opened from a link: Back is the Todos screen, in place of the page
  await page.goto(`/p/${todo.slug}`);
  await expect(page.locator(".page h1")).toHaveText(`Back todo ${tag}`);
  await expect(back(page)).toBeVisible();
  await expect(page.locator("#backto")).toHaveText("Todos");
  await expect(page.locator("header .logo")).toBeHidden(); // Back in its place
  await expect(page.locator("nav")).toBeHidden(); // the page's toolbar is the only bottom bar
  await back(page).click();
  await expect(page).toHaveURL(/\/todos$/);
  await expect(back(page)).toBeHidden();
  await expect(page.locator("nav")).toBeVisible();

  // Tapped while the page still loads, Back still knows it for a todo's
  let first = true;
  await page.route(`**/api/pages/${todo.slug}`, async (r) => {
    if (!first) return r.continue();
    first = false;
    await new Promise((ok) => setTimeout(ok, 5000)); // the page's own fetch: slow
    await r.continue().catch(() => {});
  });
  await page.goto(`/p/${todo.slug}`);
  await expect(page.getByRole("status")).toHaveText("Loading…", { timeout: 3000 });
  await back(page).click();
  await expect(page).toHaveURL(/\/todos$/);
  await page.unroute(`**/api/pages/${todo.slug}`);

  // Any other page's parent is Capture
  await page.goto(`/p/${note.slug}`);
  await expect(page.locator("#backto")).toHaveText("Capture");
  await back(page).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("button", { name: "Camera" })).toBeVisible();

  // Opened from a list: Back is history's, the list as it was (Forward still has the page)
  await page.goto(`/search?q=${tag}`);
  await page.locator(".hits a", { hasText: `Back note ${tag}` }).click();
  await expect(page).toHaveURL(`/p/${note.slug}`);
  await expect(page.locator("#backto")).toHaveText("Search");
  await back(page).click();
  await expect(page).toHaveURL(new RegExp(`/search\\?q=${tag}$`));
  await expect(page.getByRole("searchbox")).toHaveValue(tag);
  await page.goForward();
  await expect(page).toHaveURL(`/p/${note.slug}`);
});

test("the editor shows an embed as a token with a chip; ✕ removes it, Save keeps the Markdown", async ({
  page,
}) => {
  const r = await page.request.post("/api/captures", {
    multipart: {
      id: ulid(),
      text: "Chip photo",
      file: { name: "chip.png", mimeType: "image/png", buffer: Buffer.alloc(130, 9) },
    },
  });
  const ref = (await r.json()) as { page_id: string; slug: string };
  const api = async () => (await page.request.get(`/api/pages/${ref.page_id}`)).json();
  const before = await api();
  const md = /!\[[^\]]*\]\(\/api\/blobs\/[0-9a-f]{64}[^)]*\)/.exec(before.body)?.[0] ?? "";
  expect(md).not.toBe("");
  await page.goto(`/p/${ref.slug}`);

  // A short token in the box, a chip under it; Save after an edit elsewhere keeps the embed's
  // Markdown byte for byte
  await page.getByRole("button", { name: "Edit" }).click();
  const body = page.getByLabel("Body");
  await expect(body).toHaveValue(before.body.replace(md, "⟦image 1⟧"));
  const chips = page.locator(".editor .embeds .embed");
  await expect(chips).toHaveCount(1);
  // Tapped, a chip selects its token (to cut and paste it elsewhere)
  await chips.locator(".pick").click();
  const value = await body.inputValue();
  const sel = await body.evaluate((t: HTMLTextAreaElement) => [t.selectionStart, t.selectionEnd]);
  expect(value.slice(sel[0], sel[1])).toBe("⟦image 1⟧");
  await body.press("Control+Home");
  await body.pressSequentially("Kept: ");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".editor")).toBeHidden();
  const saved = await api();
  expect(saved.body).toBe(`Kept: ${before.body}`);

  // ✕ takes the token out (its line too), and the chip goes; Save warns, as deleting it would
  page.on("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "Edit" }).click();
  await chips.getByRole("button", { name: "Remove image 1" }).click();
  await expect(body).not.toHaveValue(/⟦image 1⟧/);
  await expect(chips).toHaveCount(0);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".editor")).toBeHidden();
  const after = await api();
  expect(after.body).not.toContain("/api/blobs/");
  expect(after.body).toContain("Kept: Chip photo");
});

test("the editor's key bar: Task, Bullet, Number, Indent, Outdent on one line at 320 px", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  const keys = page.locator(".editor .keys button");
  await expect(keys).toHaveText(["Task", "Bullet", "Number", "Indent", "Outdent"]);
  // The editor is still settling when it opens (fonts, the textarea's autosize), so poll the
  // boxes until they fit rather than reading them once.
  await expect
    .poll(
      async () => {
        const boxes = await keys.evaluateAll((ks) =>
          ks.map((k) => {
            const r = k.getBoundingClientRect();
            return { x: r.x, right: r.right, y: r.y, height: r.height };
          }),
        );
        const misfits = boxes.filter(
          (b) => b.x < 0 || b.right > 320 || b.y !== boxes[0]?.y || b.height < 44,
        );
        return { count: boxes.length, misfits };
      },
      { message: "the keys on one line, inside 320 px, 44 px tall" },
    )
    .toEqual({ count: 5, misfits: [] });
  // What they do (listedit.ts has the rules; here, that the keys apply them)
  const text = page.getByPlaceholder("Note or link");
  const key = (name: string) => page.locator(".editor .keys").getByRole("button", { name });
  await text.fill("milk");
  await key("Bullet: make the line a bullet").click();
  await expect(text).toHaveValue("- milk");
  await text.press("End");
  await text.press("Enter");
  await text.pressSequentially("eggs");
  await expect(text).toHaveValue("- milk\n- eggs");
  await key("Indent the line").click();
  await expect(text).toHaveValue("- milk\n  - eggs");
  await key("Outdent the line").click();
  await expect(text).toHaveValue("- milk\n- eggs");
  await key("Number: make the line a numbered item").click();
  await expect(text).toHaveValue("- milk\n1. eggs");
  await key("Task: make the line a task").click();
  await expect(text).toHaveValue("- milk\n1. [ ] eggs");
});

test("a kept draft is a row over Capture's tiles: Back keeps it, Note starts afresh, ✕ and Undo", async ({
  page,
}) => {
  await page.goto("/");
  const row = page.locator(".capture .draft");
  await expect(row).toBeHidden(); // none yet
  const text = page.getByPlaceholder("Note or link");

  // Back with something typed keeps it as the draft, shown over the tiles
  await page.getByRole("button", { name: "Note" }).click();
  await text.fill("Numbat drafts\nsecond line");
  await page.goBack(); // the phone's Back
  await expect(page.locator(".editor")).toBeHidden();
  await expect(page.locator(".toast")).toContainText("Kept as a draft");
  await expect(row).toBeVisible();
  const resume = row.getByRole("button", { name: "Draft: Numbat drafts" });
  await expect(resume).toBeVisible();
  // Over the tiles, the whole width
  const [r, tile] = await Promise.all([
    row.boundingBox(),
    page.getByRole("button", { name: "Camera" }).boundingBox(),
  ]);
  expect((r?.y ?? 0) + (r?.height ?? 0)).toBeLessThanOrEqual(tile?.y ?? 0);

  // Note always starts a fresh note; left empty, the draft is untouched
  await page.getByRole("button", { name: "Note" }).click();
  await expect(text).toHaveValue("");
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(resume).toBeVisible();

  // The row resumes it
  await resume.click();
  await expect(text).toHaveValue("Numbat drafts\nsecond line");
  await page.goBack();
  await expect(resume).toBeVisible();

  // A fresh note left by Back takes the draft's place; Undo puts the older one back
  await page.getByRole("button", { name: "Note" }).click();
  await text.fill("Bandicoot newer");
  await page.goBack();
  await expect(row.getByRole("button", { name: "Draft: Bandicoot newer" })).toBeVisible();
  const toast = page.locator(".toast", { hasText: "in place of the older one" });
  await toast.getByRole("button", { name: "Undo" }).click();
  await expect(resume).toBeVisible();

  // A fresh note is kept as typed, under a key of its own: an app killed mid-capture (no
  // Back) finds it on the next open, in the older draft's place, with Undo
  await page.getByRole("button", { name: "Note" }).click();
  await text.fill("Quokka killed");
  await page.waitForTimeout(800); // the draft is kept a moment after typing
  await page.reload(); // as if the app was killed
  await expect(row.getByRole("button", { name: "Draft: Quokka killed" })).toBeVisible();
  await page
    .locator(".toast", { hasText: "Recovered your unsaved capture, in place of the older draft" })
    .getByRole("button", { name: "Undo" })
    .click();
  await expect(resume).toBeVisible();
  // Saved, a fresh note leaves the kept draft as it was, and nothing to recover
  await page.getByRole("button", { name: "Note" }).click();
  await text.fill("Quokka saved");
  await page.waitForTimeout(800);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".editor")).toBeHidden();
  await page.reload();
  await expect(resume).toBeVisible();
  await expect(page.locator(".toast", { hasText: "Recovered" })).toHaveCount(0);

  // ✕ discards it, with Undo
  await row.getByRole("button", { name: "Discard draft" }).click();
  await expect(row).toBeHidden();
  await page
    .locator(".toast", { hasText: "Draft discarded" })
    .getByRole("button", { name: "Undo" })
    .click();
  await expect(resume).toBeVisible();
  await row.getByRole("button", { name: "Discard draft" }).click();
  await expect(row).toBeHidden();
  await page.reload();
  await expect(page.getByRole("button", { name: "Camera" })).toBeVisible();
  await expect(row).toBeHidden(); // gone for good
});

test("Capture offline: the badge, the waiting row and one quiet line; no card or toast", async ({
  page,
  context,
}) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Camera" })).toBeVisible();
  await context.setOffline(true);
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill("Quiet offline note");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".editor")).toBeHidden();
  await expect(page.locator("#queue")).toHaveText("1 waiting");
  await expect(page.getByText("waiting to upload (offline)")).toBeVisible();
  await expect(page.locator(".strip .offline")).toHaveText("Offline: showing what's on this phone");
  await expect(page.locator(".capture .empty")).toHaveCount(0); // no problem card
  await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0);
  await expect(page.locator(".toast")).toHaveCount(0); // the waiting row says it
  // Online again: it uploads, and Latest draws itself, no Retry needed
  await context.setOffline(false);
  await expect(page.locator("#queue")).toBeHidden({ timeout: 15_000 });
  await expect(page.locator(".strip .offline")).toHaveCount(0);
  await expect(page.locator(".capture .list a", { hasText: "Quiet offline note" })).toBeVisible();
});

test("a search row drops a snippet that only says its title again", async ({ page }) => {
  const tag = ulid().slice(-6).toLowerCase();
  await make(page, `Wombat echo ${tag}`); // its text is its title
  await make(page, `Wombat more ${tag}\nthe burrow runs under the fence by the gate`);
  await page.goto(`/search?q=${encodeURIComponent(`wombat ${tag}`)}`);
  const hit = (title: string) => page.locator(".hits li", { hasText: title });
  await expect(hit(`Wombat echo ${tag}`)).toBeVisible();
  await expect(hit(`Wombat echo ${tag}`).locator(".snip")).toHaveCount(0);
  await expect(hit(`Wombat more ${tag}`).locator(".snip")).toBeVisible();
  // Open notes and todos have no chip: their icon says the kind
  await expect(hit(`Wombat echo ${tag}`).locator("em")).toHaveCount(0);
});

test("a draft storage refuses is said, and Back keeps the editor open rather than lose it", async ({
  page,
}) => {
  // IndexedDB refusing a draft (full, say): puts to the drafts store throw once the flag is set
  await page.addInitScript(() => {
    const put = IDBObjectStore.prototype.put;
    IDBObjectStore.prototype.put = function (this: IDBObjectStore, ...a: [unknown, IDBValidKey?]) {
      if (this.name === "drafts" && (window as { refuse?: boolean }).refuse)
        throw new DOMException("full", "QuotaExceededError");
      return put.apply(this, a);
    };
  });
  await page.goto("/");
  const text = page.getByPlaceholder("Note or link");
  await page.getByRole("button", { name: "Note" }).click();
  await text.fill("Quoll early text");
  await page.waitForTimeout(800); // kept: an older save
  await page.evaluate(() => ((window as { refuse?: boolean }).refuse = true));
  await text.fill("Quoll early text and much more");
  const refused = page.locator(".toast", { hasText: "Couldn't keep a draft" });
  await expect(refused).toBeVisible(); // said as it is typed, once

  // Back would leave only the older save: it stays, the text with it
  await page.evaluate(() => {
    for (const t of document.querySelectorAll(".toast")) t.remove();
  });
  await page.goBack();
  await expect(page.locator(".editor")).toBeVisible();
  await expect(text).toHaveValue("Quoll early text and much more");
  await expect(refused).toBeVisible();

  // Storage works again: Back keeps the draft as typed
  await page.evaluate(() => ((window as { refuse?: boolean }).refuse = false));
  await page.goBack();
  await expect(page.locator(".editor")).toBeHidden();
  await expect(page.locator(".toast")).toContainText("Kept as a draft");
  await expect(
    page
      .locator(".capture .draft")
      .getByRole("button", { name: /Draft: Quoll early text and much more/ }),
  ).toBeVisible();
  await page.locator(".capture .draft").getByRole("button", { name: "Discard draft" }).click();
});

test("a capture whose first line is indented code keeps its # in the title", async ({ page }) => {
  const word = `indented${Date.now()}`; // unique: the data lasts across repeats
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill(`    # ${word}\nsecond line`);
  await page.getByRole("button", { name: "Save" }).click();
  await expect
    .poll(async () => {
      const hits = await (await page.request.get(`/api/search?q=${word}`)).json();
      return hits.map((h: { title: string }) => h.title);
    })
    .toEqual([`# ${word}`]);
  const [hit] = await (await page.request.get(`/api/search?q=${word}`)).json();
  const body = (await (await page.request.get(`/api/pages/${hit.id}`)).json()).body;
  expect(body).toBe(`    # ${word}\nsecond line`);
});

test("search results follow the queue: a capture that uploads later appears", async ({ page }) => {
  const word = `quokka${Date.now()}`;
  let release: () => void = () => {};
  const gate = new Promise<void>((ok) => (release = ok));
  await page.route("**/api/captures", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await gate; // the upload waits: the capture is queued
    return route.continue();
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill(`${word} refresh note`);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator("#queue")).toHaveText("1 waiting");
  await page.getByRole("link", { name: "Search", exact: true }).click();
  const box = page.getByRole("searchbox");
  await box.fill(word);
  await expect(page.getByText("No matches")).toBeVisible(); // not uploaded yet
  release();
  await expect(page.locator(".hits a", { hasText: `${word} refresh note` })).toBeVisible();
  await expect(box).toHaveValue(word); // typing untouched
});

test("search results stay when the queue changes offline", async ({ page, context }) => {
  const word = `numbat${Date.now()}`;
  await make(page, `${word} stays`);
  await page.goto(`/search?q=${word}`);
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();
  const hit = page.locator(".hits a", { hasText: `${word} stays` });
  await expect(hit).toBeVisible();
  await context.setOffline(true);
  // What a capture queued offline does (main.ts, showQueue): the queue changed
  await page.evaluate(() => document.dispatchEvent(new Event("queuechange")));
  await page.waitForTimeout(1500); // the refresh has had its turn
  await expect(hit).toBeVisible();
  await expect(page.getByText("Search needs the server.")).toHaveCount(0);
  await context.setOffline(false);
});

test("the draft is kept the moment the app is hidden, without waiting for the pause (#16)", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Note", exact: true }).click();
  const text = page.getByPlaceholder("Note or link");
  await text.fill("Wombat last words");
  // Hidden at once, well inside the 0.4 s pause
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const stored = () =>
    page.evaluate(
      () =>
        new Promise<string>((ok) => {
          const open = indexedDB.open("scrap");
          open.onsuccess = () => {
            const all = open.result.transaction("drafts").objectStore("drafts").getAll();
            all.onsuccess = () => ok(JSON.stringify(all.result));
          };
        }),
    );
  await expect.poll(stored, { timeout: 300 }).toContain("Wombat last words");
  page.once("dialog", (d) => d.accept());
  await page.locator(".editor").getByRole("button", { name: "Cancel" }).click();
});

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
// An iPhone's home-screen app (navigator.standalone): the only place the top bar has Back
const iphoneApp = (page: Page) =>
  page
    .context()
    .addInitScript(() => Object.defineProperty(navigator, "standalone", { value: true }));

test("elsewhere (Android, a browser) a page keeps the wordmark: no Back in the top bar", async ({
  page,
}) => {
  const note = await make(page, `No arrow ${ulid().slice(-6)}`);
  await page.goto(`/p/${note.slug}`);
  await expect(page.locator(".page h1")).toBeVisible();
  await expect(back(page)).toBeHidden();
  await expect(page.locator("header .logo")).toBeVisible();
  await expect(page.locator("nav")).toBeHidden(); // still: the page's toolbar is the bottom bar
});

test("Back on a page opened cold goes to its parent; from a list, back to it", async ({ page }) => {
  await iphoneApp(page);
  const tag = ulid().slice(-6);
  const todo = await make(page, `Back todo ${tag}`, "todo");
  const note = await make(page, `Back note ${tag}`);

  // A todo opened from a link: Back is the Todos screen, in place of the page
  await page.goto(`/p/${todo.slug}`);
  await expect(page.locator(".page h1")).toHaveText(`Back todo ${tag}`);
  await expect(back(page)).toBeVisible();
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
  await back(page).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("button", { name: "Camera" })).toBeVisible();

  // Tags: titled in the top bar, its parent Search
  await page.goto("/tags");
  await expect(page.locator("header #where")).toHaveText("Tags");
  await back(page).click();
  await expect(page).toHaveURL(/\/search$/);

  // Opened from a list: Back is history's, the list as it was (Forward still has the page)
  await page.goto(`/search?q=${tag}`);
  await page.locator(".hits a", { hasText: `Back note ${tag}` }).click();
  await expect(page).toHaveURL(`/p/${note.slug}`);
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
  const boxes = await Promise.all((await keys.all()).map((k) => k.boundingBox()));
  for (const b of boxes) {
    expect(b).not.toBeNull();
    expect(b?.x ?? -1).toBeGreaterThanOrEqual(0);
    expect((b?.x ?? 0) + (b?.width ?? 0)).toBeLessThanOrEqual(320);
    expect(b?.y).toBe(boxes[0]?.y); // one line
    expect(b?.height ?? 0).toBeGreaterThanOrEqual(44);
  }
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

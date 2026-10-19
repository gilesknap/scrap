import { readFileSync, writeFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";

test("capture a note, find it, and capture offline", async ({ page, context }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill("Buy oat milk\nfrom the corner shop");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator("#queue")).toBeHidden();

  await page.getByRole("link", { name: "Recent", exact: true }).click();
  await expect(page.getByText("Buy oat milk")).toBeVisible();

  await page.getByRole("link", { name: "Search", exact: true }).click();
  await page.getByRole("searchbox").fill("corner sho");
  await expect(page.locator(".hits mark")).toHaveText(["corner", "shop"]);
  await page.locator(".hits a").first().click();
  await expect(page.getByRole("heading", { name: "Buy oat milk" })).toBeVisible();
  const note = await (await page.request.get(page.url().replace("/p/", "/api/pages/"))).json();
  expect(note.body).toBe("Buy oat milk\nfrom the corner shop"); // LF, not CRLF

  // Offline: the app still opens from the service worker and queues the capture.
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();
  await context.setOffline(true);
  await page.goto("/");
  await page.getByRole("button", { name: "Todo" }).click();
  await page.getByPlaceholder("Note or link").fill("Ring the plumber");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator("#queue")).toHaveText("1 waiting");
  await page.reload(); // the queue survives a reload
  await expect(page.locator("#queue")).toHaveText("1 waiting");

  await context.setOffline(false);
  await expect(page.locator("#queue")).toBeHidden();
  const pages = await (await page.request.get("/api/pages")).json();
  expect(pages.map((p: { title: string; kind: string }) => [p.title, p.kind])).toEqual([
    ["Ring the plumber", "todo"],
    ["Buy oat milk", "note"],
  ]);
});

test("the share target queues a share in the service worker", async ({ page, context }) => {
  await page.goto("/");
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();
  await context.setOffline(true); // so only the service worker can take it
  // What Android's share sheet does: a multipart POST navigation to the share_target action.
  await page.evaluate(() => {
    const form = Object.assign(document.createElement("form"), {
      method: "POST",
      action: "/share",
      enctype: "multipart/form-data",
    });
    for (const [name, value] of [
      ["title", "A story"],
      ["text", "A story https://example.com/s"],
    ]) {
      form.append(Object.assign(document.createElement("input"), { name, value }));
    }
    document.body.append(form);
    form.submit();
  });
  await expect(page.getByText("Shared item saved")).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator("#queue")).toHaveText("1 waiting");
  await context.setOffline(false);
  await expect(page.locator("#queue")).toBeHidden();
  const [hit] = await (await page.request.get("/api/search?q=story")).json();
  const shared = await (await page.request.get(`/api/pages/${hit.slug}`)).json();
  expect(shared.captures[0]).toMatchObject({
    source: "share",
    url: "https://example.com/s",
    text: "A story",
  });
});

test("a new build offers to reload", async ({ page }) => {
  const sw = new URL("../../src/scrap/static/sw.js", import.meta.url);
  const code = readFileSync(sw, "utf8");
  await page.goto("/");
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload(); // now controlled by the service worker
  try {
    writeFileSync(sw, code.replace("scrap-", "scrap-next-")); // what a new deploy looks like
    await page.evaluate(async () => (await navigator.serviceWorker.getRegistration())?.update());
    await page.getByRole("button", { name: "Reload" }).click();
    await page.waitForEvent("load");
    const caches = await page.evaluate(() => window.caches.keys());
    expect(caches).toHaveLength(1);
    expect(caches[0]).toMatch(/^scrap-next-/); // the old build's cache is gone
  } finally {
    writeFileSync(sw, code);
  }
});

const photo = (mb: number) => ({
  name: "big.png",
  mimeType: "image/png",
  buffer: Buffer.alloc(mb * 2 ** 20, 1),
});

async function pick(page: Page, mb: number, caption: string) {
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByText("Gallery").click(),
  ]);
  await chooser.setFiles(photo(mb));
  await page.getByPlaceholder("Caption (optional)").fill(caption);
  await page.getByRole("button", { name: "Save" }).click();
}

test("a refused capture says why and can be discarded", async ({ page }) => {
  await page.route("**/healthz", (r) => r.abort()); // limit unknown: no check before saving
  await page.goto("/");
  await pick(page, 2, "too big");
  await expect(page.locator("#queue")).toHaveText("1 failed");
  await expect(page.getByText("not saved: too large: over the 1 MB upload limit")).toBeVisible();
  await page.getByRole("button", { name: "Retry" }).click(); // still too large
  await expect(page.locator("#queue")).toHaveText("1 failed");
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Discard" }).click();
  await expect(page.locator("#queue")).toBeHidden();
  expect(
    await page.evaluate(
      () =>
        new Promise((ok) => {
          indexedDB.open("scrap").onsuccess = (e) => {
            const db = (e.target as IDBOpenDBRequest).result;
            db.transaction("queue").objectStore("queue").count().onsuccess = (c) =>
              ok((c.target as IDBRequest).result);
          };
        }),
    ),
  ).toBe(0);
});

test("a capture the phone cannot store stays in the composer", async ({
  page,
  context,
  baseURL,
}) => {
  await page.route("**/healthz", (r) => r.abort()); // limit unknown: no check before saving
  await page.goto("/");
  const cdp = await context.newCDPSession(page);
  await cdp.send("Storage.overrideQuotaForOrigin", {
    origin: baseURL as string,
    quotaSize: 2 ** 20,
  });
  await pick(page, 3, "my caption");
  await expect(page.getByText(/Not saved: the phone refused to store it/)).toBeVisible();
  await expect(page.getByPlaceholder("Caption (optional)")).toHaveValue("my caption");
  await expect(page.locator(".thumbs img")).toHaveCount(1);
});

test("a share the phone cannot store goes to the server, or says so", async ({
  page,
  context,
  baseURL,
}) => {
  await page.goto("/");
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Storage.overrideQuotaForOrigin", { origin: baseURL as string, quotaSize: 1 });
  const share = (text: string) =>
    page.evaluate((text) => {
      const form = Object.assign(document.createElement("form"), {
        method: "POST",
        action: "/share",
        enctype: "multipart/form-data",
      });
      form.append(Object.assign(document.createElement("input"), { name: "text", value: text }));
      document.body.append(form);
      form.submit();
    }, text);
  await share("quota fallback note");
  await expect(page).toHaveURL(/\/$/);
  const [hit] = await (await page.request.get("/api/search?q=quota+fallback")).json();
  expect(hit.title).toBe("quota fallback note");
  await context.setOffline(true);
  await share("nowhere to go");
  await expect(
    page.getByText("Not saved: the phone refused to store the share", { exact: false }),
  ).toBeVisible();
});

test("search text can be edited with Backspace", async ({ page }) => {
  await page.goto("/search");
  const box = page.getByRole("searchbox");
  await box.pressSequentially("milkx");
  await box.press("Backspace");
  await expect(box).toHaveValue("milk");
  await box.press("ArrowLeft");
  await box.press("Delete");
  await expect(box).toHaveValue("mil");
});

test("several photos make one capture", async ({ page }) => {
  const png = (name: string, byte: number) => ({
    name,
    mimeType: "image/png",
    buffer: Buffer.alloc(1000, byte),
  });
  await page.goto("/");
  const [gallery] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByText("Gallery").click(),
  ]);
  expect(gallery.isMultiple()).toBe(true);
  await gallery.setFiles([png("a.png", 1), png("b.png", 2), png("c.png", 3)]);
  await page.getByRole("button", { name: "Remove photo 2" }).click();
  const [camera] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByText("+ Camera").click(),
  ]);
  expect(camera.isMultiple()).toBe(false);
  await camera.setFiles(png("d.png", 4));
  await expect(page.locator(".thumb img")).toHaveCount(3);
  // The composer's camera is a real camera input, separate from the gallery picker.
  const cam = camera.element();
  const gal = gallery.element();
  expect(await cam.getAttribute("capture")).toBe("environment");
  expect(await gal.getAttribute("capture")).toBeNull();
  expect(await cam.evaluate((i: HTMLInputElement) => i.value)).toBe(""); // reset for a re-shot
  await expect(page.getByRole("button", { name: "+ Camera" })).toBeVisible(); // Tab/TalkBack
  await expect(page.getByRole("button", { name: "+ Gallery" })).toBeVisible();
  const [again] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByText("+ Camera").click(),
  ]);
  await again.setFiles(png("d.png", 4)); // a second shot appends
  await expect(page.locator(".thumb img")).toHaveCount(4);
  await page.getByPlaceholder("Caption (optional)").fill("three photos");
  await page.getByRole("button", { name: "Save" }).click();
  const search = async () => (await page.request.get("/api/search?q=three+photos")).json();
  await expect.poll(search).toHaveLength(1); // uploaded
  const [hit] = await search();
  const saved = await (await page.request.get(`/api/pages/${hit.slug}`)).json();
  expect(saved.captures).toHaveLength(1);
  expect(saved.captures[0].blobs.map((b: { filename: string }) => b.filename)).toEqual([
    "a.png",
    "c.png",
    "d.png",
    "d.png",
  ]);
});

test("photos over the upload limit are saved separately, or split after a 413", async ({
  page,
}) => {
  const png = (name: string) => ({
    name,
    mimeType: "image/png",
    buffer: Buffer.alloc(700 * 1024, 7),
  });
  const pages = async () => (await page.request.get("/api/search?q=limit+test")).json();
  await page.goto("/");
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("scrap.max_upload_bytes")))
    .toBe(String(2 ** 20));
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByText("Gallery").click(),
  ]);
  await chooser.setFiles([png("one.png"), png("two.png")]);
  await page.getByPlaceholder("Caption (optional)").fill("limit test");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("1.4 MB of photos is over the server's 1.0 MB limit")).toBeVisible();
  await expect(page.locator(".thumb img")).toHaveCount(2); // nothing lost
  await page.getByRole("button", { name: "Save separately" }).click();
  await expect.poll(async () => (await pages()).length).toBe(1); // the text goes with the first
  await expect
    .poll(
      async () =>
        (await (await page.request.get("/api/pages")).json()).filter(
          (p: { thumb: string | null }) => p.thumb,
        ).length,
    )
    .toBeGreaterThanOrEqual(2);

  // Queued before the limit was known (an old client): the server's 413 can be split.
  await page.evaluate(() => localStorage.removeItem("scrap.max_upload_bytes"));
  await page.route("**/healthz", (r) => r.abort());
  const [again] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByText("Gallery").click(),
  ]);
  await again.setFiles([png("three.png"), png("four.png")]);
  await page.getByPlaceholder("Caption (optional)").fill("split after refusal");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator("#queue")).toHaveText("1 failed");
  await page.getByRole("button", { name: "Split and retry" }).click();
  await expect(page.locator("#queue")).toBeHidden();
  const [hit] = await (await page.request.get("/api/search?q=split+after")).json();
  const first = await (await page.request.get(`/api/pages/${hit.slug}`)).json();
  expect(first.captures[0].blobs.map((b: { filename: string }) => b.filename)).toEqual([
    "three.png",
  ]);
});

test("a missing page says so", async ({ page }) => {
  await page.goto("/p/no-such-page");
  await expect(page.getByText("Not found: it may have been deleted.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to capture" })).toBeVisible();
});

import { readFileSync, writeFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";
import { caption } from "./panel";

// The top bar's Back shows only in an iPhone's home-screen app (navigator.standalone), which
// has no Back of its own; tests here use it, so they run as one
test.beforeEach(({ context }) =>
  context.addInitScript(() => Object.defineProperty(navigator, "standalone", { value: true })),
);

test("capture a note, find it, and capture offline", async ({ page, context }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill("Buy oat milk\nfrom the corner shop");
  await page.getByRole("button", { name: "Save" }).click();
  // Straight to Search, whether or not the upload has landed: its results follow the queue
  await page.getByRole("link", { name: "Search", exact: true }).click();
  await expect(page.getByText("Buy oat milk")).toBeVisible(); // newest first
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
  await page.getByRole("button", { name: "Note" }).click(); // the composer, kept offline
  await page.locator(".kinds").getByText("Todo").click();
  await page.getByPlaceholder("What needs doing?").fill("Ring the plumber");
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

async function pick(page: Page, mb: number, text: string) {
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByText("Gallery").click(),
  ]);
  await chooser.setFiles(photo(mb));
  await caption(page, text);
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
  await expect(page.locator(".editor textarea")).toHaveValue("my caption\n\n⟦image 1⟧\n\n");
  await expect(page.locator(".editor .embeds img")).toHaveCount(1);
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
  await page.getByRole("button", { name: "Remove image 2" }).click();
  const [camera] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.locator(".editor").getByRole("button", { name: "Camera" }).click(),
  ]);
  expect(camera.isMultiple()).toBe(false);
  await camera.setFiles(png("d.png", 4));
  await expect(page.locator(".editor .embeds img")).toHaveCount(3);
  // The composer's camera is a real camera input, separate from the gallery picker.
  const cam = camera.element();
  const gal = gallery.element();
  expect(await cam.getAttribute("capture")).toBe("environment");
  expect(await gal.getAttribute("capture")).toBeNull();
  expect(await cam.evaluate((i: HTMLInputElement) => i.value)).toBe(""); // reset for a re-shot
  const editor = page.locator(".editor");
  await expect(editor.getByRole("button", { name: "Camera" })).toBeVisible(); // Tab/TalkBack
  await expect(editor.getByRole("button", { name: "Gallery" })).toBeVisible();
  const [again] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.locator(".editor").getByRole("button", { name: "Camera" }).click(),
  ]);
  await again.setFiles(png("d.png", 4)); // a second shot, after the first
  await expect(page.locator(".editor .embeds img")).toHaveCount(4);
  await caption(page, "three photos");
  await page.getByRole("button", { name: "Save" }).click();
  const search = async () => (await page.request.get("/api/search?q=three+photos")).json();
  await expect.poll(search).toHaveLength(1); // uploaded
  const [hit] = await search();
  const saved = await (await page.request.get(`/api/pages/${hit.slug}`)).json();
  expect(saved.captures).toHaveLength(1);
  // In the text's order (#403): the shots went where the caret was, where photo 2 had been
  expect(saved.captures[0].blobs.map((b: { filename: string }) => b.filename)).toEqual([
    "a.png",
    "d.png",
    "d.png",
    "c.png",
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
  await caption(page, "limit test");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("1.4 MB of files is over the server's 1.0 MB limit")).toBeVisible();
  await expect(page.locator(".editor .embeds img")).toHaveCount(2); // nothing lost
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
  await caption(page, "split after refusal");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator("#queue")).toHaveText("1 failed");
  await page.getByRole("button", { name: "Split and retry" }).click();
  await expect(page.locator("#queue")).toBeHidden();
  const [hit] = await (await page.request.get("/api/search?q=split+after")).json();
  const first = await (await page.request.get(`/api/pages/${hit.slug}`)).json();
  expect(first.captures[0].blobs.map((b: { filename: string }) => b.filename)).toEqual([
    "three.png",
  ]);
  // Its text with its own photo where its token was, and no stray token for the other (#403)
  expect(first.body).toMatch(
    /^split after refusal\n\n!\[\]\(\/api\/blobs\/[0-9a-f]{64}\/preview\?size=2048\)$/,
  );
});

test("a missing page says so", async ({ page }) => {
  await page.goto("/p/no-such-page");
  await expect(page.getByText("Not found: it may have been deleted.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to capture" })).toBeVisible();
});

test("a slow upload finishes; a stalled one is dropped and retried", async ({ page, context }) => {
  test.setTimeout(90_000);
  await page.addInitScript(() => localStorage.setItem("scrap.stall_ms", "3000"));
  await page.goto("/");
  const cdp = await context.newCDPSession(page);
  const upload = (bytesPerSecond: number) =>
    cdp.send("Network.emulateNetworkConditions", {
      offline: false,
      latency: 0,
      downloadThroughput: -1,
      uploadThroughput: bytesPerSecond,
    });
  const save = async (text: string) => {
    const [chooser] = await Promise.all([
      page.waitForEvent("filechooser"),
      page.getByText("Gallery").click(),
    ]);
    await chooser.setFiles({
      name: `${text}.png`,
      mimeType: "image/png",
      buffer: Buffer.alloc(600 * 1024, 5),
    });
    await caption(page, text);
    await page.getByRole("button", { name: "Save", exact: true }).click();
  };
  const found = async (q: string) =>
    (await (await page.request.get(`/api/search?q=${q}`)).json()).length;

  await upload(64 * 1024); // about 10 s for 600 KB: far past the 3 s stall limit, but moving
  await save("slowpoke");
  await expect.poll(() => found("slowpoke"), { timeout: 30_000 }).toBe(1);
  await expect(page.locator("#queue")).toBeHidden();

  await upload(1); // nothing moves
  await save("stuck");
  await expect(page.getByText("waiting to upload (timed out)")).toBeVisible({ timeout: 15_000 });
  await upload(-1);
  await expect.poll(() => found("stuck"), { timeout: 30_000 }).toBe(1);
});

test("a slow view says Loading at once, and a newer tap wins", async ({ page }) => {
  const made = await page.request.post("/api/captures", {
    data: {
      id: `01${Array.from({ length: 24 }, () => "ABCDEFGHJKMNPQRS"[Math.floor(Math.random() * 16)]).join("")}`,
      text: "Slow view",
    },
  });
  const { slug } = await made.json();
  await page.goto("/");
  await expect(page.locator(".capture")).toBeVisible();
  let hold = true;
  let aborted = false;
  page.on("requestfailed", (r) => {
    if (r.url().endsWith(`/api/pages/${slug}`)) aborted = true;
  });
  await page.route(`**/api/pages/${slug}`, async (r) => {
    while (hold) await new Promise((ok) => setTimeout(ok, 100));
    await r.continue();
  });
  await page
    .locator(".capture")
    .getByRole("link", { name: /Slow view/ })
    .click();
  await expect(page.getByRole("status")).toHaveText("Loading…", { timeout: 3000 });
  await expect(page.locator(".capture")).toHaveCount(0); // not the old view, as if stuck
  await page.locator("#back").click(); // a page has no nav: the top bar's Back
  await expect(page.locator(".capture")).toBeVisible();
  await expect.poll(() => aborted).toBe(true); // the superseded request is given up, not left open
  hold = false; // had its answer come late, it must not cover Capture
  await expect(page.locator(".capture")).toBeVisible();
  await expect(page.locator("#view > .page")).toHaveCount(0);
  await expect(page.getByText("Loading…")).toHaveCount(0);
});

test("opening the app while another tab holds the upload lock: sent once it is free", async ({
  page,
  context,
}) => {
  await page.goto("/");
  let refuse = true; // for both tabs
  await context.route("**/api/captures", (r) => (refuse ? r.abort() : r.continue()));
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill("Sent after the lock");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("waiting to upload (connection lost)")).toBeVisible();
  // Another tab takes the lock and never lets go (as if it died mid-upload, until closed)
  const other = await context.newPage();
  await other.goto("/");
  await expect(other.locator("#queue")).toBeVisible(); // its own try on open is over
  await other.evaluate(() => {
    void navigator.locks.request("scrap-queue", () => new Promise(() => {}));
  });
  await other.waitForFunction(async () => (await navigator.locks.query()).held?.length === 1);
  refuse = false;
  const posts: string[] = [];
  page.on("request", (r) => r.url().endsWith("/api/captures") && posts.push(r.method()));
  await page.reload(); // no timer left from before: only the nudge on open
  await expect(page.getByText("waiting to upload (connection lost)")).toBeVisible();
  await page.waitForLoadState("networkidle"); // the app has opened and its nudge has had its turn
  expect(posts).toEqual([]); // it did not try, the other tab holds the lock
  await expect(page.locator("#queue")).toBeVisible(); // not on top of the other tab's upload
  await other.close(); // its lock comes free
  await expect(page.locator("#queue")).toBeHidden({ timeout: 10_000 });
  const pages = await (await page.request.get("/api/pages")).json();
  expect(pages.map((p: { title: string }) => p.title)).toContain("Sent after the lock");
  await context.unroute("**/api/captures");
});

test("opening the app sends what waits now, not when its backoff says", async ({ page }) => {
  await page.goto("/");
  let refuse = true;
  await page.route("**/api/captures", (r) => (refuse ? r.abort() : r.continue()));
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill("Sent on open");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("waiting to upload (connection lost)")).toBeVisible();
  // As after many failures: the next timed try is far off
  await page.evaluate(
    () =>
      new Promise((ok) => {
        indexedDB.open("scrap").onsuccess = (e) => {
          const store = (e.target as IDBOpenDBRequest).result
            .transaction("queue", "readwrite")
            .objectStore("queue");
          store.getAll().onsuccess = (g) => {
            for (const i of (g.target as IDBRequest).result)
              store.put({ ...i, next: Date.now() + 10 * 60_000 });
            store.transaction.oncomplete = ok;
          };
        };
      }),
  );
  refuse = false;
  await page.reload();
  await expect(page.locator("#queue")).toBeHidden({ timeout: 10_000 });
  const pages = await (await page.request.get("/api/pages")).json();
  expect(pages.map((p: { title: string }) => p.title)).toContain("Sent on open");
});

test("the title bar shows the server's version", async ({ page }) => {
  const { version } = await (await page.request.get("/healthz")).json();
  await page.goto("/");
  await expect(page.locator("#ver")).toHaveText(`v${String(version).split("+")[0]}`);
});

test("a view the server never answers ends in an error with Retry", async ({ page }) => {
  const made = await page.request.post("/api/captures", {
    data: { id: `01${"ABCDEFGHJKMNPQRS".repeat(2).slice(0, 24)}`, text: "Never answered" },
  });
  const { slug } = await made.json();
  await page.clock.install();
  await page.goto("/");
  await expect(page.locator(".capture")).toBeVisible();
  let hold = true;
  await page.route(`**/api/pages/${slug}`, (r) => (hold ? new Promise(() => {}) : r.continue()));
  await page.goto(`/p/${slug}`);
  await page.clock.runFor(31_000);
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  hold = false;
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.locator(".page h1")).toBeVisible();
});

test.describe("without the service worker", () => {
  test.use({ serviceWorkers: "block" }); // it would answer from its cache

  test("Back in the top bar still goes up when its chunk will not load", async ({ page }) => {
    // A todo: its Back goes to Todos, so landing on Capture shows the fallback ran
    const made = await page.request.post("/api/captures", {
      data: { id: "01E2EBACKCHNK".padEnd(26, "0"), text: "Back chunk todo", kind: "todo" },
    });
    expect(made.ok()).toBe(true);
    const { slug } = await made.json();
    await page.route("**/assets/back-*.js", (r) => r.abort());
    await page.goto(`/p/${slug}`); // opened directly: nothing of the app's behind it
    await expect(page.locator("#backto")).toHaveText("Todos");
    await page.locator("#back").click();
    await expect(page).toHaveURL("/");
  });
});

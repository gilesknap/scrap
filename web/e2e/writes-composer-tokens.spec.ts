// The composer's photos and files as tokens in its text, with the page editor's chip row
// (#403): each picked file is a token where the caret is (⟦image 1⟧, ⟦file 1: minutes.pdf⟧) and a
// chip; the server puts each one's embed or link where its token is. Drafts, the offline queue
// and an older build's draft (files, no tokens) keep them paired.
import { execFileSync } from "node:child_process";
import { expect, type FileChooser, type Page, test } from "@playwright/test";

// A real 1x1 PNG (the server makes its preview)
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);
const photo = (name: string) => ({ name, mimeType: "image/png", buffer: PNG });

/** A real one-page PDF with text. */
function pdf(name: string, text: string) {
  const stream = `BT /F1 24 Tf 72 720 Td (${text}) Tj ET`;
  const objs = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>",
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
  ];
  let out = "%PDF-1.4\n";
  const at: number[] = [];
  objs.forEach((o, i) => {
    at.push(out.length);
    out += `${i + 1} 0 obj\n${o}\nendobj\n`;
  });
  const xref = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
  out += at.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("");
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return { name, mimeType: "application/pdf", buffer: Buffer.from(out) };
}
const MD = { name: "reading.md", mimeType: "", buffer: Buffer.from("# Reading\nthe wombat") };
const TXT = { name: "list.txt", mimeType: "text/plain", buffer: Buffer.from("eggs\nmilk") };

type Saved = {
  id: string;
  slug: string;
  title: string;
  kind: string;
  body: string;
  captures: { kind: string; blobs: { filename: string; sha256: string }[] }[];
};
const read = async (page: Page, id: string) =>
  (await (await page.request.get(`/api/pages/${id}`)).json()) as Saved;

/** Pick files with one of the composer's (or Capture's) Camera, Gallery and File. */
async function pick(
  page: Page,
  scope: string,
  label: string,
  files: Parameters<FileChooser["setFiles"]>[0],
) {
  const chooser = page.waitForEvent("filechooser");
  await page.locator(scope).getByRole("button", { name: label, exact: true }).click();
  await (await chooser).setFiles(files);
}
const BAR = ".editor .fields > .bar";
const id = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};
const box = (page: Page) => page.locator(".editor textarea");
const chips = (page: Page) => page.locator(".editor .embeds .embed");

/** Save the composer; the new page's id, from the capture's reply. */
async function save(page: Page) {
  const made = page.waitForResponse(
    (r) => r.url().endsWith("/api/captures") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Save", exact: true }).click();
  return ((await (await made).json()) as { page_id: string }).page_id;
}

test("photos and files are tokens where the caret is, with a chip each; the page has them in place", async ({
  page,
}) => {
  const word = `numbat${Date.now()}`;
  await page.goto("/");
  await pick(page, ".actions", "Gallery", [photo("a.png")]);
  await expect(box(page)).toHaveValue("⟦image 1⟧\n\n");
  await expect(page.getByPlaceholder("Caption (optional)")).toHaveCount(0);
  await expect(page.getByRole("radio", { name: "Note" })).toBeChecked(); // the kind, with photos too
  // Typed after it, then a PDF and a .md at the start, a .txt at the end
  await box(page).focus();
  await page.keyboard.type("Site visit");
  await box(page).evaluate((t: HTMLTextAreaElement) => t.setSelectionRange(0, 0));
  await pick(page, BAR, "File", [pdf("minutes.pdf", `${word} clause`), MD]);
  await box(page).evaluate((t: HTMLTextAreaElement) =>
    t.setSelectionRange(t.value.length, t.value.length),
  );
  await pick(page, BAR, "File", [TXT]);
  await expect(box(page)).toHaveValue(
    "⟦file 1: minutes.pdf⟧\n\n⟦file 2: reading.md⟧\n\n⟦image 1⟧\n\nSite visit\n\n⟦file 3: list.txt⟧\n\n",
  );
  // The chips in the text's order: a thumbnail for the photo, the file icon and name for a file
  await expect(chips(page)).toHaveText(["minutes.pdf", "reading.md", "Image 1", "list.txt"]);
  await expect(chips(page).locator("img")).toHaveCount(1);
  // Taking a chip off takes its token (and its line) out; deleting a token takes its chip
  await page.getByRole("button", { name: "Remove file 2" }).click();
  await expect(box(page)).toHaveValue(
    "⟦file 1: minutes.pdf⟧\n\n\n⟦image 1⟧\n\nSite visit\n\n⟦file 3: list.txt⟧\n\n",
  );
  await box(page).evaluate((t: HTMLTextAreaElement) => {
    const i = t.value.indexOf("⟦file 3: list.txt⟧");
    t.focus();
    t.setSelectionRange(i, i + "⟦file 3: list.txt⟧".length);
  });
  await page.keyboard.press("Backspace");
  await expect(chips(page)).toHaveText(["minutes.pdf", "Image 1"]);
  // Camera: one shot at the caret
  await box(page).evaluate((t: HTMLTextAreaElement) => {
    const i = t.value.indexOf("Site visit") + "Site visit".length;
    t.setSelectionRange(i, i);
  });
  await pick(page, BAR, "Camera", photo("b.png"));
  await expect(chips(page)).toHaveText(["minutes.pdf", "Image 1", "Image 2"]);
  const id = await save(page);
  await expect(page.locator(".editor")).toBeHidden();

  // The server put each one's embed or link where its token was; what was taken out is not sent
  const saved = await read(page, id);
  const sha = Object.fromEntries(saved.captures[0].blobs.map((b) => [b.filename, b.sha256]));
  expect(Object.keys(sha).sort()).toEqual(["a.png", "b.png", "minutes.pdf"]);
  const img = (s: string) => `![](/api/blobs/${s}/preview?size=2048)`;
  expect(saved.body).toBe(
    `[minutes.pdf](/api/blobs/${sha["minutes.pdf"]})\n\n\n${img(sha["a.png"])}\n\nSite visit\n\n${img(sha["b.png"])}`,
  );
  expect(saved.title).toBe("Site visit");

  // The page: the PDF's row where its link is, not listed again below; the photos as figures
  await page.goto(`/p/${saved.slug}`);
  await expect(page.locator(".filerow")).toHaveCount(1);
  await expect(page.locator(".originals .filerow")).toHaveCount(0);
  await expect(page.locator("figure.orig img")).toHaveCount(2);
  // Its Edit shows the same tokens and chips
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByLabel("Body")).toHaveValue(
    "⟦file 1: minutes.pdf⟧\n\n\n⟦image 1⟧\n\nSite visit\n\n⟦image 2⟧",
  );
  await expect(chips(page)).toHaveText(["minutes.pdf", "Image 1", "Image 2"]);
  await page.getByRole("button", { name: "Cancel" }).click();

  // Search still finds the PDF's text (read as ever: the e2e server has ingest off)
  const data = process.env.SCRAP_E2E_DATA as string;
  const args = ["run", "--locked", "python", "web/e2e/readfiles.py", data, saved.id];
  expect(execFileSync("uv", args, { cwd: "..", encoding: "utf8" }).trim()).toBe("1");
  const hits = (await (await page.request.get(`/api/search?q=${word}`)).json()) as { id: string }[];
  expect(hits.map((h) => h.id)).toEqual([saved.id]);
});

test("a todo with a photo and a PDF: kind and Due with files, kept through a reload and offline", async ({
  page,
  context,
}) => {
  await page.goto("/");
  await page.waitForFunction(async () => {
    await navigator.serviceWorker.ready;
    return !!navigator.serviceWorker.controller;
  });
  await page.getByRole("button", { name: "Note" }).click();
  await page.locator(".kinds").getByText("Todo").click();
  await page.getByPlaceholder("What needs doing?").fill("Mend the gate");
  await pick(page, BAR, "File", [pdf("quote.pdf", "hinges")]);
  await pick(page, BAR, "Gallery", [photo("gate.png")]);
  // Due stays with files (#403)
  await expect(page.locator(".editor details.fold", { hasText: "Due" })).toBeVisible();
  await page.waitForTimeout(600); // the draft is kept 0.4 s after a change
  await page.reload(); // as if the app was killed
  await page.getByRole("button", { name: "Draft: Mend the gate · 1 photo, 1 file" }).click();
  await expect(box(page)).toHaveValue("Mend the gate\n\n⟦file 1: quote.pdf⟧\n\n⟦image 1⟧\n\n");
  await expect(chips(page)).toHaveText(["quote.pdf", "Image 1"]);
  await expect(page.getByRole("radio", { name: "Todo" })).toBeChecked();
  // Saved offline: the queue's row says it as the draft row did
  await context.setOffline(true);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".editor")).toBeHidden();
  const row = page.locator(".pending li");
  await expect(row.locator("strong")).toHaveText("Mend the gate · 1 photo, 1 file");
  await context.setOffline(false);
  await expect(page.locator("#queue")).toBeHidden({ timeout: 15_000 });
  const [hit] = await (await page.request.get("/api/search?q=mend+gate")).json();
  const saved = await read(page, hit.id);
  expect(saved.kind).toBe("todo");
  const sha = Object.fromEntries(saved.captures[0].blobs.map((b) => [b.filename, b.sha256]));
  expect(saved.body).toBe(
    `Mend the gate\n\n[quote.pdf](/api/blobs/${sha["quote.pdf"]})\n\n![](/api/blobs/${sha["gate.png"]}/preview?size=2048)`,
  );
  // To the trash: an open todo's Done tick on Capture would be one more "Done" for other specs
  await page.request.delete(`/api/pages/${saved.id}`);
});

test("an older build's draft (photos, no tokens) gets its tokens at the end of its text", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator(".actions")).toBeVisible();
  // As an older build kept it: a caption, and a photo and a PDF with no token in the text
  await page.evaluate(
    ([png, pdfText]) =>
      new Promise<void>((ok, fail) => {
        const open = indexedDB.open("scrap", 2);
        open.onsuccess = () => {
          const tx = open.result.transaction("drafts", "readwrite");
          const bytes = Uint8Array.from(atob(png), (c) => c.charCodeAt(0));
          tx.objectStore("drafts").put(
            {
              text: "Old caption",
              kind: "note",
              files: [
                new File([bytes], "old.png", { type: "image/png" }),
                new File([pdfText], "old.pdf", { type: "application/pdf" }),
              ],
              at: Date.now(),
            },
            "new",
          );
          tx.oncomplete = () => ok();
          tx.onerror = () => fail(tx.error);
        };
      }),
    [PNG.toString("base64"), pdf("old.pdf", "older").buffer.toString("latin1")],
  );
  await page.reload();
  await page.getByRole("button", { name: "Draft: Old caption · 1 photo, 1 file" }).click();
  await expect(box(page)).toHaveValue("Old caption\n\n⟦image 1⟧\n\n⟦file 1: old.pdf⟧\n\n");
  await expect(chips(page)).toHaveText(["Image 1", "old.pdf"]);
  const id = await save(page);
  const saved = await read(page, id);
  const sha = Object.fromEntries(saved.captures[0].blobs.map((b) => [b.filename, b.sha256]));
  expect(saved.body).toBe(
    `Old caption\n\n![](/api/blobs/${sha["old.png"]}/preview?size=2048)\n\n[old.pdf](/api/blobs/${sha["old.pdf"]})`,
  );
});

test("a token pasted from another page's Edit is plain text, not a place for a photo", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill("Pasted ⟦image 1⟧ here");
  await pick(page, BAR, "Gallery", [photo("p.png")]);
  await expect(box(page)).toHaveValue("Pasted ⟦image 1⟧ here\n\n⟦image 2⟧\n\n");
  await expect(chips(page)).toHaveText(["Image 2"]);
  const saved = await read(page, await save(page));
  const sha = saved.captures[0].blobs[0].sha256;
  expect(saved.body).toBe(`Pasted [image 1] here\n\n![](/api/blobs/${sha}/preview?size=2048)`);
});

test("a file linked mid-sentence keeps its row below the text; one alone on its line is its row there", async ({
  page,
}) => {
  const made = await page.request.post("/api/captures", {
    multipart: {
      id: id(),
      text: "See ⟦file 1⟧ for the terms.\n\n⟦file 2⟧",
      place: "1",
      file: pdf("terms.pdf", "terms"),
    },
  });
  // (one file part per request with this API: the second file is added to the page)
  expect(made.status()).toBe(201);
  const ref = (await made.json()) as { page_id: string; slug: string };
  const saved = await read(page, ref.page_id);
  const sha = saved.captures[0].blobs[0].sha256;
  expect(saved.body).toBe(`See [terms.pdf](/api/blobs/${sha}) for the terms.\n\n⟦file 2⟧`);
  await page.goto(`/p/${ref.slug}`);
  await expect(page.locator(`a[data-sha="${sha}"]`)).toHaveText("terms.pdf");
  await expect(page.locator(".originals .filerow")).toHaveCount(1); // its Download, its hint
  // Alone on its line: its row there instead, not below
  const body = `${saved.body.split("\n\n")[0]}\n\n[terms.pdf](/api/blobs/${sha})`;
  await page.request.patch(`/api/pages/${ref.page_id}`, { data: { base_rev: 1, body } });
  await page.reload();
  await expect(page.locator(".filerow")).toHaveCount(1);
  await expect(page.locator(".originals .filerow")).toHaveCount(0);
});

test("a chip whose preview fails keeps the file icon as the text changes", async ({ page }) => {
  const made = await page.request.post("/api/captures", {
    multipart: { id: id(), text: "Scan", file: pdf("scan.pdf", "x") },
  });
  const ref = (await made.json()) as { page_id: string; slug: string };
  const sha = (await read(page, ref.page_id)).captures[0].blobs[0].sha256;
  // An image embed of a PDF: the server draws no preview for it
  const body = `Scan\n\n![](/api/blobs/${sha}/preview?size=2048)`;
  await page.request.patch(`/api/pages/${ref.page_id}`, { data: { base_rev: 1, body } });
  await page.goto(`/p/${ref.slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(chips(page)).toHaveText(["Image 1"]);
  await expect(chips(page).locator("img")).toHaveCount(0); // the file icon
  await page.getByLabel("Body").press("End");
  await page.keyboard.type(" more");
  await expect(chips(page).locator("img")).toHaveCount(0); // still, not the broken image again
  await expect(chips(page).locator("svg")).toHaveCount(2); // its icon and its ✕
  page.once("dialog", (d) => d.accept()); // discard the change
  await page.getByRole("button", { name: "Cancel" }).click();
});

test("an image and a file link in one paragraph: the figure stays, the file is listed below", async ({
  page,
}) => {
  const made = await page.request.post("/api/captures", {
    multipart: { id: id(), text: "Mixed\n\n⟦image 1⟧\n⟦file 2⟧", place: "1", file: photo("m.png") },
  });
  const ref = (await made.json()) as { page_id: string; slug: string };
  // the PDF, added to the page; its link put beside the image by hand
  const saved = await read(page, ref.page_id);
  const img = saved.captures[0].blobs[0].sha256;
  const add = await page.request.post(`/api/pages/${ref.page_id}/captures`, {
    multipart: { id: id(), file: pdf("doc.pdf", "doc") },
  });
  const doc = ((await add.json()) as Saved).captures[1].blobs[0].sha256;
  const body = `Mixed\n\n![](/api/blobs/${img}/preview?size=2048)\n[doc.pdf](/api/blobs/${doc})`;
  const rev = ((await add.json()) as { rev: number }).rev;
  await page.request.patch(`/api/pages/${ref.page_id}`, { data: { base_rev: rev, body } });
  await page.goto(`/p/${ref.slug}`);
  await expect(page.locator("figure.orig img")).toHaveCount(1); // the image still a figure
  await expect(page.locator(`a[data-sha="${doc}"]`)).toHaveText("doc.pdf"); // a link in place
  await expect(page.locator(".originals .filerow")).toHaveCount(1); // and its row below
});

test("a token pasted twice: two chips, each with its picture", async ({ page }) => {
  const made = await page.request.post("/api/captures", {
    multipart: { id: id(), text: "Twice\n\n⟦image 1⟧", place: "1", file: photo("t.png") },
  });
  const ref = (await made.json()) as { page_id: string; slug: string };
  await page.goto(`/p/${ref.slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(chips(page).locator("img")).toHaveCount(1);
  await page.getByLabel("Body").press("Control+End");
  await page.keyboard.insertText("\n\n⟦image 1⟧"); // a copy of its token, pasted
  await expect(chips(page)).toHaveText(["Image 1", "Image 1"]);
  await expect(chips(page).locator("img")).toHaveCount(2);
  await page.keyboard.type(" more"); // drawn again: both keep a picture
  await expect(chips(page).locator("img")).toHaveCount(2);
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Cancel" }).click();
});

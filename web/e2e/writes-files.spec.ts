// The page editor's File takes PDFs (#234, #380): one goes to the page through the capture
// queue, listed below the text as a plain row (its name, opening it, and its pages once read),
// with a hint only if its text couldn't be read; picked with a photo, the photo still goes in
// the text. Camera and Gallery take photos only (writes-picked-files.spec.ts has File's others). The e2e server runs with ingest off, so e2e/readfiles.py reads the files.
import { execFileSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";
import { lowContrast } from "./contrast";
import { ulid } from "./helpers";

async function notePage(page: Page, text: string) {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text } });
  return (await r.json()) as { page_id: string; slug: string };
}

const read = async (page: Page, id: string) =>
  (await (await page.request.get(`/api/pages/${id}`)).json()) as {
    rev: number;
    body: string;
    captures: { blobs: { filename: string; ingest: { state: string } | null }[] }[];
  };

/** A real PDF, a page for each string (an empty one has no text at all). */
function pdf(pages: string[]): Buffer {
  const objs = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    `<< /Type /Pages /Kids [${pages.map((_, i) => `${4 + 2 * i} 0 R`).join(" ")}] /Count ${pages.length} >>`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  pages.forEach((t, i) => {
    const stream = t ? `BT /F1 24 Tf 72 720 Td (${t}) Tj ET` : "";
    objs.push(
      "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]" +
        ` /Resources << /Font << /F1 3 0 R >> >> /Contents ${5 + 2 * i} 0 R >>`,
      `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    );
  });
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
  return Buffer.from(out, "latin1");
}

const WORD = `quillwort${Date.now()}`; // found only in the PDF's text
const FILES = [
  {
    name: "minutes.pdf",
    mimeType: "application/pdf",
    buffer: pdf([`${WORD} minutes`, "page two"]),
  },
  { name: "blank.pdf", mimeType: "application/pdf", buffer: pdf([""]) },
  { name: "broken.pdf", mimeType: "application/pdf", buffer: Buffer.from("not a pdf at all") },
];

/** The file chooser a picker opens, and what it accepts. */
async function choose(page: Page, scope: string, label: string) {
  const chooser = page.waitForEvent("filechooser");
  await page.locator(scope).getByRole("button", { name: label, exact: true }).click();
  const c = await chooser;
  return { chooser: c, accept: await c.element().getAttribute("accept") };
}

const row = (page: Page, name: string) => page.locator(".filerow").filter({ hasText: name });

/** A file's card under its row (filecard.ts). */
const card = (page: Page, name: string) => page.locator(".file-panel").filter({ hasText: name });

test("the editor's File puts PDFs in the text, each a row with its card", async ({ page }) => {
  const ref = await notePage(page, "Committee notes\nsee the minutes");
  await page.goto(`/p/${ref.slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  const bar = '.editor [role="group"][aria-label="Add photos and files"]';
  expect((await choose(page, bar, "Camera")).accept).toBe("image/*");
  expect((await choose(page, bar, "Gallery")).accept).toBe("image/*");
  await page.getByLabel("Body").press("Control+End");
  const file = await choose(page, bar, "File");
  expect(file.accept).toBe("application/pdf,text/plain,text/markdown,.md,.txt");
  await file.chooser.setFiles(FILES);
  // A token each where the caret was, a chip each; nothing sent until Save
  await expect(page.getByLabel("Body")).toHaveValue(
    `Committee notes\nsee the minutes\n\n${FILES.map((f, i) => `⟦file ${i + 1}: ${f.name}⟧`).join("\n\n")}\n\n`,
  );
  await expect(page.locator(".editor .embeds .embed")).toHaveText(FILES.map((f) => f.name));
  expect((await read(page, ref.page_id)).captures.length).toBe(1);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".editor")).toBeHidden();
  const added = await read(page, ref.page_id);
  expect(added.rev).toBe(2);
  expect(added.captures[1].blobs.map((b) => b.filename)).toEqual(FILES.map((f) => f.name));

  // Waiting to be read: each file a row in place, its name opening it, its card saying so
  await page.reload();
  await expect(page.locator(".filerow")).toHaveCount(3);
  await expect(page.locator(".originals .filerow")).toHaveCount(0); // not listed twice
  for (const f of FILES) {
    const link = row(page, f.name).locator("a.file");
    await expect(link).toHaveAttribute("href", /^\/api\/blobs\/[0-9a-f]{64}$/);
    await expect(link).toHaveAttribute("target", "_blank");
    // The file's own link opens it, and the viewer saves it: no Download under the row
    await expect(row(page, f.name).getByRole("link", { name: "Download" })).toHaveCount(0);
    await expect(card(page, f.name).locator(".state")).toHaveText("Waiting to be read");
  }
  await expect(page.locator(".file-panel .did")).toHaveCount(0);
  await expect(page.locator(".photo-panel")).toHaveCount(0); // no Claude card for a file

  // Read (as the worker would): the page count, and why search can't find one
  const data = process.env.SCRAP_E2E_DATA as string;
  const args = ["run", "--locked", "python", "web/e2e/readfiles.py", data, ref.page_id];
  expect(execFileSync("uv", args, { cwd: "..", encoding: "utf8" }).trim()).toBe("3");
  await page.reload();
  // Only the failed read keeps its state, outside the fold (it has none), with Retry beside it
  await expect(page.locator(".file-panel .state")).toHaveCount(1);
  await expect(card(page, "broken.pdf").locator(".state")).toContainText("Couldn't read it");
  await expect(card(page, "broken.pdf").getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(card(page, "broken.pdf").locator("details")).toHaveCount(0);
  // The others: Claude's reading, one closed fold each (#521)
  await expect(page.locator(".file-panel details.reading-fold:not([open])")).toHaveCount(2);
  await expect(card(page, "minutes.pdf").locator(".did")).toHaveText("2 pages · Searchable");
  await expect(card(page, "minutes.pdf").locator(".did")).toBeHidden();
  const unread = "Text couldn't be read; not searchable";
  await expect(card(page, "blank.pdf").locator(".did")).toHaveText(`1 page · ${unread}`);
  // A PDF's text, fetched when the fold is opened
  await card(page, "minutes.pdf").getByText("Claude's reading").click();
  await expect(card(page, "minutes.pdf").locator("pre")).toContainText(WORD);
  await expect(card(page, "minutes.pdf").getByRole("button", { name: "Regenerate" })).toBeVisible();
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    await page.reload();
    await expect(card(page, "broken.pdf").locator(".state")).toBeVisible();
    for (const f of await page.locator(".file-panel .reading-fold > summary").all())
      await f.click();
    await expect(card(page, "minutes.pdf").locator("pre")).toContainText(WORD);
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} file rows`).toEqual([]);
  }
  // and the PDF's text finds the page
  const hits = (await (await page.request.get(`/api/search?q=${WORD}`)).json()) as { id: string }[];
  expect(hits.map((h) => h.id)).toContain(ref.page_id);
});

test("the composer's Camera and Gallery take photos only", async ({ page }) => {
  await page.goto("/");
  // The capture screen's tiles
  expect((await choose(page, ".actions", "Camera")).accept).toBe("image/*");
  expect((await choose(page, ".actions", "Gallery")).accept).toBe("image/*");
  await page.getByRole("button", { name: "Note" }).click();
  await expect(page.locator(".editor")).toBeVisible();
  const bar = ".editor .fields > .bar";
  expect((await choose(page, bar, "Camera")).accept).toBe("image/*");
  expect((await choose(page, bar, "Gallery")).accept).toBe("image/*");
});

// A real 1x1 PNG (the server makes its preview), as writes-photos.spec.ts's
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

test("a photo and a PDF picked together: both in the text, the PDF a row with its card", async ({
  page,
}) => {
  const ref = await notePage(page, "Site visit\nnotes");
  await page.goto(`/p/${ref.slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  const word = `sedgewarbler${Date.now()}`;
  const body = page.getByLabel("Body");
  await body.press("Control+End");
  const gallery = await choose(
    page,
    '.editor [role="group"][aria-label="Add photos and files"]',
    "Gallery",
  );
  await gallery.chooser.setFiles([
    { name: "board.png", mimeType: "image/png", buffer: PNG },
    { name: "report.pdf", mimeType: "application/pdf", buffer: pdf([`${word} report`]) },
  ]);
  await expect(body).toHaveValue("Site visit\nnotes\n\n⟦image 1⟧\n\n⟦file 1: report.pdf⟧\n\n");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".editor")).toBeHidden();
  const added = (await (await page.request.get(`/api/pages/${ref.page_id}`)).json()) as {
    rev: number;
    body: string;
    captures: { kind: string; blobs: { filename: string; ingest: { state: string } | null }[] }[];
  };
  expect(added.rev).toBe(2);
  // One capture, a photo capture so the photo is still read
  expect(added.captures.map((c) => c.kind)).toEqual(["note", "photo"]);
  expect(added.captures[1].blobs.map((b) => b.filename)).toEqual(["board.png", "report.pdf"]);
  expect(added.captures[1].blobs.map((b) => b.ingest?.state)).toEqual(["queued", "queued"]);
  expect(added.body.match(/!\[[^\]]*\]\(\/api\/blobs\//g)).toHaveLength(1);
  expect(added.body).toMatch(/\n\n\[report\.pdf\]\(\/api\/blobs\/[0-9a-f]{64}\)\s*$/);

  // The photo a figure in the text with its Claude card; the PDF a row in place, its card
  const data = process.env.SCRAP_E2E_DATA as string;
  const args = ["run", "--locked", "python", "web/e2e/readfiles.py", data, ref.page_id];
  expect(execFileSync("uv", args, { cwd: "..", encoding: "utf8" }).trim()).toBe("1");
  await page.reload();
  await expect(page.locator("figure.orig img")).toHaveCount(1);
  await expect(page.locator(".photo-panel")).toHaveCount(1);
  await expect(page.locator(".photo-panel")).not.toContainText("report.pdf");
  await expect(page.locator(".filerow")).toHaveCount(1);
  await expect(page.locator(".originals .filerow")).toHaveCount(0);
  await expect(card(page, "report.pdf").locator(".did")).toHaveText("1 page · Searchable");
  const hits = (await (await page.request.get(`/api/search?q=${word}`)).json()) as { id: string }[];
  expect(hits.map((h) => h.id)).toContain(ref.page_id);
});

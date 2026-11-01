// File (#380): Gallery takes photos only (so a phone opens its photo picker for it), and File
// takes PDFs, text and Markdown, on the capture screen, in the
// composer and in the page editor. A picked file is a chip with its name in the composer and
// the page editor (not a broken image).
import { expect, type Page, test } from "@playwright/test";
import { ulid } from "./helpers";

async function notePage(page: Page, text: string) {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text } });
  return (await r.json()) as { page_id: string; slug: string };
}

type Blob = { filename: string; mime: string };
const read = async (page: Page, id: string) =>
  (await (await page.request.get(`/api/pages/${id}`)).json()) as {
    rev: number;
    body: string;
    captures: { kind: string; blobs: Blob[] }[];
  };

const FILES = "application/pdf,text/plain,text/markdown,.md,.txt";
const PDF = { name: "minutes.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n") };
// A phone's .md often comes untyped: the server types it by its name
const MD = { name: "reading.md", mimeType: "", buffer: Buffer.from("# Reading\nthe wombat") };
const TXT = { name: "list.txt", mimeType: "text/plain", buffer: Buffer.from("eggs\nmilk") };

/** The file chooser a picker opens, and what it accepts. */
async function choose(page: Page, scope: string, label: string) {
  const chooser = page.waitForEvent("filechooser");
  await page.locator(scope).getByRole("button", { name: label, exact: true }).click();
  const c = await chooser;
  return { chooser: c, accept: await c.element().getAttribute("accept") };
}

const ADD = '.editor [role="group"][aria-label="Add photos and files"]';

test("Gallery takes photos only and File takes PDFs, text and Markdown, everywhere", async ({
  page,
}) => {
  await page.goto("/");
  const pickers = async (scope: string) => [
    (await choose(page, scope, "Camera")).accept,
    (await choose(page, scope, "Gallery")).accept,
    (await choose(page, scope, "File")).accept,
  ];
  expect(await pickers(".actions")).toEqual(["image/*", "image/*", FILES]);
  await page.getByRole("button", { name: "Note" }).click();
  expect(await pickers(".editor .fields > .bar")).toEqual(["image/*", "image/*", FILES]);
  const ref = await notePage(page, "Pickers");
  await page.goto(`/p/${ref.slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  expect(await pickers(ADD)).toEqual(["image/*", "image/*", FILES]);
});

test("a PDF and a .md picked with File: chips in the composer, files on the page", async ({
  page,
}) => {
  await page.goto("/");
  const { chooser } = await choose(page, ".actions", "File");
  await chooser.setFiles([PDF, MD]);
  await expect(page.locator(".editor")).toBeVisible();
  // Each a token in the text and a chip with its name (#403), not a photo that can't be drawn
  const box = page.locator(".editor textarea");
  await expect(box).toHaveValue("⟦file 1: minutes.pdf⟧\n\n⟦file 2: reading.md⟧\n\n");
  const thumbs = page.locator(".editor .embeds .embed");
  await expect(thumbs).toHaveCount(2);
  await expect(page.locator(".editor .embeds img")).toHaveCount(0);
  await expect(thumbs.nth(0)).toHaveText("minutes.pdf");
  await expect(thumbs.nth(1)).toHaveText("reading.md");
  await expect(page.getByRole("button", { name: "Remove file 1" })).toBeVisible();
  // One more from the composer's own File, then one taken out again
  await (await choose(page, ".editor .fields > .bar", "File")).chooser.setFiles([TXT]);
  await expect(thumbs).toHaveCount(3);
  await page.getByRole("button", { name: "Remove file 3" }).click();
  await expect(thumbs).toHaveCount(2);
  await expect(box).toHaveValue("⟦file 1: minutes.pdf⟧\n\n⟦file 2: reading.md⟧\n\n\n");
  const made = page.waitForResponse(
    (r) => r.url().endsWith("/api/captures") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const ref = (await (await made).json()) as { page_id: string; slug: string };
  const saved = await read(page, ref.page_id);
  expect(saved.captures.map((c) => c.kind)).toEqual(["file"]);
  expect(saved.captures[0].blobs.map((b) => [b.filename, b.mime])).toEqual([
    ["minutes.pdf", "application/pdf"],
    ["reading.md", "text/markdown"],
  ]);
  // Each linked where its token was, its row in place, and not listed again below the text
  expect(saved.body).toMatch(/^\[minutes\.pdf\]\(\/api\/blobs\/\w{64}\)\n\n\[reading\.md\]/);
  await page.goto(`/p/${ref.slug}`);
  await expect(page.locator(".filerow")).toHaveCount(2);
  await expect(page.locator(".originals .filerow")).toHaveCount(0);
  await expect(page.locator(".filerow", { hasText: "reading.md" })).toBeVisible();
});

test("the editor's File puts a .md and a text file in the text; Save adds them", async ({
  page,
}) => {
  const ref = await notePage(page, "Shopping\nfor the week");
  await page.goto(`/p/${ref.slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Body").press("Control+End");
  await (await choose(page, ADD, "File")).chooser.setFiles([MD, TXT]);
  await expect(page.getByLabel("Body")).toHaveValue(
    "Shopping\nfor the week\n\n⟦file 1: reading.md⟧\n\n⟦file 2: list.txt⟧\n\n",
  );
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".editor")).toBeHidden();
  const added = await read(page, ref.page_id);
  expect(added.rev).toBe(2);
  expect(added.captures[1].kind).toBe("file");
  expect(added.captures[1].blobs.map((b) => [b.filename, b.mime])).toEqual([
    ["reading.md", "text/markdown"],
    ["list.txt", "text/plain"],
  ]);
  await page.reload();
  await expect(page.locator(".filerow")).toHaveCount(2);
  await expect(page.locator(".originals .filerow")).toHaveCount(0); // in place, not below
  // A text file's card has no text fold: its own link opens it
  await expect(page.locator(".file-panel")).toHaveCount(2);
  await expect(page.locator(".file-panel pre")).toHaveCount(0);
  // In Edit again, each a token with a chip
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.locator(".editor .embeds .embed")).toHaveText(["reading.md", "list.txt"]);
});

// Add files on a computer: Camera, Gallery and File all open the same file dialog there, so the
// home screen shows Add files (photos and files in one pick) and Note, and the editor's row
// Add files alone (desktop.css). A phone keeps Camera, Gallery, File and Note.
import { expect, type Page, test } from "@playwright/test";
import { ulid } from "../src/ulid";

// A real 1x1 PNG
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);
const photo = (name: string) => ({ name, mimeType: "image/png", buffer: PNG });
const PDF = (name: string) => ({
  name,
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.4\n"),
});
const ANY = "image/*,application/pdf,text/plain,text/markdown,.md,.txt";
const ADD = '.editor [role="group"][aria-label="Add photos and files"]';

/** Pick files with scope's Add files: the chooser it opened, its accept and multiple. */
async function addFiles(page: Page, scope: string, files: ReturnType<typeof photo>[]) {
  const chooser = page.waitForEvent("filechooser");
  await page.locator(scope).getByRole("button", { name: "Add files", exact: true }).click();
  const c = await chooser;
  expect(await c.element().getAttribute("accept")).toBe(ANY);
  expect(c.isMultiple()).toBe(true);
  await c.setFiles(files);
}

test.describe("on a computer", () => {
  test.use({ viewport: { width: 1280, height: 900 }, isMobile: false, hasTouch: false });

  test("the home screen shows Add files and Note; one pick takes a photo and a PDF", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.locator(".actions > button:visible")).toHaveText(["Add files", "Note"]);
    for (const name of ["Camera", "Gallery", "File"])
      await expect(
        page.locator(".actions").getByRole("button", { name, exact: true }),
      ).toBeHidden();
    // Side by side, the same width
    const [a, b] = await Promise.all(
      ["Add files", "Note"].map((name) =>
        page.locator(".actions").getByRole("button", { name }).boundingBox(),
      ),
    );
    expect(a && b && Math.abs(a.y - b.y) < 1 && Math.abs(a.width - b.width) < 1).toBe(true);

    await addFiles(page, ".actions", [photo("a.png"), PDF("minutes.pdf")]);
    await expect(page.locator(".editor")).toBeVisible();
    const box = page.locator(".editor textarea");
    await expect(box).toHaveValue("⟦image 1⟧\n\n⟦file 1: minutes.pdf⟧\n\n");
    await expect(page.locator(".editor .embeds .embed")).toHaveCount(2);
    // The composer's own row: Add files alone, numbering on from the first pick
    await expect(page.locator(".editor .fields > .bar > button:visible")).toHaveText(["Add files"]);
    await box.evaluate((t: HTMLTextAreaElement) =>
      t.setSelectionRange(t.value.length, t.value.length),
    );
    await addFiles(page, ".editor .fields > .bar", [PDF("agenda.pdf"), photo("b.png")]);
    await expect(box).toHaveValue(
      "⟦image 1⟧\n\n⟦file 1: minutes.pdf⟧\n\n⟦file 2: agenda.pdf⟧\n\n⟦image 2⟧\n\n",
    );
    await expect(page.locator(".editor .embeds .embed")).toHaveCount(4);
  });

  test("with a kept draft over the tiles, Add files and Note both still show", async ({ page }) => {
    // The draft row is the first child of the tiles' row: Note must stay, as the last tile
    await page.goto("/");
    await page.getByRole("button", { name: "Note" }).click();
    await page.getByPlaceholder("Note or link").fill("Desk draft");
    await page.goBack(); // Back keeps it as the draft
    await expect(page.locator(".editor")).toBeHidden();
    await expect(page.locator(".capture .draft")).toBeVisible();
    await expect(page.locator(".actions > button:visible")).toHaveText(["Add files", "Note"]);
  });

  test("a page's Edit has Add files alone, taking a photo and a PDF together", async ({ page }) => {
    const r = await page.request.post("/api/captures", {
      data: { id: ulid(), text: "Desk add files" },
    });
    const { slug } = (await r.json()) as { slug: string };
    await page.goto(`/p/${slug}`);
    await page.locator(".page > .tools").getByRole("button", { name: "Edit" }).click();
    await expect(page.locator(`${ADD} > button:visible`)).toHaveText(["Add files"]);
    const box = page.locator(".editor textarea");
    await box.evaluate((t: HTMLTextAreaElement) =>
      t.setSelectionRange(t.value.length, t.value.length),
    );
    await addFiles(page, ADD, [photo("a.png"), PDF("minutes.pdf")]);
    await expect(box).toHaveValue(/⟦image 1⟧\n\n⟦file 1: minutes\.pdf⟧/);
    await expect(page.locator(".editor .embeds .embed")).toHaveCount(2);
  });
});

test("a phone keeps Camera, Gallery, File and Note, and no Add files", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".actions > button:visible")).toHaveText([
    "Camera",
    "Gallery",
    "File",
    "Note",
  ]);
  await page.getByRole("button", { name: "Note" }).click();
  await expect(page.locator(".editor .fields > .bar > button:visible")).toHaveText([
    "Camera",
    "Gallery",
    "File",
  ]);
});

// Deleting an image's line in the editor: Save warns, naming the image, before it goes.
import { expect, type Page, test } from "@playwright/test";
import { deletedAfterEach, ulid } from "./helpers";

const made = deletedAfterEach();

/** A page of one photo, of this many bytes: fresh ones (a ulid first), so a repeat of the
 * spec gets a blob no earlier page has shown. */
async function photoPage(page: Page, text: string, bytes: number) {
  const buffer = Buffer.alloc(bytes, 7);
  buffer.write(ulid());
  const r = await page.request.post("/api/captures", {
    multipart: {
      id: ulid(),
      text,
      file: { name: "whiteboard.png", mimeType: "image/png", buffer },
    },
  });
  const ref = (await r.json()) as { page_id: string; slug: string };
  made.push(ref.page_id);
  return ref;
}

// The dialog's message, or null if Save asked nothing; answer: accept it or not
function dialogs(page: Page) {
  const seen: string[] = [];
  let answer = false;
  page.on("dialog", (d) => {
    seen.push(d.message());
    void (answer ? d.accept() : d.dismiss());
  });
  return { seen, answer: (yes: boolean) => (answer = yes) };
}

/** Delete the last line of the body with the keyboard (so Undo can bring it back). */
async function deleteLastLine(page: Page) {
  const body = page.getByLabel("Body");
  await body.focus();
  await body.press("Control+End");
  await body.press("Shift+Home");
  await body.press("Backspace");
  await body.press("Backspace"); // the line break before it
}

test("deleting an image's line warns on Save; Cancel keeps editing, Undo, OK saves", async ({
  page,
}) => {
  const ref = await photoPage(page, "Board photo", 120);
  const before = await (await page.request.get(`/api/pages/${ref.page_id}`)).json();
  const sha = before.captures[0].blobs[0].sha256 as string;
  expect(before.body).toContain(`/api/blobs/${sha}`);
  const d = dialogs(page);
  await page.goto(`/p/${ref.slug}`);
  await expect(page.locator(".originals, .page figure").first()).toBeAttached();
  await page.getByRole("button", { name: "Edit" }).click();
  const body = page.getByLabel("Body");
  // The editor shows the image as a short token (embeds.ts), not its Markdown
  const shown = before.body.replace(/!\[[^\]]*\]\(\/api\/blobs\/[0-9a-f]{64}[^)]*\)/, "⟦image 1⟧");
  await expect(body).toHaveValue(shown);

  // Cancel: the editor stays open with the text as edited, nothing saved
  await deleteLastLine(page);
  const edited = await body.inputValue();
  expect(edited).not.toContain("⟦image 1⟧");
  await page.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => d.seen.length).toBe(1);
  expect(d.seen[0]).toContain("Saving removes an image from this page");
  expect(d.seen[0]).toContain("• whiteboard.png: no longer shown on any page");
  await expect(page.locator(".editor")).toBeVisible();
  expect(await body.inputValue()).toBe(edited);
  expect((await (await page.request.get(`/api/pages/${ref.page_id}`)).json()).rev).toBe(1);

  // Undo brings the line back: Save then asks nothing
  await body.press("Control+z");
  await body.press("Control+z");
  await expect(body).toHaveValue(shown);
  await body.press("End");
  await body.pressSequentially(" ok");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".editor")).toBeHidden();
  expect(d.seen.length).toBe(1);

  // Shared with another page: the warning says so
  const other = await photoPage(page, "Other", 121);
  const o = await (await page.request.get(`/api/pages/${other.page_id}`)).json();
  await page.request.patch(`/api/pages/${other.page_id}`, {
    data: { base_rev: o.rev, body: `${o.body}\n\n![](/api/blobs/${sha}/preview?size=2048)` },
  });
  await page.getByRole("button", { name: "Edit" }).click();
  await deleteLastLine(page);
  await page.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => d.seen.length).toBe(2);
  expect(d.seen[1]).toContain("• whiteboard.png: still shown on 1 other page");
  await expect(page.locator(".editor")).toBeVisible();

  // OK saves: the image is gone from the page (not listed below the text either)
  d.answer(true);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".editor")).toBeHidden();
  expect(d.seen.length).toBe(3);
  const after = await (await page.request.get(`/api/pages/${ref.page_id}`)).json();
  expect(after.body).not.toContain(sha);
  expect(after.removed).toEqual([sha]);
  await expect(page.getByText("whiteboard.png")).toHaveCount(0);
  await expect(page.locator(".page figure, .originals .orig")).toHaveCount(0);
});

test("an edit that deletes no image's line saves without asking", async ({ page }) => {
  const ref = await photoPage(page, "Keep my photo", 122);
  const d = dialogs(page);
  await page.goto(`/p/${ref.slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  const body = page.getByLabel("Body");
  await body.press("Control+Home");
  await body.pressSequentially("Note: ");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".editor")).toBeHidden();
  expect(d.seen).toEqual([]);
});

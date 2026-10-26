// The page editor's Add photo (#260): the photo goes to the end of the page, through the
// capture queue, so it waits on the phone while offline.
import { expect, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

async function notePage(page: Page, text: string) {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text } });
  return (await r.json()) as { page_id: string; slug: string };
}

const read = async (page: Page, id: string) =>
  (await (await page.request.get(`/api/pages/${id}`)).json()) as {
    rev: number;
    body: string;
    captures: { kind: string }[];
  };

// A real 1x1 PNG: the server must be able to make its preview. Bytes it can't decode get no
// preview, and the page then shows the photo as a file link instead of an image (#278's flake)
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

/** Pick a photo with the editor's Gallery. */
async function pick(page: Page) {
  const chooser = page.waitForEvent("filechooser");
  await page
    .getByRole("group", { name: "Add photo" })
    .getByRole("button", { name: "Gallery" })
    .click();
  await (await chooser).setFiles({ name: "board.png", mimeType: "image/png", buffer: PNG });
}

test("Add photo puts it at the end of the page and in the open editor's text", async ({ page }) => {
  const ref = await notePage(page, "Planning board\nfirst pass");
  await page.goto(`/p/${ref.slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  const body = page.getByLabel("Body");
  await body.press("Control+End");
  await body.pressSequentially("\nmore notes");
  await pick(page);
  // Uploaded: the editor's text gains its token after what was typed, nothing lost
  await expect(body).toHaveValue("Planning board\nfirst pass\nmore notes\n\n⟦image 1⟧");
  const added = await read(page, ref.page_id);
  expect(added.rev).toBe(2);
  expect(added.captures.map((c) => c.kind)).toEqual(["note", "photo"]);
  // Save is no conflict: the editor took the photo's revision
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".editor")).toBeHidden();
  const saved = await read(page, ref.page_id);
  expect(saved.rev).toBe(3);
  expect(saved.body).toMatch(
    /^Planning board\nfirst pass\nmore notes\n\n!\[\]\(\/api\/blobs\/[0-9a-f]{64}\/preview\?size=2048\)$/,
  );
});

test("offline, the photo waits on the phone and is added once back online", async ({
  page,
  context,
}) => {
  const ref = await notePage(page, "Second board");
  await page.goto(`/p/${ref.slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  await context.setOffline(true);
  await pick(page);
  await expect(page.getByText("kept on the phone")).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.locator(".editor")).toBeHidden();
  expect((await read(page, ref.page_id)).rev).toBe(1);
  await context.setOffline(false);
  await expect.poll(async () => (await read(page, ref.page_id)).rev).toBe(2);
  await page.reload();
  // Shown as an image, and one that loaded (a failed preview would become a file link)
  const img = page.locator(".page img[src*='/api/blobs/']").first();
  await expect(img).toBeVisible();
  await expect.poll(() => img.evaluate((i: HTMLImageElement) => i.naturalWidth)).toBe(1);
});

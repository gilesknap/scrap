// The page editor's Camera, Gallery and File (#260, as the composer's since #403): a picked photo
// is a token where the caret is, with a chip, and goes to the server with Save, which puts its
// embed where the token is. The row of three stays one line at large text sizes.
import { expect, type Page, test } from "@playwright/test";
import { ulid } from "./helpers";

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
    .getByRole("group", { name: "Add photos and files" })
    .getByRole("button", { name: "Gallery" })
    .click();
  await (await chooser).setFiles({ name: "board.png", mimeType: "image/png", buffer: PNG });
}

test("Gallery puts the photo's token at the caret; Save sends it with the edit", async ({
  page,
}) => {
  const ref = await notePage(page, "Planning board\nfirst pass");
  await page.goto(`/p/${ref.slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  const body = page.getByLabel("Body");
  await body.press("Control+End");
  await body.pressSequentially("\nmore notes");
  await pick(page);
  // A token after what was typed, and a chip; nothing is sent until Save
  await expect(body).toHaveValue("Planning board\nfirst pass\nmore notes\n\n⟦image 1⟧\n\n");
  await expect(page.locator(".editor .embeds .embed")).toHaveText(["Image 1"]);
  expect((await read(page, ref.page_id)).rev).toBe(1);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".editor")).toBeHidden();
  const saved = await read(page, ref.page_id);
  expect(saved.rev).toBe(2); // one revision: the text and the photo together
  expect(saved.captures.map((c) => c.kind)).toEqual(["note", "photo"]);
  expect(saved.body).toMatch(
    /^Planning board\nfirst pass\nmore notes\n\n!\[\]\(\/api\/blobs\/[0-9a-f]{64}\/preview\?size=2048\)\s*$/,
  );
  // Shown as an image, and one that loaded (a failed preview would become a file link)
  const img = page.locator(".page img[src*='/api/blobs/']").first();
  await expect(img).toBeVisible();
  await expect.poll(() => img.evaluate((i: HTMLImageElement) => i.naturalWidth)).toBe(1);
});

test("offline, Save keeps the editor and its photo to try again", async ({ page, context }) => {
  const ref = await notePage(page, "Second board");
  await page.goto(`/p/${ref.slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  await context.setOffline(true);
  await pick(page);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".toast")).toBeVisible();
  await expect(page.locator(".editor .embeds .embed")).toHaveCount(1); // still there
  expect((await read(page, ref.page_id)).rev).toBe(1);
  await context.setOffline(false);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".editor")).toBeHidden();
  expect((await read(page, ref.page_id)).captures.map((c) => c.kind)).toEqual(["note", "photo"]);
});

/** Camera, Gallery and File inside `scope` (the page editor's group, or the composer's bar),
 * read together in one pass so layout cannot move between them. */
const addButtons = (page: Page, scope: string) =>
  page.evaluate((sel) => {
    const bs = [...document.querySelectorAll(`${sel} button`)].filter((b) => b.checkVisibility());
    const root = document.documentElement;
    return {
      n: bs.length,
      rows: new Set(bs.map((b) => Math.round(b.getBoundingClientRect().y))).size,
      tall: bs.every((b) => Math.abs(b.getBoundingClientRect().height - 48) <= 1),
      clipped: bs.some((b) => b.scrollWidth > b.clientWidth + 1),
      overflow: root.scrollWidth - root.clientWidth,
    };
  }, scope);

/** Large text sizes (Android font scaling, as a root font size): the three stay one line of
 * 48 px buttons, an icon over each word where they would not fit beside it; no label cut, no
 * sideways scroll. Waits for the layout to settle after the font change. */
async function expectOneLine(page: Page, scope: string, root: number) {
  await page.addStyleTag({ content: `html { font-size: ${root}px !important; }` });
  await expect
    .poll(async () => JSON.stringify(await addButtons(page, scope)))
    .toBe(JSON.stringify({ n: 3, rows: 1, tall: true, clipped: false, overflow: 0 }));
}

const sizes = [
  { width: 390, root: 22.1 }, // 130% text
  { width: 360, root: 22.1 },
  { width: 320, root: 17 }, // 100%
  { width: 320, root: 22.1 },
];

for (const { width, root } of sizes) {
  test(`the editor's Camera, Gallery and File: ${root}px text on ${width}px`, async ({ page }) => {
    const ref = await notePage(page, `Large text ${width}`);
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`/p/${ref.slug}`);
    await page.getByRole("button", { name: "Edit" }).click();
    await expectOneLine(page, '.editor [role="group"][aria-label="Add photos and files"]', root);
  });

  test(`the composer's Camera, Gallery and File: ${root}px text on ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/");
    await page.getByRole("button", { name: "Note" }).click();
    await expect(page.locator(".editor")).toBeVisible();
    await expectOneLine(page, ".editor .fields > .bar", root);
  });
}

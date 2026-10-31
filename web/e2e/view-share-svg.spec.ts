// Sharing an SVG from the photo viewer (#486): many apps refuse SVG, so it is drawn on a canvas
// and shared as a PNG, named to match; if it can't be drawn, as the SVG, named .svg (or saved,
// where the phone can't share an SVG).
import { expect, type Page, test } from "@playwright/test";
import { ulid } from "../src/ulid";

const svg = (attrs: string) =>
  `<svg xmlns="http://www.w3.org/2000/svg" ${attrs}>` +
  '<rect x="10" y="10" width="380" height="80" fill="none" stroke="#000" stroke-width="4"/>' +
  '<circle cx="200" cy="50" r="30"/></svg>';

type Shared = { name: string; type: string; head: number[]; size: number[] | null }[][];

/** Open the viewer on a page with the SVG, with a share sheet that records what it is sent. */
async function open(page: Page, body: string) {
  await page.addInitScript(() => {
    const w = window as unknown as { shared: unknown[]; noSvg: boolean };
    w.shared = [];
    w.noSvg = false;
    navigator.canShare = (d?: ShareData) =>
      !(w.noSvg && d?.files?.some((f) => f.type === "image/svg+xml"));
    navigator.share = async (d?: ShareData) => {
      const files = [];
      for (const f of d?.files ?? []) {
        const head = [...new Uint8Array(await f.slice(0, 4).arrayBuffer())];
        // The pixels a PNG has (createImageBitmap can't read an SVG blob)
        const size =
          f.type === "image/png"
            ? await createImageBitmap(f).then((b) => [b.width, b.height])
            : null;
        files.push({ name: f.name, type: f.type, head, size });
      }
      w.shared.push(files);
    };
  });
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", "Share a diagram");
  form.append("file", new Blob([body], { type: "image/svg+xml" }), "flow.svg");
  const { slug } = await (await page.request.post("/api/captures", { multipart: form })).json();
  await page.goto(`/p/${slug}`);
  await page.locator("figure.orig img").click();
  const shared = () => page.evaluate(() => (window as unknown as { shared: Shared }).shared);
  const sharePhoto = async () => {
    await page.getByRole("dialog").getByRole("button", { name: "Share" }).click();
    await page.locator(".share-menu").getByRole("button", { name: "Photo" }).click();
  };
  return { shared, sharePhoto };
}

const PNG = [0x89, 0x50, 0x4e, 0x47];

test("an SVG is shared as a PNG drawn from it", async ({ page }) => {
  // No width or height: its size comes from the viewBox (400 x 100, drawn at 1024 x 256)
  const { shared, sharePhoto } = await open(page, svg('viewBox="0 0 400 100"'));
  await sharePhoto();
  await expect
    .poll(shared)
    .toEqual([[{ name: "flow.png", type: "image/png", head: PNG, size: [1024, 256] }]]);

  // It can't be drawn (no PNG from the canvas): the SVG itself, named and typed as one
  await page.evaluate(() => {
    HTMLCanvasElement.prototype.toBlob = (done: BlobCallback) => done(null);
  });
  await sharePhoto();
  await expect
    .poll(async () => (await shared())[1])
    .toEqual([
      { name: "flow.svg", type: "image/svg+xml", head: [0x3c, 0x73, 0x76, 0x67], size: null },
    ]);

  // ...and where the phone can't share an SVG, it is saved instead
  await page.evaluate(() => {
    (window as unknown as { noSvg: boolean }).noSvg = true;
  });
  const saved = page.waitForEvent("download");
  await sharePhoto();
  expect((await saved).suggestedFilename()).toBe("flow.svg");
  expect(await shared()).toHaveLength(2);
});

test("an SVG with only a width keeps its shape", async ({ page }) => {
  // 800 wide, and 4:1 by its viewBox: 800 x 200, drawn at 1024 x 256, not squashed
  const { shared, sharePhoto } = await open(page, svg('width="800" viewBox="0 0 400 100"'));
  await sharePhoto();
  await expect
    .poll(shared)
    .toEqual([[{ name: "flow.png", type: "image/png", head: PNG, size: [1024, 256] }]]);
});

// Sharing an SVG from the photo viewer (#486): many apps refuse SVG, so it is drawn on a canvas
// and shared as a PNG, named to match; if it can't be drawn, as the SVG, named .svg.
import { expect, test } from "@playwright/test";
import { ulid } from "../src/ulid";

// No width or height: its size comes from the viewBox (400 x 200, drawn at 1024 x 512)
const SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">' +
  '<rect x="10" y="10" width="380" height="180" fill="none" stroke="#000" stroke-width="4"/>' +
  '<text x="200" y="110" text-anchor="middle" font-size="40">A to B</text></svg>';

test("an SVG is shared as a PNG drawn from it", async ({ page }) => {
  await page.addInitScript(() => {
    const w = window as unknown as { shared: unknown[] };
    w.shared = [];
    navigator.canShare = () => true;
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
  form.append("file", new Blob([SVG], { type: "image/svg+xml" }), "flow.svg");
  const { slug } = await (await page.request.post("/api/captures", { multipart: form })).json();
  await page.goto(`/p/${slug}`);
  const shared = () => page.evaluate(() => (window as unknown as { shared: unknown[] }).shared);
  const sharePhoto = async () => {
    await page.getByRole("dialog").getByRole("button", { name: "Share" }).click();
    await page.locator(".share-menu").getByRole("button", { name: "Photo" }).click();
  };

  await page.locator("figure.orig img").click();
  await sharePhoto();
  await expect
    .poll(shared)
    .toEqual([
      [{ name: "flow.png", type: "image/png", head: [0x89, 0x50, 0x4e, 0x47], size: [1024, 512] }],
    ]);

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
});

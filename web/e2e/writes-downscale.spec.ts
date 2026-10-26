// Photos are made smaller on the phone before they are queued (#89): at most 2560 px on the
// long edge, upright, smaller than the original; anything the browser cannot decode goes up
// unchanged; Settings can turn it off.
import { createHash } from "node:crypto";
import { expect, type Page, test } from "@playwright/test";

/** A 4000x3000 JPEG with an EXIF Orientation of 6 (shown rotated 90 degrees clockwise, so
 * as 3000x4000). Its stored left half is red and the right half blue: shown upright, red
 * is the top and blue the bottom. Some texture, so that it is a real photo's worth of bytes. */
async function bigJpeg(page: Page): Promise<Buffer> {
  const b64 = await page.evaluate(async () => {
    const c = new OffscreenCanvas(4000, 3000);
    const g = c.getContext("2d") as OffscreenCanvasRenderingContext2D;
    g.fillStyle = "#e00";
    g.fillRect(0, 0, 2000, 3000);
    g.fillStyle = "#00e";
    g.fillRect(2000, 0, 2000, 3000);
    for (let i = 0; i < 4000; i += 40) {
      g.fillStyle = `rgba(255,255,255,${0.1 + ((i * 7) % 10) / 100})`;
      g.fillRect(i, (i * 13) % 3000, 20, 600);
    }
    const jpeg = new Uint8Array(
      await (await c.convertToBlob({ type: "image/jpeg", quality: 0.95 })).arrayBuffer(),
    );
    // APP1 "Exif": big-endian TIFF, one IFD entry, Orientation (0x0112) = 6
    const exif = [
      0xff, 0xe1, 0x00, 0x22, 0x45, 0x78, 0x69, 0x66, 0, 0, 0x4d, 0x4d, 0, 0x2a, 0, 0, 0, 8, 0, 1,
      0x01, 0x12, 0, 3, 0, 0, 0, 1, 0, 6, 0, 0, 0, 0, 0, 0,
    ];
    const out = new Uint8Array(jpeg.length + exif.length);
    out.set(jpeg.subarray(0, 2));
    out.set(exif, 2);
    out.set(jpeg.subarray(2), 2 + exif.length);
    let s = "";
    for (const v of out) s += String.fromCharCode(v);
    return btoa(s);
  });
  return Buffer.from(b64, "base64");
}

interface Queued {
  size: number;
  type: string;
  name: string;
  lastModified: number;
  width: number;
  height: number;
  top: string; // the upright photo's top-centre and bottom-centre pixels
  bottom: string;
  sha: string;
}

/** The files in the offline queue, read back from IndexedDB and decoded. */
async function queued(page: Page): Promise<Queued[]> {
  return page.evaluate(
    () =>
      new Promise((ok, no) => {
        const open = indexedDB.open("scrap");
        open.onerror = () => no(open.error);
        open.onsuccess = () => {
          const all = open.result.transaction("queue").objectStore("queue").getAll();
          all.onsuccess = async () => {
            const out = [];
            for (const item of all.result) {
              for (const f of item.files) {
                const blob = f.blob as Blob;
                const sha = [
                  ...new Uint8Array(
                    await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()),
                  ),
                ]
                  .map((b) => b.toString(16).padStart(2, "0"))
                  .join("");
                let width = 0;
                let height = 0;
                let top = "";
                let bottom = "";
                try {
                  const bmp = await createImageBitmap(blob);
                  width = bmp.width;
                  height = bmp.height;
                  const c = new OffscreenCanvas(width, height);
                  const g = c.getContext("2d") as OffscreenCanvasRenderingContext2D;
                  g.drawImage(bmp, 0, 0);
                  const px = (y: number) => {
                    const d = g.getImageData(3, y, 1, 1).data;
                    return d[0] > d[2] ? "red" : "blue";
                  };
                  top = px(Math.floor(height / 10));
                  bottom = px(Math.floor((height * 9) / 10));
                } catch {}
                out.push({
                  size: blob.size,
                  type: blob.type,
                  name: f.name,
                  lastModified: (blob as File).lastModified,
                  width,
                  height,
                  top,
                  bottom,
                  sha,
                });
              }
            }
            ok(out);
          };
        };
      }) as Promise<Queued[]>,
  );
}

/** Wait until the service worker has the downscale chunk, so going offline cannot beat it. */
async function ready(page: Page) {
  await page.evaluate(() => navigator.serviceWorker.ready);
  await expect
    .poll(() =>
      page.evaluate(async () =>
        (
          await Promise.all(
            (
              await caches.keys()
            ).map(async (k) => (await (await caches.open(k)).keys()).map((r) => r.url)),
          )
        )
          .flat()
          .some((u) => /\/assets\/downscale-[^/]+\.js$/.test(u)),
      ),
    )
    .toBe(true);
}

async function save(page: Page, file: { name: string; mimeType: string; buffer: Buffer }) {
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.getByText("Gallery").click(),
  ]);
  await chooser.setFiles(file);
  await page.getByRole("button", { name: "Save" }).click();
}

test("a big photo is queued at 2560 px, upright and smaller, with its name", async ({
  page,
  context,
}) => {
  await page.goto("/");
  const original = await bigJpeg(page);
  await ready(page);
  await context.setOffline(true); // so that the queue still holds it to be read
  await save(page, { name: "IMG_0001.jpg", mimeType: "image/jpeg", buffer: original });
  await expect(page.locator("#queue")).toHaveText("1 waiting");
  const [q] = await queued(page);
  expect(Math.max(q.width, q.height)).toBe(2560);
  expect([q.width, q.height]).toEqual([1920, 2560]); // portrait: the EXIF rotation applied
  expect(q.top).toBe("red");
  expect(q.bottom).toBe("blue");
  expect(q.size).toBeLessThan(original.length);
  expect(q.type).toBe("image/jpeg");
  expect(q.name).toBe("IMG_0001.jpg");
  expect(q.lastModified).toBeGreaterThan(0);
});

test("turned off in Settings, the photo is queued as it was", async ({ page, context }) => {
  await page.goto("/");
  const original = await bigJpeg(page);
  await page.getByRole("button", { name: "Settings" }).click();
  const group = page.getByRole("radiogroup", { name: "Smaller photos" });
  await expect(group.getByLabel("Smaller")).toBeChecked(); // on by default
  await group.getByText("Full size").click();
  await page.getByRole("button", { name: "Done" }).click();
  await ready(page);
  await context.setOffline(true);
  await save(page, { name: "IMG_0002.jpg", mimeType: "image/jpeg", buffer: original });
  await expect(page.locator("#queue")).toHaveText("1 waiting");
  const [q] = await queued(page);
  expect(q.size).toBe(original.length);
});

test("a file the browser cannot decode uploads unchanged", async ({ page }) => {
  const unique = `${Date.now()}-${Math.random()}`;
  const bytes = Buffer.from(
    `not really a HEIC photo, but a browser cannot decode it either ${unique}`,
  );
  await page.goto("/");
  await save(page, { name: `IMG_${unique}.heic`, mimeType: "image/heic", buffer: bytes });
  // The server stored the very bytes: its blob is addressed by their SHA-256
  const sha = createHash("sha256").update(bytes).digest("hex");
  const find = async () => {
    const list = (await (await page.request.get("/api/pages")).json()) as { id: string }[];
    for (const { id } of list) {
      const got = (await (await page.request.get(`/api/pages/${id}`)).json()) as {
        captures: { blobs: { sha256: string; name: string }[] }[];
      };
      const blobs = got.captures.flatMap((c) => c.blobs).filter((b) => b.sha256 === sha);
      if (blobs.length) return blobs;
    }
    return [];
  };
  await expect.poll(async () => (await find()).length).toBe(1);
});

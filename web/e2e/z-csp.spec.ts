// The Content-Security-Policy (issue 105) must not block anything the app does: no console
// report of a violation in the flows that reach for WebAssembly (Excalidraw's image resize and
// font subsetting on export) or for Mermaid. Runs after smoke.spec.ts, like whiteboard.spec.ts.
import { execFileSync } from "node:child_process";
import { deflateSync } from "node:zlib";
import { expect, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

/** Every console message or page error that reports the policy blocking something, less
 * Excalidraw's font subsetting (the fonts themselves are served by scrap, and vite.config.ts
 * points Excalidraw's CDN fallback at them, so nothing reaches for esm.sh), whose
 * Emscripten module builds functions with Function(): that needs 'unsafe-eval', which the
 * policy refuses, so Excalidraw skips subsetting (it logs it and exports with whole fonts). */
function violations(page: Page) {
  const seen: string[] = [];
  const check = (text: string) => {
    if (
      /Content Security Policy|Refused to|\bcsp\b/i.test(text) &&
      !text.includes("Skipped glyph subsetting")
    )
      seen.push(text);
  };
  page.on("pageerror", (e) => check(String(e)));
  page.on("console", (m) => check(m.text()));
  page.on("requestfailed", (r) => check(`${r.url()} ${r.failure()?.errorText}`));
  return seen;
}

/** A grey w x h PNG. */
function png(w: number, h: number): Buffer {
  const crc = (b: Buffer) => {
    let c = ~0;
    for (const x of b) {
      c ^= x;
      for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
    }
    return ~c >>> 0;
  };
  const chunk = (type: string, data: Buffer) => {
    const body = Buffer.concat([Buffer.from(type), data]);
    const out = Buffer.alloc(body.length + 8);
    out.writeUInt32BE(data.length, 0);
    body.copy(out, 4);
    out.writeUInt32BE(crc(body), body.length + 4);
    return out;
  };
  const head = Buffer.alloc(13);
  head.writeUInt32BE(w, 0);
  head.writeUInt32BE(h, 4);
  head.set([8, 0, 0, 0, 0], 8);
  const rows = Buffer.alloc((w + 1) * h, 128);
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", head),
    chunk("IDAT", deflateSync(rows)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

test("WebAssembly may compile under the policy", async ({ page }) => {
  const seen = violations(page);
  await page.goto("/");
  const result = await page.evaluate(async () => {
    // The smallest valid module: magic and version
    const wasm = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0]);
    const out: Record<string, string> = {};
    try {
      await WebAssembly.instantiate(wasm);
      out.wasm = "ok";
    } catch (e) {
      out.wasm = String(e);
    }
    return out;
  });
  expect(result).toEqual({ wasm: "ok" });
  expect(seen).toEqual([]);
});

test("Mermaid draws without a policy violation", async ({ page }) => {
  const seen = violations(page);
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", "Diagram\n\n```mermaid\ngraph TD\n  A[Start] --> B[End]\n```\n");
  const ref = await (await page.request.post("/api/captures", { multipart: form })).json();
  await page.goto(`/p/${ref.slug}`);
  await expect(page.locator(".diagram svg")).toBeVisible();
  expect(seen).toEqual([]);
});

test("a drawing opens, takes a photo, and exports with fonts, without a policy violation", async ({
  page,
}) => {
  const data = process.env.SCRAP_E2E_DATA as string;
  const out = execFileSync("uv", ["run", "--locked", "python", "web/e2e/draw.py", data], {
    cwd: "..",
    encoding: "utf8",
  });
  const b = JSON.parse(out.trim().split("\n").pop() || "null");
  const seen = violations(page);
  await page.goto(`/p/${b.slug}`);
  await page.locator(".drawing-card").click();
  const dialog = page.getByRole("dialog", { name: "Drawing" });
  await expect(dialog.locator(".excalidraw canvas").first()).toBeVisible();
  await expect(dialog.getByRole("button", { name: /^Edit/ })).toBeEnabled();

  for (const label of ["Export PNG", "Export SVG"]) {
    await dialog.getByText("More").click();
    const [file] = await Promise.all([
      page.waitForEvent("download"),
      dialog.getByRole("button", { name: label, exact: true }).click(),
    ]);
    expect(file.suggestedFilename()).toContain("drawing");
  }
  // Insert an image: Excalidraw resizes it with pica (WebAssembly)
  await dialog.getByRole("button", { name: /^Edit/ }).click();
  // The image tool is off here, but a dropped photo still goes through the resize
  const bytes = [...png(2400, 1800)];
  await page.evaluate((data) => {
    const file = new File([new Uint8Array(data)], "big.png", { type: "image/png" });
    const dt = new DataTransfer();
    dt.items.add(file);
    const target = document.querySelector(".excalidraw .interactive") as HTMLElement;
    const box = target.getBoundingClientRect();
    for (const type of ["dragenter", "dragover", "drop"])
      target.dispatchEvent(
        new DragEvent(type, {
          dataTransfer: dt,
          bubbles: true,
          cancelable: true,
          clientX: box.x + 50,
          clientY: box.y + 50,
        }),
      );
  }, bytes);
  await page.waitForTimeout(2000);

  expect(seen).toEqual([]);
});

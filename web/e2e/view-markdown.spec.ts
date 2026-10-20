// Page text as Markdown (render.ts, a chunk of its own): GitHub's tables, task lists and the
// rest, page links, an embedded photo as a figure, and a Mermaid diagram (a chunk of its own
// too); a table scrolls in its own box on a narrow phone; nothing in the console.
import { deflateSync } from "node:zlib";
import { expect, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

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
  for (let y = 0; y < h; y++) rows[y * (w + 1)] = 0;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", head),
    chunk("IDAT", deflateSync(rows)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const WIDE = Array.from({ length: 8 }, (_, i) => `Column ${i} with long words`);

test("tables, task lists, code, page links, a figure and a diagram", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  const other = await page.request.post("/api/captures", {
    data: { id: ulid(), text: "Linked target page" },
  });
  const target = (await other.json()).slug as string;
  const text = [
    "Rich page",
    "",
    "## Plan",
    "",
    `| ${WIDE.join(" | ")} |`,
    `|${"---|".repeat(WIDE.length)}`,
    `| [[${target}\\|the target]] | ~~old~~ | \`code\` |${" x |".repeat(WIDE.length - 3)}`,
    "",
    "- [ ] open task",
    "- [x] done task",
    "",
    "```mermaid",
    "graph TD",
    "  A[Start] --> B[End]",
    "```",
    "",
    "```",
    "<b>not bold</b> [[not-a-link]]",
    "```",
    "",
    "Said so[^1]. <img src=x onerror=alert(1)>",
    "",
    "[^1]: A footnote.",
  ].join("\n");
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", text);
  form.append("file", new Blob([new Uint8Array(png(300, 200))], { type: "image/png" }), "a.png");
  const ref = await (await page.request.post("/api/captures", { multipart: form })).json();

  await page.goto(`/p/${ref.slug}`);
  const body = page.locator(".body.md");
  await expect(body.locator("table th")).toHaveCount(WIDE.length);
  await expect(body.locator("td s")).toHaveText("old");
  await expect(body.locator("td code")).toHaveText("code");
  await expect(body.locator(`td a[href="/p/${target}"]`)).toHaveText("the target");
  await expect(body.locator("li.task input[type=checkbox]")).toHaveCount(2);
  await expect(body.locator("li.task input").nth(1)).toBeChecked();
  await expect(body.locator("li.task input").first()).toBeDisabled();
  await expect(body.locator("pre code:not(.language-mermaid)")).toContainText(
    "<b>not bold</b> [[not-a-link]]",
  );
  await expect(body.locator("h2#h-plan")).toHaveText("Plan");
  await expect(body.locator(".footnotes")).toContainText("A footnote.");
  await expect(body).toContainText("<img src=x onerror=alert(1)>"); // shown, not run
  // The embedded photo is a figure, with its name and Download (and Claude's panel)
  await expect(body.locator("figure.orig img")).toBeVisible();
  await expect(body.locator("figure.orig figcaption")).toContainText("a.png");
  // The diagram, drawn by Mermaid (a chunk loaded for it): its labels are text in an SVG
  await expect(body.locator(".diagram svg")).toBeVisible();
  await expect(body.locator(".diagram")).toContainText("Start");
  await expect(body.locator("code.language-mermaid")).toHaveCount(0);

  // A footnote link scrolls, it doesn't route
  await body.locator(".footnote-ref a").click();
  await expect(page).toHaveURL(new RegExp(`/p/${ref.slug}$`));

  // At 320 px the table scrolls in its box; the page doesn't
  await page.setViewportSize({ width: 320, height: 640 });
  const box = body.locator(".table");
  await expect.poll(() => box.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
  expect(await box.evaluate((el) => el.getBoundingClientRect().right)).toBeLessThanOrEqual(320);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);

  // A page link in the table routes in the app
  await body.locator(`td a[href="/p/${target}"]`).click();
  await expect(page.getByRole("heading", { name: "Linked target page" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("an image in a link is not taken into a figure (#82)", async ({ page }) => {
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", "Linked photo");
  form.append("file", new Blob([new Uint8Array(png(30, 20))], { type: "image/png" }), "b.png");
  const ref = await (await page.request.post("/api/captures", { multipart: form })).json();
  const p = await (await page.request.get(`/api/pages/${ref.slug}`)).json();
  const embed = /!\[\]\([^)]+\)/.exec(p.body)?.[0];
  const body = `${embed}\n[${embed}](https://example.com/)`;
  await page.request.patch(`/api/pages/${p.id}`, { data: { base_rev: p.rev, body } });
  await page.goto(`/p/${ref.slug}`);
  await expect(page.locator(".body.md p a[href='https://example.com/'] img")).toBeVisible();
});

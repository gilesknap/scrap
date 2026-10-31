// Page text as Markdown (render.ts, a chunk of its own): GitHub's tables, task lists and the
// rest, page links, an embedded photo as a figure, and a Mermaid diagram (a chunk of its own
// too); a table scrolls in its own box on a narrow phone, and on a computer the box hugs a
// narrow table; nothing in the console.
import { expect, test } from "@playwright/test";
import { png, ulid } from "./helpers";

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
  await expect(body.locator("li.task input").first()).toBeEnabled(); // ticks in place (tasks.ts)
  await expect(body.locator("pre code:not(.language-mermaid)")).toContainText(
    "<b>not bold</b> [[not-a-link]]",
  );
  await expect(body.locator("h2#h-plan")).toHaveText("Plan");
  await expect(body.locator(".footnotes")).toContainText("A footnote.");
  await expect(body).toContainText("<img src=x onerror=alert(1)>"); // shown, not run
  // The embedded photo is a figure, named by its alt (no caption: the viewer names it)
  await expect(body.locator("figure.orig img")).toBeVisible();
  await expect(body.locator("figure.orig img")).toHaveAttribute("alt", "a.png");
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

test.describe("on a computer (a wide window)", () => {
  test.use({ viewport: { width: 1024, height: 1280 }, isMobile: false, hasTouch: false });

  test("a narrow table's box hugs it, at the start of the line, so its shading reaches the border (#473)", async ({
    page,
  }) => {
    const text = [
      "Narrow table",
      "",
      "Some text.",
      "",
      "| a | b | c |",
      "|---|---|---|",
      "| 1 | 2 | 3 |",
    ];
    const res = await page.request.post("/api/captures", {
      data: { id: ulid(), text: text.join("\n") },
    });
    await page.goto(`/p/${(await res.json()).slug}`);
    const body = page.locator(".body.md");
    const box = body.locator(".table");
    await expect(box.locator("th")).toHaveCount(3);
    // One call, so a relayout can't fall between the measurements
    const m = await box.evaluate((el) => {
      const b = el.getBoundingClientRect();
      const t = el.querySelector("table")?.getBoundingClientRect();
      const p = el.closest(".body.md")?.querySelector("p")?.getBoundingClientRect();
      return { box: b.width, table: t?.width ?? 0, left: b.left, text: p?.left ?? -1 };
    });
    expect(Math.abs(m.box - (m.table + 2)), `box ${m.box}, table ${m.table}`).toBeLessThanOrEqual(
      2,
    );
    expect(Math.abs(m.left - m.text), `box at ${m.left}, text at ${m.text}`).toBeLessThanOrEqual(2);
  });
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

test("a paragraph with an image in a link, emphasis or a spaced link keeps all of it (#82)", async ({
  page,
}) => {
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", "Mixed photos");
  form.append("file", new Blob([new Uint8Array(png(30, 20))], { type: "image/png" }), "b.png");
  const ref = await (await page.request.post("/api/captures", { multipart: form })).json();
  const p = await (await page.request.get(`/api/pages/${ref.slug}`)).json();
  const e = /!\[\]\([^)]+\)/.exec(p.body)?.[0];
  const body = `${e}\n[${e}](https://example.com/a)\n\n${e}\n*${e}*\n\n${e}\n[ ](https://example.com/c)`;
  await page.request.patch(`/api/pages/${p.id}`, { data: { base_rev: p.rev, body } });
  await page.goto(`/p/${ref.slug}`);
  await expect(page.locator(".body.md a[href='https://example.com/a'] img")).toBeVisible();
  await expect(page.locator(".body.md em img")).toBeVisible();
  await expect(page.locator(".body.md a[href='https://example.com/c']")).toHaveCount(1);
});

test("the viewer names a photo on one line, however long its file name, at 360 and 412 px", async ({
  page,
}) => {
  const form = new FormData();
  form.append("id", ulid());
  form.append("text", "Long name photo");
  const name = "IMG_20261021_103455_garden_fence_left_side_from_the_shed.png";
  form.append("file", new Blob([new Uint8Array(png(300, 200))], { type: "image/png" }), name);
  const ref = await (await page.request.post("/api/captures", { multipart: form })).json();
  for (const width of [360, 412]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`/p/${ref.slug}`);
    await expect(page.locator(".page figure figcaption")).toHaveCount(0); // no caption
    await page.locator(".page figure img").first().click();
    const label = page.getByRole("dialog").locator(".name");
    await expect(label).toHaveText(name);
    // One line, cut with an ellipsis, inside the screen and clear of the count and Close
    const got = await label.evaluate((el) => {
      const r = el.getBoundingClientRect();
      return { right: r.right, height: Math.round(r.height), cut: el.scrollWidth > el.clientWidth };
    });
    expect(got.right).toBeLessThanOrEqual(width / 2);
    expect(got.height).toBeLessThanOrEqual(30);
    expect(got.cut).toBe(true);
    await page.goBack();
  }
});

test("a task box ticks in place: that item, saved at once; never over a newer edit", async ({
  page,
  context,
}) => {
  const text = "Packing\n\n- [ ] socks\n- [ ] socks\n- [x] passport\n\n```\n- [ ] in code\n```";
  const made = await (
    await page.request.post("/api/captures", { data: { id: ulid(), text } })
  ).json();
  const body = async () =>
    (await (await page.request.get(`/api/pages/${made.page_id}`)).json()) as {
      body: string;
      rev: number;
    };
  await page.goto(`/p/${made.slug}`);
  const boxes = page.locator(".page .md li.task input");
  await expect(boxes).toHaveCount(3); // not the one in code
  await expect(boxes.first()).toBeEnabled();
  // Each box is named by its item's text
  await expect(page.getByRole("checkbox", { name: "passport" })).toBeChecked();
  // Measured once the view has come in: it rises 6 px as it enters (bottom-nav.css), so a box
  // measured meanwhile is lower than it will be, and a tap 10 px below it lands on the next
  await page.waitForFunction(() =>
    document.getAnimations().every((a) => a.playState !== "running"),
  );
  // A tight list, as a bulleted one: one line from box to box
  const at = await boxes.nth(1).boundingBox();
  const below = await boxes.nth(2).boundingBox();
  if (!at || !below) throw new Error("no box");
  expect(below.y - at.y).toBeLessThan(32);
  // A target 48 px wide and a line high: a tap beside the box still reaches it, and that box,
  // not its neighbour's (no two targets meet)
  const [x, y] = [at.x + at.width / 2, at.y + at.height / 2];
  for (const [dx, dy] of [
    [20, 0],
    [-20, 0],
    [15, 10],
    [0, -10],
  ]) {
    const hit = await page.evaluate(
      ([px, py]) =>
        document
          .elementFromPoint(px, py)
          ?.closest(".taskbox")
          ?.querySelector("input")
          ?.getAttribute("data-line"),
      [x + dx, y + dy],
    );
    expect(hit).toBe(await boxes.nth(1).getAttribute("data-line"));
  }
  // The second "socks": that one only, saved with no editor
  await boxes.nth(1).click();
  await expect
    .poll(async () => (await body()).body)
    .toBe(text.replace("- [ ] socks\n- [x]", "- [x] socks\n- [x]"));
  await expect(page.locator(".editor")).toHaveCount(0);
  await expect(boxes.nth(1)).toBeChecked();
  await expect(boxes.nth(0)).not.toBeChecked();
  // Changed elsewhere meanwhile: not overwritten; the page as it is now, and why
  const now = await body();
  await page.request.patch(`/api/pages/${made.page_id}`, {
    data: { base_rev: now.rev, body: `${now.body}\n\nAdded elsewhere` },
  });
  await boxes.nth(0).click();
  await expect(page.locator(".toast")).toContainText("Changed elsewhere");
  await expect(page.getByText("Added elsewhere")).toBeVisible();
  await expect(boxes.nth(0)).not.toBeChecked();
  expect((await body()).body).toBe(`${now.body}\n\nAdded elsewhere`);
  // Offline: the boxes are off
  await context.setOffline(true);
  await expect(boxes.first()).toBeDisabled();
  await context.setOffline(false);
  await expect(boxes.first()).toBeEnabled();
  // In the editor's Preview they never tick
  await page.locator(".page .tools").getByRole("button", { name: "Edit" }).click();
  await page.locator(".editor").getByRole("button", { name: "Preview" }).click();
  await expect(page.locator(".editor .preview li.task input").first()).toBeDisabled();
});

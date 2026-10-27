// A page's header (#334): the meta line (kind, then what else), the dates line, and one row of
// chips (a todo's due chip first, the tags, the + that changes them). One line or two; one red
// word; no dot ending a line; no sideways scroll on a phone; AA contrast in both themes.
import { expect, type Page, test } from "@playwright/test";
import { lowContrast } from "./contrast";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};
const word = () => ulid().slice(-6).toLowerCase();

/** A day from today on this machine's calendar (the server's too), as YYYY-MM-DD. */
const day = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
};

// Every page made here is deleted after, so other specs' counts of the store's pages hold
const made: string[] = [];
test.afterEach(async ({ request }) => {
  for (const id of made.splice(0)) await request.delete(`/api/pages/${id}`);
});

/** A page of that kind, its other columns patched in: its slug and id. */
async function make(
  page: Page,
  text: string,
  kind: string,
  patch: Record<string, unknown> = {},
  extra: Record<string, unknown> = {},
) {
  const r = await page.request.post("/api/captures", {
    data: { id: ulid(), text, kind, ...extra },
  });
  const got = (await r.json()) as { page_id: string; slug: string };
  made.push(got.page_id);
  if (Object.keys(patch).length)
    expect((await page.request.patch(`/api/pages/${got.page_id}`, { data: patch })).ok()).toBe(
      true,
    );
  return got;
}

/** The page, once it has drawn its title and chip row, not only once the address
 * changed. (The chip row's + is what the tests reach for; waiting for the row keeps a slow first read from looking like a missing button.) */
async function open(page: Page, got: { slug: string }) {
  await page.goto(`/p/${got.slug}`);
  await expect(page.locator(".page > h1")).toBeVisible();
  await expect(page.locator(".page .tags")).toBeVisible();
}

/** The parts of a header line, as typed (its dots are drawn by CSS). */
const parts = async (page: Page, line: string) => {
  const row = page.locator(`.page > ${line} .parts > *`);
  await row.first().waitFor();
  return row.allInnerTexts();
};

test("a note, board or plain todo has one line; more to say makes two", async ({ page }) => {
  const note = await make(page, `Header note ${word()}`, "note");
  await open(page, note);
  await expect(page.locator(".page > p.meta.dates")).toHaveCount(1); // one line: both classes
  await expect(page.locator(".page > p.dates:not(.meta)")).toHaveCount(0);
  const one = await parts(page, ".meta");
  expect(one[0]).toBe("Note");
  expect(one[1]).toMatch(/^Created /);
  expect(one).toHaveLength(2); // never edited: no Edited

  // A todo with a due date and priority is still one line: they are in the due chip
  const plain = await make(page, `Header plain ${word()}`, "todo", {
    due: day(3),
    priority: "high",
  });
  await open(page, plain);
  await expect(page.locator(".page > p.meta.dates")).toHaveCount(1);
  expect((await parts(page, ".meta"))[0]).toBe("Todo");

  // A status other than open, a snooze, tasks: the meta line, then the dates line
  const busy = await make(page, `Header busy ${word()}\n\n- [x] one\n- [ ] two`, "todo", {
    fields: { status: "in_progress" },
    snoozed_until: day(5),
  });
  await open(page, busy);
  await expect(page.locator(".page > p.meta:not(.dates)")).toHaveCount(1);
  await expect(page.locator(".page > p.dates:not(.meta)")).toHaveCount(1);
  const meta = await parts(page, ".meta");
  expect(meta.slice(0, 2)).toEqual(["Todo", "in progress"]);
  expect(meta[2]).toMatch(/^snoozed till /);
  expect(meta[3]).toBe("1 of 2");
  expect((await parts(page, ".dates"))[0]).toMatch(/^Created /);
  // The kind word leads, in ink and semibold, after its (decorative) icon
  const kind = page.locator(".page > .meta .kind");
  await expect(kind.locator("svg")).toHaveAttribute("aria-hidden", "true");
  expect(await kind.evaluate((e) => getComputedStyle(e).fontWeight)).toBe("600");
});

test("a Later reads Kind · medium · verb, and its status once it is not open", async ({ page }) => {
  const later = await make(page, `Header later ${word()}`, "consume", {
    fields: { media_type: "tv", subtype: "watch" },
  });
  await open(page, later);
  expect(await parts(page, ".meta")).toEqual(["Later", "TV", "to watch"]);
  await page.request.patch(`/api/pages/${later.page_id}`, { data: { fields: { status: "done" } } });
  await page.reload();
  // Done, it says what was done, not "to watch · done"
  expect(await parts(page, ".meta")).toEqual(["Later", "TV", "watched"]);
  await expect(page.locator(".page > .dates:not(.meta)")).toBeVisible();
});

test("the due chip is first and opens the due editor, focus back after", async ({ page }) => {
  const t = await make(page, `Header due ${word()}`, "todo", { due: day(3), priority: "high" });
  await page.request.patch(`/api/pages/${t.page_id}`, { data: { tags: ["hdrcar"] } });
  await open(page, t);
  const row = page.locator(".page .tags");
  await expect(row.locator(":scope > *").first()).toHaveClass(/duechip/);
  const chip = row.locator(".duechip");
  await expect(chip).toHaveText(/^.+ · high$/);
  const box = await chip.boundingBox();
  expect(box?.height).toBeGreaterThanOrEqual(47); // a 48 px target
  await chip.click();
  await expect(page.locator(".todoedit")).toBeVisible();
  await expect(chip).toHaveCount(0); // in its place
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.locator(".page .tags .duechip")).toBeFocused();
  // An open todo with no due date offers one
  const bare = await make(page, `Header bare ${word()}`, "todo");
  await open(page, bare);
  await expect(page.locator(".tags .duechip")).toHaveText("Add due date");
});

test("an overdue todo has exactly one red word", async ({ page }) => {
  const t = await make(page, `Header late ${word()}`, "todo", {
    due: day(-2),
    priority: "high",
    tags: ["hdrlate"],
  });
  await open(page, t);
  const chip = page.locator(".tags .duechip");
  await expect(chip).toHaveText(/^overdue .+ · high$/);
  const red = await page.evaluate(() => {
    const danger = getComputedStyle(document.querySelector(".duechip .late") as Element).color;
    const out: string[] = [];
    for (const el of document.querySelectorAll(".page > :is(.meta, .dates, .tags) *")) {
      if (el.children.length) continue; // leaves only
      if (getComputedStyle(el).color === danger && el.textContent?.trim())
        out.push(el.textContent.trim());
    }
    return out;
  });
  expect(red).toEqual(["overdue"]);
});

test("a tag opens its search; + opens the tag editor and gives focus back", async ({ page }) => {
  const tag = `hdr${word()}`;
  const t = await make(page, `Header tags ${word()}`, "note", { tags: [tag, "car"] });
  await open(page, t);
  const row = page.locator(".page .tags");
  await row.getByRole("link", { name: "Tag car" }).click();
  await expect(page).toHaveURL("/search?q=tag%3Acar");
  await page.goBack();
  const plus = row.getByRole("button", { name: "Change tags" });
  // + sits straight after the last tag, in the same wrapper
  await expect(row.locator(".last").locator("a, button")).toHaveCount(2);
  await plus.click();
  await expect(page.locator(".tagform")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".tagform")).toBeHidden();
  await expect(page.locator(".page .tags .add")).toBeFocused();
});

test("the tag editor's and the write-up's .row are not the header's parts", async ({ page }) => {
  const t = await make(page, `Header rows ${word()}`, "note", { tags: ["car"] });
  await open(page, t);
  await page.locator(".page .tags .add").click();
  // Its Cancel and Save are the action row's while it is open
  const save = page.locator(".page > .tools").getByRole("button", { name: "Save" });
  await expect(save).toBeVisible();
  const style = await save.evaluate((e) => {
    const cs = getComputedStyle(e, "::before");
    return [cs.content, getComputedStyle(e).marginInlineStart];
  });
  expect(style).toEqual(["none", "0px"]);
});

test("the due chip stays while tags are edited; closing the due editor keeps focus", async ({
  page,
}) => {
  const t = await make(page, `Header both ${word()}`, "todo", { due: day(4), tags: ["car"] });
  await open(page, t);
  await page.locator(".page .tags .add").click();
  await expect(page.locator(".tagform")).toBeVisible();
  await expect(page.locator(".page .tags .duechip")).toBeVisible(); // not swept away
  await page.keyboard.press("Escape");
  await expect(page.locator(".page .tags .add")).toBeFocused();
  // The due editor, cancelled: focus is back on its chip
  await page.locator(".page .tags .duechip").click();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.locator(".page .tags .duechip")).toBeFocused();
});

test("an untagged page offers + Tag, named Add tags", async ({ page }) => {
  const t = await make(page, `Header untagged ${word()}`, "note");
  await open(page, t);
  const add = page.locator(".page .tags").getByRole("button", { name: "Add tags" });
  await expect(add).toHaveText("Tag");
  expect((await add.boundingBox())?.height).toBeGreaterThanOrEqual(47);
  await add.click();
  await expect(page.locator(".tagform")).toBeVisible();
});

/** Each visual line of a header line (".meta" or ".dates"), as geometry: its parts' edges, where
 * each part's gutter dot is centred, and the line's own clip box (its padding box). */
const lines = (page: Page, sel: string) =>
  page.locator(sel).evaluate((p) => {
    const box = p.getBoundingClientRect();
    const pad = Number.parseFloat(getComputedStyle(p).paddingLeft);
    const em = Number.parseFloat(getComputedStyle(p).fontSize);
    const parts = [...p.querySelectorAll<HTMLElement>(".parts > *")].map((k, i) => {
      const r = k.getBoundingClientRect();
      const border = Number.parseFloat(getComputedStyle(k).borderLeftWidth);
      // The text's own box: a link's padding (its 48 px target) is not text
      const padTop = Number.parseFloat(getComputedStyle(k).paddingTop);
      const padBottom = Number.parseFloat(getComputedStyle(k).paddingBottom);
      // The dot's box is 1.5em wide, ending at the part's padding edge
      return {
        i,
        top: r.top + padTop,
        bottom: r.bottom - padBottom,
        left: r.left,
        right: r.right,
        dot: r.left + border - 0.75 * em,
      };
    });
    const rows: (typeof parts)[] = [];
    for (const k of parts) {
      const row = rows.at(-1);
      if (row && Math.abs(row[0].top - k.top) < 3) row.push(k);
      else rows.push([k]);
    }
    return {
      clip: { left: box.left, top: box.top, bottom: box.bottom },
      edge: box.left + pad,
      rows,
    };
  });

/** The page, as Claude wrote it (made_by) or as a topic: its fetch answered with that changed. */
async function as(page: Page, change: Record<string, unknown>) {
  await page.route(/\/api\/pages\/[^/?]+$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), ...change } });
  });
}

const cases: [string, Record<string, unknown>][] = [
  ["plain", {}],
  ["written by Claude", { made_by: "claude" }],
];

for (const width of [320, 360, 390, 430])
  for (const [name, change] of cases)
    test(`${name} at ${width}px: a line starts at the edge, its dot gone; none ends in one; rings fit`, async ({
      page,
    }) => {
      const t = await make(page, `Header wrap ${word()}\n\n- [x] one\n- [ ] two`, "todo", {
        fields: { status: "in_progress" },
        snoozed_until: day(9),
      });
      await as(page, change);
      await page.setViewportSize({ width, height: 700 });
      await open(page, t);
      await expect(page.locator(".page .meta .parts")).toBeVisible();
      let wrapped = 0;
      for (const sel of [".page > .meta", ".page > .dates"]) {
        const { clip, edge, rows } = await lines(page, sel);
        wrapped += rows.length - 1;
        rows.forEach((row, n) => {
          // (a) a line's first part starts at the edge
          expect(Math.abs(row[0].left - edge), `${sel} line ${n} starts at the edge`).toBeLessThan(
            2,
          );
          // (b) the dot of a part that starts a line lies outside the clip box: not drawn
          if (row[0].i) expect(row[0].dot, `${sel} line ${n} dot`).toBeLessThan(clip.left);
          // (c) each other dot sits between its neighbours, so nothing is left at a line's end
          row.slice(1).forEach((k, j) => {
            expect(k.dot).toBeGreaterThan(row[j].right - 2);
            expect(k.dot).toBeLessThan(k.left);
          });
        });
        // A 2px ring with a 2px offset, round the first and last lines' parts, is not clipped
        const top = Math.min(...rows[0].map((k) => k.top));
        const bottom = Math.max(...(rows.at(-1) ?? []).map((k) => k.bottom));
        expect(top - 4, `${sel} ring above`).toBeGreaterThanOrEqual(clip.top - 0.5);
        expect(bottom + 4, `${sel} ring below`).toBeLessThanOrEqual(clip.bottom + 0.5);
        for (const row of rows) expect(row[0].left - 4).toBeGreaterThanOrEqual(clip.left - 0.5);
      }
      if (width === 320 && name === "plain") expect(wrapped, "320 px wraps").toBeGreaterThan(0);
    });

test("a link's focus ring in the meta line is whole", async ({ page }) => {
  const t = await make(page, `Header ring ${word()}`, "note");
  await as(page, { made_by: "claude" });
  await open(page, t);
  const link = page.locator(".page > .meta .written");
  await page.keyboard.press("Tab"); // the keyboard is in use, so the ring shows
  await link.focus();
  const ring = await link.evaluate((a) => {
    const cs = getComputedStyle(a);
    const r = a.getBoundingClientRect();
    const meta = a.closest(".meta") as HTMLElement;
    const p = meta.getBoundingClientRect();
    const reach = Number.parseFloat(cs.outlineWidth) + Number.parseFloat(cs.outlineOffset);
    return {
      style: cs.outlineStyle,
      left: r.left - reach - p.left, // clipped sideways (the dots in the gutter): room needed
      height: r.height,
      // Above and below the line nothing is clipped, so the ring and the 48 px target are whole
      overflowY: getComputedStyle(meta).overflowY,
    };
  });
  expect(ring.style).toBe("solid");
  expect(ring.left).toBeGreaterThanOrEqual(-0.5);
  expect(ring.overflowY).toBe("visible");
  expect(ring.height).toBeGreaterThanOrEqual(47); // a 48 px target
});

for (const width of [320, 360, 390, 430]) {
  test(`no sideways scroll at ${width}px, with long tags and a long title`, async ({ page }) => {
    const t = await make(
      page,
      `Header narrow ${word()} ${"verylongwordinatitle".repeat(3)}\n\n- [x] a\n- [ ] b`,
      "todo",
      {
        due: day(-1),
        priority: "medium",
        fields: { status: "in_progress" },
        snoozed_until: day(4),
        tags: ["alpha/beta/gamma/delta", "another-quite-long-tag", "car", "garden", "kitchen"],
      },
    );
    await page.setViewportSize({ width, height: 800 });
    await open(page, t);
    await expect(page.locator(".page .tags .add")).toBeVisible();
    for (const colorScheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme });
      const wide = await page.evaluate(() => {
        const over = (sel: string) => {
          const e = document.querySelector(sel) as HTMLElement;
          return e.scrollWidth - e.clientWidth;
        };
        return [
          document.documentElement.scrollWidth - document.documentElement.clientWidth,
          over(".page > .tags"),
          over(".page > .meta"),
          over(".page > .dates"),
        ];
      });
      expect(wide, `${colorScheme} at ${width}: page, tags, meta, dates`).toEqual([0, 0, 0, 0]);
    }
  });
}

test("the header has AA contrast in light and dark", async ({ page }) => {
  const t = await make(page, `Header contrast ${word()}`, "todo", {
    due: day(-1),
    priority: "high",
    tags: ["hdrink", "car"],
  });
  await open(page, t);
  await expect(page.locator(".page .tags .add")).toBeVisible();
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    expect(await page.evaluate(lowContrast, ""), colorScheme).toEqual([]);
  }
  const late = await make(page, `Header contrast later ${word()}`, "consume", {
    fields: { media_type: "tv", subtype: "watch" },
    tags: ["car"],
  });
  await open(page, late);
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} Later`).toEqual([]);
  }
});

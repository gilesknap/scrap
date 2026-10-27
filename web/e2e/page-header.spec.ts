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

/** The parts of a header line, as typed (its dots are drawn by CSS). */
const parts = async (page: Page, line: string) => {
  const row = page.locator(`.page > ${line} .row > *`);
  await row.first().waitFor();
  return row.allInnerTexts();
};

test("a note, board or plain todo has one line; more to say makes two", async ({ page }) => {
  const note = await make(page, `Header note ${word()}`, "note");
  await page.goto(`/p/${note.slug}`);
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
  await page.goto(`/p/${plain.slug}`);
  await expect(page.locator(".page > p.meta.dates")).toHaveCount(1);
  expect((await parts(page, ".meta"))[0]).toBe("Todo");

  // A status other than open, a snooze, tasks: the meta line, then the dates line
  const busy = await make(page, `Header busy ${word()}\n\n- [x] one\n- [ ] two`, "todo", {
    fields: { status: "in_progress" },
    snoozed_until: day(5),
  });
  await page.goto(`/p/${busy.slug}`);
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
  await page.goto(`/p/${later.slug}`);
  expect(await parts(page, ".meta")).toEqual(["Later", "TV", "to watch"]);
  await page.request.patch(`/api/pages/${later.page_id}`, { data: { fields: { status: "done" } } });
  await page.reload();
  expect(await parts(page, ".meta")).toEqual(["Later", "TV", "to watch", "done"]);
  await expect(page.locator(".page > .dates:not(.meta)")).toBeVisible();
});

test("the due chip is first and opens the due editor, focus back after", async ({ page }) => {
  const t = await make(page, `Header due ${word()}`, "todo", { due: day(3), priority: "high" }, {});
  await page.request.patch(`/api/pages/${t.page_id}`, { data: { tags: ["hdrcar"] } });
  await page.goto(`/p/${t.slug}`);
  const row = page.locator(".page .tags");
  const buttons = row.locator("> :is(a, button, span)");
  await expect(row.locator(":scope > *").first()).toHaveClass(/duechip/);
  const chip = row.locator(".duechip");
  await expect(chip).toHaveText(/^\w+ \d+ · high$/);
  const box = await chip.boundingBox();
  expect(box?.height).toBeGreaterThanOrEqual(47); // a 48 px target
  await expect(buttons.first()).toBeVisible();
  await chip.click();
  await expect(page.locator(".todoedit")).toBeVisible();
  await expect(chip).toHaveCount(0); // in its place
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.locator(".page .tags .duechip")).toBeFocused();
  // An open todo with no due date offers one
  const bare = await make(page, `Header bare ${word()}`, "todo");
  await page.goto(`/p/${bare.slug}`);
  await expect(page.locator(".tags .duechip")).toHaveText("Add due date");
});

test("an overdue todo has exactly one red word", async ({ page }) => {
  const t = await make(page, `Header late ${word()}`, "todo", {
    due: day(-2),
    priority: "high",
    tags: ["hdrlate"],
  });
  await page.goto(`/p/${t.slug}`);
  const chip = page.locator(".tags .duechip");
  await expect(chip).toHaveText(/^overdue \w+ \d+ · high$/);
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
  await page.goto(`/p/${t.slug}`);
  const row = page.locator(".page .tags");
  await row.getByRole("link", { name: "#car" }).click();
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

test("an untagged page offers + Tag, named Add tags", async ({ page }) => {
  const t = await make(page, `Header untagged ${word()}`, "note");
  await page.goto(`/p/${t.slug}`);
  const add = page.locator(".page .tags").getByRole("button", { name: "Add tags" });
  await expect(add).toHaveText("Tag");
  expect((await add.boundingBox())?.height).toBeGreaterThanOrEqual(47);
  await add.click();
  await expect(page.locator(".tagform")).toBeVisible();
});

test("no line starts or ends with a dot, and a wrapped line starts at the left edge", async ({
  page,
}) => {
  const t = await make(page, `Header wrap ${word()}\n\n- [x] one\n- [ ] two`, "todo", {
    fields: { status: "in_progress" },
    snoozed_until: day(9),
  });
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto(`/p/${t.slug}`);
  await expect(page.locator(".page .meta .row")).toBeVisible();
  const lay = await page.locator(".page > .meta").evaluate((p) => {
    const edge = p.getBoundingClientRect().left;
    const kids = [...(p.querySelectorAll(".row > *") as NodeListOf<HTMLElement>)];
    return kids.map((k) => {
      const r = k.getBoundingClientRect();
      return { top: Math.round(r.top), left: Math.round(r.left - edge), dot: k !== kids[0] };
    });
  });
  const tops = new Set(lay.map((l) => l.top));
  expect(tops.size, "320 px wraps this line").toBeGreaterThan(1);
  // A part that starts a line sits at the edge, where its gutter dot is clipped away
  for (const l of lay) if (l.left < 4) expect(l.top === lay[0].top || l.dot).toBe(true);
  // The text itself carries no dots to strand
  expect(await page.locator(".page > .meta").innerText()).not.toMatch(/·/);
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
    await page.goto(`/p/${t.slug}`);
    await expect(page.locator(".page .tags .add")).toBeVisible();
    for (const colorScheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme });
      const wide = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(wide, `${colorScheme} at ${width}`).toBeLessThanOrEqual(0);
    }
  });
}

test("the header has AA contrast in light and dark", async ({ page }) => {
  const t = await make(page, `Header contrast ${word()}`, "todo", {
    due: day(-1),
    priority: "high",
    tags: ["hdrink", "car"],
  });
  await page.goto(`/p/${t.slug}`);
  await expect(page.locator(".page .tags .add")).toBeVisible();
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    expect(await page.evaluate(lowContrast, ""), colorScheme).toEqual([]);
  }
  const late = await make(page, `Header contrast later ${word()}`, "consume", {
    fields: { media_type: "tv", subtype: "watch" },
    tags: ["car"],
  });
  await page.goto(`/p/${late.slug}`);
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} Later`).toEqual([]);
  }
});

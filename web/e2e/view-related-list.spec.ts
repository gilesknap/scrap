// Related on the About-this-page card reads as a list of pages (#375): a line each in the regular
// weight, the page's kind icon hung in the indent, 4 px apart, each link still a 48 px target,
// and a note (· links here) running on after its title. And the top bar stays over a page's task
// boxes when they scroll under it. Named to run after smoke.spec.ts, which wants an empty store.
import { expect, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

// Every page made here is deleted after, so other specs' counts of the store's pages hold
const made: string[] = [];
test.afterEach(async ({ request }) => {
  for (const id of made.splice(0)) await request.delete(`/api/pages/${id}`);
});

async function note(page: Page, text: string) {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text } });
  expect(r.ok()).toBe(true);
  const got = (await r.json()) as { page_id: string; slug: string };
  made.push(got.page_id);
  return got;
}

/** The page's answer as if Claude were on and had read it, with these related pages. */
async function asRead(page: Page, slug: string, related: object[]) {
  await page.route(`**/api/pages/${slug}`, async (r) => {
    if (r.request().method() !== "GET") return r.continue();
    const json = await (await r.fetch()).json();
    await r.fulfill({
      json: { ...json, enrich: { on: true, error: null, state: "done", summary: "S." }, related },
    });
  });
}

const LONG =
  "A very long title that goes on and on until it has to wrap onto a second line of the card";

for (const width of [320, 360, 390]) {
  for (const colorScheme of ["light", "dark"] as const) {
    test(`Related is a list of pages at ${width} px, ${colorScheme}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.emulateMedia({ colorScheme });
      const a = await note(page, `Rel a ${ulid().slice(-6)}`);
      const b = await note(page, `Rel b ${ulid().slice(-6)}`);
      const c = await note(page, `Rel c ${ulid().slice(-6)}`);
      const d = await note(page, `Rel d ${ulid().slice(-6)}`);
      const n = await note(page, `Rel host ${ulid().slice(-6)}`);
      await asRead(page, n.slug, [
        { id: a.page_id, slug: a.slug, title: "Short one", kind: "note", via: "claude" },
        { id: b.page_id, slug: b.slug, title: "Linked", kind: "todo", via: "link" },
        { id: c.page_id, slug: c.slug, title: "Written up", kind: "claude", via: "writeup" },
        { id: d.page_id, slug: d.slug, title: LONG, kind: "note", via: "link" },
      ]);
      await page.goto(`/p/${n.slug}`);
      const items = page.locator(".enrich .related li");
      await expect(items).toHaveCount(4);
      // Wait for the page's entrance (it rises as it enters), then measure
      await page.waitForFunction(() =>
        document.getAnimations().every((x) => x.playState !== "running"),
      );

      const m = await page.evaluate(() => {
        const lis = [...document.querySelectorAll<HTMLElement>(".enrich .related li")];
        const rect = (e: Element) => e.getBoundingClientRect();
        return lis.map((li, i) => {
          const a = li.querySelector("a") as HTMLElement;
          const small = li.querySelector("small");
          const lh = Number.parseFloat(getComputedStyle(li).lineHeight);
          // The title's own text: the last line it is set on
          const text = [...a.childNodes].find((x) => x.nodeType === Node.TEXT_NODE) as Text;
          const range = document.createRange();
          range.selectNodeContents(text);
          const lines = range.getClientRects();
          const last = lines[lines.length - 1];
          return {
            icon: !!a.querySelector("svg.i, .i"),
            iconSize: rect(a.querySelector(".i") as Element).width,
            weight: getComputedStyle(a).fontWeight,
            rows: Math.round(rect(li).height / lh),
            titleLines: lines.length,
            target: rect(a).height,
            gapAbove: i ? rect(li).top - rect(lis[i - 1]).bottom : null,
            note: small ? small.textContent : null,
            noteLines: small ? small.getClientRects().length : 0,
            // The note sits on the title's last line (not on one of its own)
            noteOnTitleLine: small ? Math.abs(rect(small).top - last.top) < lh / 2 : null,
            noteStartsLine: small ? rect(small).left <= rect(li).left + 1 : null,
            // The icon hung at the item's edge, the title's text 22 px in, as wrapped lines are
            iconAt: Math.round(rect(a.querySelector(".i") as Element).left - rect(li).left),
            textAt: Math.round(lines[0].left - rect(li).left),
          };
        });
      });

      for (const r of m) {
        expect(r.icon).toBe(true);
        expect(r.iconSize).toBe(16);
        expect([r.iconAt, r.textAt], "icon hung in the 22 px indent").toEqual([0, 22]);
        expect(r.weight).toBe("400");
        expect(r.target).toBeGreaterThanOrEqual(48);
        expect(r.noteLines, "a note is never split").toBeLessThanOrEqual(1);
      }
      // 4 px between items, and a line each: the short ones are one row, the long one wraps
      expect(m.slice(1).map((r) => r.gapAbove)).toEqual([4, 4, 4]);
      expect(m.slice(0, 3).map((r) => r.rows)).toEqual([1, 1, 1]);
      expect(m[3].titleLines).toBeGreaterThan(1);
      expect(m[3].rows).toBe(m[3].titleLines);
      // The notes run on after their titles
      expect(m[1].note).toBe(" · links here");
      expect(m[1].noteOnTitleLine).toBe(true);
      expect(m[1].noteStartsLine).toBe(false);
      expect(m[2].noteOnTitleLine).toBe(true);
      expect(m[0].note).toBeNull(); // a page Claude found has no note
    });
  }
}

test("Related: a long title's note runs on after its last line at 320 px", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  const x = await note(page, `Rel x ${ulid().slice(-6)}`);
  const n = await note(page, `Rel host ${ulid().slice(-6)}`);
  // Wraps to two lines, the second short enough to take the note
  const title = "A title long enough to wrap in the card, then ending";
  await asRead(page, n.slug, [{ id: x.page_id, slug: x.slug, title, kind: "note", via: "link" }]);
  await page.goto(`/p/${n.slug}`);
  const li = page.locator(".enrich .related li");
  await expect(li).toHaveCount(1);
  const r = await li.evaluate((el) => {
    const a = el.querySelector("a") as HTMLElement;
    const text = [...a.childNodes].find((x) => x.nodeType === Node.TEXT_NODE) as Text;
    const range = document.createRange();
    range.selectNodeContents(text);
    const lines = [...range.getClientRects()];
    const small = el.querySelector("small") as HTMLElement;
    return {
      lines: lines.length,
      lastTop: lines[lines.length - 1].top,
      noteTop: small.getBoundingClientRect().top,
      lh: Number.parseFloat(getComputedStyle(el).lineHeight),
    };
  });
  expect(r.lines).toBeGreaterThan(1);
  expect(Math.abs(r.noteTop - r.lastTop)).toBeLessThan(r.lh / 2);
});

for (const colorScheme of ["light", "dark"] as const) {
  test(`a task box scrolled under the top bar is not drawn over it (${colorScheme})`, async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme });
    const text = `Boxes ${ulid().slice(-6)}\n\n${Array.from({ length: 80 }, (_, i) => `- [ ] job ${i}`).join("\n")}`;
    const n = await note(page, text);
    await page.goto(`/p/${n.slug}`);
    const boxes = page.locator(".page .md li.task input");
    await expect(boxes).toHaveCount(80);
    await page.waitForFunction(() =>
      document.getAnimations().every((x) => x.playState !== "running"),
    );
    let overlapped = 0;
    for (let y = 300; y <= 1500; y += 120) {
      await page.evaluate((to) => window.scrollTo(0, to), y);
      const found = await page.evaluate(() => {
        const bar = document.querySelector("header") as HTMLElement;
        const br = bar.getBoundingClientRect();
        const out = { overlapped: 0, over: [] as string[] };
        for (const box of document.querySelectorAll(".page .md li.task input")) {
          const r = box.getBoundingClientRect();
          const top = Math.max(r.top, br.top);
          const bottom = Math.min(r.bottom, br.bottom);
          if (bottom - top < 4 || r.left < br.left || r.right > br.right) continue;
          out.overlapped++;
          // The point of the box that is under the bar: what is drawn there
          const at = document.elementFromPoint((r.left + r.right) / 2, (top + bottom) / 2);
          if (!at || !bar.contains(at)) out.over.push(at?.tagName ?? "nothing");
        }
        return out;
      });
      expect(found.over, `scrolled to ${y}`).toEqual([]);
      overlapped += found.overlapped;
    }
    expect(overlapped, "some box went under the bar").toBeGreaterThan(0);
  });
}

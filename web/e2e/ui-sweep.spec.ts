// The UI sweep (#345): the results header on Todos and Topics, one amber fill while a page's
// form is open, Add photo above the keys, no line ending in "·", the "Kept on this phone"
// toast, and the offline search. Named to run after smoke.spec.ts, which wants an empty store.
import { execFileSync } from "node:child_process";
import { expect, type Page, test } from "@playwright/test";

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
async function make(page: Page, text: string, kind: string, patch: Record<string, unknown> = {}) {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text, kind } });
  const got = (await r.json()) as { page_id: string; slug: string };
  made.push(got.page_id);
  if (Object.keys(patch).length)
    expect((await page.request.patch(`/api/pages/${got.page_id}`, { data: patch })).ok()).toBe(
      true,
    );
  return got;
}

/** The results header: 48 px tall, the count at its start and Refine (a 48 px target) in it. */
async function resultsHeader(page: Page, screen: string, count: RegExp) {
  const head = page.locator(`${screen} .rhead`);
  await expect(head.locator(".count")).toHaveText(count);
  expect((await head.boundingBox())?.height).toBeGreaterThanOrEqual(47.5);
  const refine = head.getByRole("link", { name: /^Refine in Search/ });
  const box = await refine.boundingBox();
  expect([box?.width, box?.height].map((n) => Math.round(n ?? 0))).toEqual([48, 48]);
  return refine;
}

test("Todos: the count line is the results header, and Refine goes to Search", async ({ page }) => {
  await make(page, `Sweep header ${word()}`, "todo", { due: day(2) });
  await page.goto("/todos");
  const refine = await resultsHeader(page, ".todos", /^\d+ open todos?$/);
  await refine.click();
  await expect(page).toHaveURL(/\/search\?q=kind%3Atodo/);
  // The same header over the results there
  await expect(page.locator(".rhead .count")).toHaveText(/^\d+ pages?$/);
  await expect(page.locator(".list li").first()).toBeVisible();
});

test("Topics: the count line is the results header, and Refine goes to Search", async ({
  page,
}) => {
  const data = process.env.SCRAP_E2E_DATA as string;
  const out = execFileSync("uv", ["run", "--locked", "python", "web/e2e/topics.py", data], {
    cwd: "..",
    encoding: "utf8",
  });
  const t = JSON.parse(out.trim().split("\n").pop() || "null") as {
    slug: string;
    title: string;
    sources: { id: string }[];
  };
  // Into the Trash after (the store has no purge), so no Topics or Recent list keeps them
  made.push(...t.sources.map((x) => x.id));
  made.push(((await (await page.request.get(`/api/pages/${t.slug}`)).json()) as { id: string }).id);
  await page.goto("/topics");
  await expect(page.locator(".topics .list li", { hasText: t.title })).toBeVisible();
  const refine = await resultsHeader(page, ".topics", /^\d+ topics?$/);
  await refine.click();
  await expect(page).toHaveURL(/\/search\?q=is%3Atopic/);
  await expect(page.locator(".list li", { hasText: t.title })).toBeVisible();
});

/** The elements drawn with the accent as their fill: what a screen's amber fills are. */
const amberFills = (page: Page) =>
  page.evaluate(() => {
    const probe = document.createElement("i");
    probe.style.background = "var(--accent)";
    document.body.append(probe);
    const accent = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return [...document.body.querySelectorAll<HTMLElement>("*")]
      .filter((e) => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(e).backgroundColor === accent;
      })
      .map((e) => e.textContent?.trim() || e.className || e.tagName);
  });

test("a todo's page has one amber fill: Save while its due form (or tags) is open", async ({
  page,
}) => {
  const t = await make(page, `Sweep amber ${word()}`, "todo", { due: day(3), tags: ["car"] });
  await page.goto(`/p/${t.slug}`);
  await expect(page.locator(".page .tags .duechip")).toBeVisible();
  // At rest: Mark done is the one fill
  expect(await amberFills(page)).toEqual(["Mark done"]);
  await page.locator(".page .tags .duechip").click();
  await expect(page.locator(".todoedit")).toBeVisible();
  await expect.poll(() => amberFills(page)).toEqual(["Save"]);
  await page.getByRole("button", { name: "Cancel" }).click();
  await page.locator(".page .tags .add").click();
  await expect(page.locator(".tagform")).toBeVisible();
  await expect.poll(() => amberFills(page)).toEqual(["Save"]);
});

test("Add photo scrolls clear of the keys, in the page editor", async ({ page }) => {
  const t = await make(page, `Sweep photo ${word()}\n\nSome text`, "note");
  // A phone with its keys up: the visual viewport is what is left above them
  await page.setViewportSize({ width: 390, height: 440 });
  await page.goto(`/p/${t.slug}`);
  await page.getByRole("button", { name: "Edit" }).click();
  const group = page.getByRole("group", { name: "Add photo" });
  await expect(group).toBeVisible();
  // Scrolled to the end of the fields, it is whole and clear of the keys (not under them)
  await page.locator(".editor .fields").evaluate((el) => el.scrollTo(0, el.scrollHeight));
  const inside = () =>
    page.evaluate(() => {
      const r = document
        .querySelector('.editor [role="group"][aria-label="Add photo"]')
        ?.getBoundingClientRect();
      const keys = document.querySelector(".editor .keys")?.getBoundingClientRect();
      return !!r && !!keys && r.bottom <= keys.top + 0.5 && r.top >= 0;
    });
  await expect.poll(inside).toBe(true);
  for (const name of ["Camera", "Gallery"])
    expect((await group.getByRole("button", { name }).boundingBox())?.height).toBeGreaterThan(47);
});

/** The last character of each line a text node is drawn on. */
const lineEnds = (page: Page, sel: string) =>
  page.locator(sel).evaluate((el) => {
    const ends: string[] = [];
    const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let rows: { y: number; c: string }[] = [];
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      const text = n.textContent ?? "";
      for (let i = 0; i < text.length; i++) {
        if (/\s/.test(text[i])) continue;
        const range = document.createRange();
        range.setStart(n, i);
        range.setEnd(n, i + 1);
        const r = range.getClientRects()[0];
        if (r) rows.push({ y: Math.round(r.top), c: text[i] });
      }
    }
    // The characters in reading order, grouped by the line they sit on
    for (const y of new Set(rows.map((r) => r.y)))
      ends.push(rows.filter((r) => r.y === y).at(-1)?.c ?? "");
    rows = [];
    return ends;
  });

test("no line of a todo's due text ends in a dot, at 320 px", async ({ page }) => {
  const t = await make(
    page,
    `Sweep dots ${word()} a longish title for a narrow screen\n\n- [x] one\n- [ ] two`,
    "todo",
    {
      due: day(-3),
      priority: "medium",
      fields: { status: "in_progress" },
      snoozed_until: day(6),
    },
  );
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto(`/p/${t.slug}`);
  await expect(page.locator(".page .tags .duechip")).toBeVisible();
  // The page header's own lines draw their dots in CSS (::before), which text cannot see:
  // page-header.spec.ts checks those. Here: the todo's row in Search
  // Its row in Search: the due line wraps (never mid-phrase), its lines end on a word
  await page.goto(`/search?q=${encodeURIComponent(`kind:todo "Sweep dots"`)}`);
  const due = page.locator(".list li .due").first();
  await expect(due).toBeVisible();
  expect((await lineEnds(page, ".list li .due")).length).toBeGreaterThan(0);
  expect(await lineEnds(page, ".list li .due")).not.toContain("·");
  // Each part holds together: a plain space is only ever followed by a dot (its break point)
  expect(await due.evaluate((e) => (e.textContent ?? "").split("\u00b7").length)).toBeGreaterThan(
    2,
  );
  expect(await due.evaluate((e) => /\u0020[^\u00b7]/.test(e.textContent ?? ""))).toBe(false);
});

test("a capture the server refuses toasts Saved, then Kept on this phone", async ({ page }) => {
  await page.route("**/api/captures", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status: 400, json: { detail: "refused" } })
      : route.continue(),
  );
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Note" })).toBeVisible();
  await page.getByRole("button", { name: "Note" }).click();
  await page.getByPlaceholder("Note or link").fill(`Sweep refused ${word()}`);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".toast", { hasText: "Kept on this phone" })).toBeVisible();
  await expect(page.locator("#queue")).toHaveText("1 failed");
});

test("a capture the server takes says Saved and never Kept on this phone", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Note" }).click();
  const text = `Sweep taken ${word()}`;
  await page.getByPlaceholder("Note or link").fill(text);
  await page.getByRole("button", { name: "Save" }).click();
  // Found and queued for deletion before anything is asserted, so a failure leaks nothing
  await expect
    .poll(async () => {
      const hits = await (
        await page.request.get(`/api/search?q=${encodeURIComponent(text)}`)
      ).json();
      for (const h of hits) if (!made.includes(h.id)) made.push(h.id);
      return hits.length;
    })
    .toBeGreaterThan(0);
  await expect(page.locator(".capture .list a", { hasText: text })).toBeVisible();
  await expect(page.locator(".toast", { hasText: "Kept on this phone" })).toHaveCount(0);
});

test("an empty search shows no count; offline, it says why and Retry brings the results", async ({
  page,
}) => {
  const none = `zzq${word()}`;
  await page.goto(`/search?q=${none}`);
  await expect(page.getByText("No matches")).toBeVisible();
  await expect(page.getByText(/\b0 pages?\b/)).toHaveCount(0);
  // Search cannot reach the server: the standard problem state, not a bare line
  const t = await make(page, `Sweep offline ${word()}`, "note");
  const query = t.slug.split("-")[0];
  await page.route("**/api/search?*", (route) => route.abort());
  await page.goto(`/search?q=${query}`);
  await expect(
    page.getByText("Can't reach the server. Check your connection or VPN."),
  ).toBeVisible();
  await page.unroute("**/api/search?*");
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.locator(".hits li", { hasText: "Sweep offline" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0);
});

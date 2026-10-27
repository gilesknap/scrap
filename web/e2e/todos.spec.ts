// The Todos screen: Now (overdue, today, high priority with no date, then the rest; done
// ones folded away), Upcoming and All, the switch in the address, and its rows' tick.
import { expect, type Page, test } from "@playwright/test";
import { lowContrast } from "./contrast";
import { openFold } from "./panel";

// The top bar's Back shows only in an iPhone's home-screen app (navigator.standalone), which
// has no Back of its own; tests here use it, so they run as one
test.beforeEach(({ context }) =>
  context.addInitScript(() => Object.defineProperty(navigator, "standalone", { value: true })),
);

/** A day from today on this machine's calendar (the server's too), as YYYY-MM-DD. */
const day = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
};

// Random ids: a worker started again after a failure runs this file's beforeAll again, and a
// counted id would then be one already used, so the capture would return another test's page
const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};
/** A word of this run only: every spec, and every repeat of this one, shares one store. */
const word = () => ulid().slice(-5).toLowerCase();
async function todo(page: Page, text: string, extra: Record<string, string> = {}) {
  const id = ulid();
  const r = await page.request.post("/api/captures", {
    data: { id, text, kind: "todo", ...extra },
  });
  expect(r.ok()).toBeTruthy();
  return (await r.json()) as { page_id: string; slug: string };
}

const made: Record<string, { page_id: string; slug: string }> = {};
let Q = "Quoll"; // these todos' first words: "Quoll" and a word of their own
test.beforeAll(async ({ request }) => {
  const page = { request } as Page;
  Q = `Quoll ${word()}`;
  // Made in an order unlike the ranking, so last-edited order can't pass for it
  made.rest = await todo(page, `${Q} later none`);
  made.soonMedium = await todo(page, `${Q} later medium`, { due: day(3), priority: "medium" });
  made.lateNew = await todo(page, `${Q} late new`, { due: day(-1), priority: "high" });
  made.todayLow = await todo(page, `${Q} today low`, { due: day(0), priority: "low" });
  made.high = await todo(page, `${Q} high no date`, { priority: "high" });
  made.lateOld = await todo(page, `${Q} late old`, { due: day(-5), priority: "low" });
  made.todayHigh = await todo(page, `${Q} today high`, { due: day(0), priority: "high" });
  made.farHigh = await todo(page, `${Q} later high`, { due: day(10), priority: "high" });
  made.done = await todo(page, `${Q} done`, { due: day(-3) });
  await request.patch(`/api/pages/${made.done.page_id}`, { data: { fields: { status: "done" } } });
});

/** This run's Quoll rows shown, in order (others' todos share the store). */
const quolls = async (page: Page, scope = ".todos > div > :is(section, ul) li") =>
  (await page.locator(`${scope} a strong`).allTextContents()).filter((t) => t.startsWith(`${Q} `));

test("Now ranks open todos: overdue, today, high priority, then the rest", async ({ page }) => {
  await page.goto("/todos");
  await expect(page.getByRole("radio", { name: "Now" })).toBeChecked();
  await expect(page.locator(".todos h2")).toHaveText([
    /^Overdue · \d+$/,
    /^Today · \d+$/,
    /^High priority · \d+$/,
    /^Open · \d+$/,
  ]);
  await expect
    .poll(() => quolls(page))
    .toEqual([
      `${Q} late old`,
      `${Q} late new`,
      `${Q} today high`,
      `${Q} today low`,
      `${Q} high no date`,
      `${Q} later high`,
      `${Q} later medium`,
      `${Q} later none`,
    ]);
  const section = (name: string) => page.getByRole("region", { name: new RegExp(`^${name}`) });
  await expect(section("Overdue").getByText(`${Q} late old`)).toBeVisible();
  await expect(section("Today").getByText(`${Q} today high`)).toBeVisible();
  // Each row says its priority and due date first; overdue in words (and red)
  const late = page.locator(".list li", { hasText: `${Q} late old` }).locator(".due");
  await expect(late).toHaveText(/^low\s·\soverdue\s/); // the parts hold their no-break spaces
  await expect(late).toHaveClass("due late");
  // Done: folded away at the end
  const fold = page.locator(".donefold");
  await expect(fold.getByText(`${Q} done`)).toBeHidden();
  await fold.locator("summary").click();
  await expect(fold.getByText(`${Q} done`)).toBeVisible();
  // The rows tick like the search screen's
  const row = page.locator(".list li", { hasText: `${Q} today low` });
  await row.getByRole("button", { name: `Done: ${Q} today low` }).click();
  await expect(row.locator("em")).toHaveText("done");
  await row.getByRole("button", { name: `Done: ${Q} today low` }).click();
  await expect(row.locator("em")).toHaveCount(0); // open: no chip, its icon says todo
});

test("the Now / Upcoming / All switch is in the address; Back and reload keep it", async ({
  page,
}) => {
  await page.goto("/todos");
  // Each with its icon over its word, as the search screen's kinds
  const show = page.getByRole("radiogroup", { name: "Show" });
  await expect(show.locator("label")).toHaveText(["Now", "Upcoming", "All"]);
  await expect(show.locator("label > svg.i")).toHaveCount(3);
  await page.getByText("Upcoming", { exact: true }).click();
  await expect(page).toHaveURL(/\/todos\?view=upcoming$/);
  // Due from tomorrow to a week away: not "later high", due in 10 days
  await expect.poll(() => quolls(page)).toEqual([`${Q} later medium`]);
  await expect(page.locator(".todos .count")).toHaveText(/ due in the next 7 days/);
  await expect(page.getByRole("combobox", { name: "Sort" })).toHaveCount(0); // the view's order
  await page.getByText("All", { exact: true }).click();
  await expect(page).toHaveURL(/\/todos\?view=all$/);
  const all = await quolls(page, ".todos ul li");
  expect(all[0]).toBe(`${Q} done`); // last edited first, done ones too
  expect(all).toHaveLength(9);
  // Two lines on every tab: what to do and when, never when it was last edited
  const edited = page.locator(".todos .list li .sub > small:not([class])");
  expect(await edited.count()).toBeGreaterThan(0);
  for (const s of await edited.all()) await expect(s).toBeHidden();
  await page.reload();
  await expect(page.getByRole("radio", { name: "All" })).toBeChecked();
  // A page opened from the list steps through it, and Back comes back to the same view
  await page.getByText("Upcoming", { exact: true }).click();
  await page.locator(".list a", { hasText: `${Q} later medium` }).click();
  await expect(page.locator("header .pager")).toHaveAttribute("aria-label", "In Todos · Upcoming");
  await expect(page.locator("#backto")).toHaveText("Todos");
  await page.goBack();
  await expect(page).toHaveURL(/\/todos\?view=upcoming$/);
  await expect(page.getByRole("radio", { name: "Upcoming" })).toBeChecked();
  await page.getByText("Now", { exact: true }).click();
  await expect(page).toHaveURL(/\/todos$/);
  // No Search todos link: the search screen's Todos kind filters in place, as the others do
  await expect(page.getByRole("link", { name: "Search todos" })).toHaveCount(0);
  await page.goto("/search");
  await page.getByRole("radiogroup", { name: "Kind" }).getByText("Todos").click();
  await expect(page).toHaveURL(/\/search\?q=kind%3Atodo$/); // not the Todos screen
  await expect(page.getByRole("searchbox")).toHaveValue("kind:todo");
  await expect(page.getByRole("radio", { name: "Todos" })).toBeChecked();
  // The Todos kind lists in sections (Now), not the All list that is on screen until they
  // arrive, so wait for them: the chips below would otherwise be checked on the old list. (The
  // done ones are folded, so a chip is not always visible; and a long store pages them out.)
  await expect(page.locator(".groups")).toBeVisible();
  const rows = page.locator(".groups .list li");
  await expect(rows.first()).toBeVisible();
  // Todos only: each row has a tick, and a chip is a todo status
  await expect(rows.filter({ has: page.locator(".tick") })).toHaveCount(await rows.count());
  for (const chip of await page.locator(".list li em").allTextContents())
    expect(["todo", "done", "cancelled"]).toContain(chip);
  await page.getByRole("radiogroup", { name: "Kind" }).getByText("Todos").click(); // off again
  await expect(page.getByRole("searchbox")).toHaveValue("");
  await expect(page).toHaveURL(/\/search$/);
});

test("the Todos screen meets AA contrast, in both themes", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    await page.goto("/todos");
    await expect(page.locator(".list .due.late").first()).toBeVisible();
    await page.locator(".donefold summary").click();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} todos`).toEqual([]);
  }
});

test("the Todos tab: one tap to Now, with a count of the todos due", async ({ page }) => {
  const tab = page.locator('nav a[href="/todos"]');
  const badge = tab.locator(".due-n");
  // Each step is checked against the server's answer to the badge's own request, asked after
  // that step. The steps by one (n - 1, then n) hold only while no other worker changes the
  // store's todos meanwhile: true in CI (workers: 1), not under --workers above 1
  const isDue = (url: URL) =>
    url.pathname === "/api/search/facets" && !!url.searchParams.get("q")?.includes("due:<=");
  const counted = async (step: () => Promise<unknown>) => {
    const asked = page.waitForRequest((r) => isDue(new URL(r.url())));
    await step();
    const answer = await (await asked).response();
    if (!answer) throw new Error("the badge's count went unanswered");
    const { total } = (await answer.json()) as { total: number };
    await expect(badge).toHaveText(String(total));
    await expect(tab).toHaveAccessibleName(`Todos, ${total} due`);
    return total;
  };
  const n = await counted(() => page.goto("/"));
  await expect(page.locator("nav a")).toHaveText(["Capture", /Todos$/, "Search", "Topics"]);
  expect(n).toBeGreaterThanOrEqual(4); // the Quolls: two overdue, two today
  expect((await tab.boundingBox())?.height).toBeGreaterThanOrEqual(44);
  await tab.click();
  await expect(page).toHaveURL(/\/todos$/);
  await expect(tab).toHaveAttribute("aria-current");
  await expect(page.getByRole("radio", { name: "Now" })).toBeChecked();
  // Ticking one off counts down at once, and back up
  const tick = page.getByRole("button", { name: `Done: ${Q} today high` });
  expect(await counted(() => tick.click())).toBe(n - 1);
  expect(await counted(() => tick.click())).toBe(n);
  // None due: no badge
  await page.route(
    (url) =>
      url.pathname === "/api/search/facets" && !!url.searchParams.get("q")?.includes("due:<="),
    (route) => route.fulfill({ json: { total: 0 } }),
  );
  await page.reload();
  await expect(page.locator(".todos")).toBeVisible();
  await expect(badge).toBeHidden();
  await expect(tab).toHaveAccessibleName("Todos");
});

test("switching Now, Upcoming and All replaces the entry: Back leaves Todos", async ({ page }) => {
  await page.goto("/");
  await page
    .locator("nav")
    .getByRole("link", { name: /^Todos/ })
    .click();
  await expect(page).toHaveURL(/\/todos$/);
  await page.getByText("Upcoming", { exact: true }).click();
  await page.getByText("All", { exact: true }).click();
  await page.getByText("Now", { exact: true }).click();
  await page.getByText("All", { exact: true }).click();
  await expect(page).toHaveURL(/\/todos\?view=all$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/$/); // off Todos at once, not through each view
  await expect(page.getByRole("button", { name: "Camera" })).toBeVisible();
});

test("snooze a todo from its page: out of Now and the count until its day, marked in All", async ({
  page,
}) => {
  const w = word();
  const title = `Bilby ${w} snooze me`;
  const t = await todo(page, title, { due: day(-1), priority: "high" });
  const inNow = () => page.locator(".todos .list a strong", { hasText: title });
  const badgeQ = encodeURIComponent(
    `kind:todo due:<=today -is:done -is:cancelled -is:snoozed ${w}`,
  );
  const counted = async () =>
    (
      (await (await page.request.get(`/api/search?q=${badgeQ}`)).json()) as { title: string }[]
    ).some((h) => h.title === title);
  await page.goto("/todos");
  await expect(inNow()).toBeVisible();
  expect(await counted()).toBe(true);
  await page.goto(`/p/${t.slug}`);
  const line = page.locator(".page .tags .duechip");
  const meta = page.locator(".page > .meta"); // a snooze is said on the meta line
  await line.click();
  await page.getByLabel("Snooze until").fill(day(1));
  await page.getByRole("button", { name: "Save" }).click();
  // Past its due date (yesterday): asked whether the due date moves too; kept here
  const ask = page.getByRole("group", { name: "Due date" });
  await expect(ask).toContainText("Snoozed past its due date");
  await ask.getByRole("button", { name: "Keep due date" }).click();
  await expect(meta).toContainText("snoozed till");
  expect((await (await page.request.get(`/api/pages/${t.page_id}`)).json()).due).toBe(day(-1));
  expect((await (await page.request.get(`/api/pages/${t.page_id}`)).json()).snoozed_until).toBe(
    day(1),
  );
  expect(await counted()).toBe(false); // the Todos tab's count leaves it out
  await page.goto("/todos");
  // "1 snoozed" links to a search of them (open ones only: is:snoozed skips done ones)
  const asleep = page.locator(".todos .rhead .acts a.snoozed");
  await expect(asleep).toHaveText(/^\d+ snoozed$/);
  await expect(inNow()).toHaveCount(0);
  await asleep.click();
  await expect(page).toHaveURL(/\/search\?q=kind%3Atodo(%20|\+)is%3Asnoozed(%20|\+)sort%3Adue$/);
  await expect(page.locator(".list li", { hasText: title })).toBeVisible();
  await page.goto("/todos");
  await page.getByText("All", { exact: true }).click();
  const row = page.locator(".list li", { hasText: title });
  await expect(row.locator(".due")).toHaveText(/^high\s·\soverdue\s.*\s·\ssnoozed\still\s/);
  // Woken by hand: back in Now
  await row.locator("a").click();
  await line.click();
  await page.getByRole("button", { name: "No snooze" }).click();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(meta).not.toContainText("snoozed");
  await page.goto("/todos");
  await expect(inNow()).toBeVisible();
});

test("task boxes drive a todo: filed as one, 2 of 3 on its row, done with the last box", async ({
  page,
}) => {
  const title = `Kowari ${word()} trip`;
  const text = `${title}\n\n- [x] tickets\n- [ ] tent\n- [ ] stove`;
  const made = await (
    await page.request.post("/api/captures", { data: { id: ulid(), text } })
  ).json();
  const api = async () => (await page.request.get(`/api/pages/${made.page_id}`)).json();
  expect(await api()).toMatchObject({ kind: "todo", tasks: { done: 1, total: 3 } }); // a note: filed
  await page.goto("/todos?view=all");
  const row = page.locator(".list li", { hasText: title });
  await expect(row.locator(".due")).toHaveText("1 of 3");
  const tick = row.getByRole("button", { name: `Done: ${title}` });
  await expect(tick).toHaveAttribute("aria-pressed", "mixed");
  // Ticked in place on its page: the last box makes it done; one unticked opens it again
  await row.locator("a").click();
  const boxes = page.locator(".page .md li.task input");
  const tools = page.locator(".page > .tools");
  await boxes.nth(1).click();
  await expect(page.locator(".page > .meta")).toContainText("2 of 3");
  await boxes.nth(2).click();
  await expect(tools.getByRole("button", { name: "Reopen" })).toBeVisible();
  expect((await api()).fields.status).toBe("done");
  await boxes.nth(0).click();
  await expect(tools.getByRole("button", { name: "Mark done", exact: true })).toBeVisible();
  expect(await api()).toMatchObject({ fields: { status: "open" }, tasks: { done: 2, total: 3 } });
  // Done by hand ticks no box (opened on its own, not from a list)
  await page.goto("/");
  await page.goto(`/p/${made.slug}`);
  await expect(page.locator(".pager")).toHaveCount(0);
  await tools.getByRole("button", { name: "Mark done", exact: true }).click();
  await expect(tools.getByRole("button", { name: "Reopen" })).toBeVisible();
  await expect(boxes.nth(0)).not.toBeChecked();
  expect(await api()).toMatchObject({ fields: { status: "done" }, tasks: { done: 2, total: 3 } });
});

test("New todo opens the composer on Todo, and the saved todo joins the list", async ({ page }) => {
  // A + in the top bar, on the Todos screen only
  const add = page.locator("header #new");
  const title = `Quokka ${word()} new todo`;
  const other = await page.request.post("/api/captures", {
    data: { id: "01E2ETNEWT0D0".padEnd(26, "0"), text: "Quokka elsewhere" },
  });
  const { slug } = await other.json();
  for (const elsewhere of ["/", "/search", `/p/${slug}`]) {
    await page.goto(elsewhere);
    await expect(page.locator("#view > *")).toBeVisible();
    await expect(add).toBeHidden();
  }
  await page.goto("/todos?view=all");
  await expect(add).toHaveAccessibleName("New todo");
  await expect(add).toBeInViewport(); // in the top bar, however long the list
  expect((await add.boundingBox())?.height).toBeGreaterThanOrEqual(44);
  await add.click();
  const editor = page.locator(".editor");
  await expect(editor.getByRole("radio", { name: "Todo" })).toBeChecked();
  const text = editor.locator("textarea");
  await expect(text).toHaveAttribute("placeholder", "What needs doing?");
  // A link would suggest Later: the kind was chosen, so it stays Todo
  await text.fill(`${title} https://example.com/x`);
  await expect(editor.getByRole("radio", { name: "Todo" })).toBeChecked();
  // Its due date and priority, as on a todo's page (the same fields), folded until opened
  await expect(editor.getByRole("button", { name: "Tomorrow" })).toBeHidden();
  await openFold(editor, "Due");
  await editor.getByRole("button", { name: "Tomorrow" }).click();
  await expect(editor.getByLabel("Due", { exact: true })).toHaveValue(day(1));
  await editor.getByRole("combobox", { name: "Priority" }).selectOption("high");
  await editor.getByRole("radio", { name: "Note" }).check({ force: true });
  await expect(editor.getByLabel("Due", { exact: true })).toBeHidden(); // a note has none
  await editor.getByRole("radio", { name: "Todo" }).check({ force: true });
  await editor.getByRole("button", { name: "Save" }).click();
  await expect(editor).toBeHidden();
  // Back on the list it was opened from, with the todo in it once uploaded
  await expect(page).toHaveURL(/\/todos\?view=all$/);
  const row = page.locator(".list li", { hasText: title });
  await expect(row.locator("a strong")).toBeVisible();
  await expect(row.getByRole("button", { name: new RegExp(`^Done: ${title}`) })).toBeVisible();
  await expect(row.locator(".due")).toHaveText(/^high\s·\sdue\s/);
  const [hit] = await (await page.request.get(`/api/search?q=${encodeURIComponent(title)}`)).json();
  const made = await (await page.request.get(`/api/pages/${hit.slug}`)).json();
  expect(made).toMatchObject({ kind: "todo", due: day(1), priority: "high" });
});

test("a todo uploaded while the Todos list is fetched still joins it", async ({ page }) => {
  // Installed before the screen opens, so no list request escapes them; armed at Save. Then
  // the upload waits a little, so the list fetched as the composer closes is the one from
  // before it, and that answer is held until the upload is done and its queue change has
  // fired: the screen must notice the change it missed. Requests after the upload: as is.
  let armed = false;
  let isIn = false; // the upload is done
  let uploaded = () => {};
  const done = new Promise<void>((ok) => {
    uploaded = ok;
  });
  await page.route("**/api/captures", async (r) => {
    if (!armed) return r.continue();
    await new Promise((ok) => setTimeout(ok, 300));
    await r.fulfill({ response: await r.fetch() });
    isIn = true;
    uploaded();
  });
  await page.route(/\/api\/(search|pages)\?/, async (r) => {
    if (!armed) return r.continue();
    const answer = await r.fetch(); // as the store is now
    if (!isIn) {
      await done; // fetched before the upload: held until it is in
      await new Promise((ok) => setTimeout(ok, 500)); // and its queue change has been sent
    }
    await r.fulfill({ response: answer });
  });
  await page.goto("/todos?view=all");
  await expect(page.locator("header #new")).toBeVisible();
  await page.locator("header #new").click();
  const editor = page.locator(".editor");
  const text = `Wallaroo raced ${word()}`; // words no other spec searches for
  await editor.locator("textarea").fill(text);
  armed = true;
  await editor.getByRole("button", { name: "Save" }).click();
  await expect(editor).toBeHidden();
  await expect(page.locator(".list li", { hasText: text })).toBeVisible({
    timeout: 10_000,
  });
});

test("Mark done on a todo from the Todos screen moves on to the next, with Undo and a way back", async ({
  page,
}) => {
  // Two overdue, side by side in Now (oldest first): on days no other repeat or retry of
  // this test has (up to 3 retries)
  const { repeatEachIndex, retry } = test.info();
  const back = 40 + 3 * (repeatEachIndex * 4 + retry);
  const w = word();
  const [first, second] = [`Dunnart ${w} first`, `Dunnart ${w} second`];
  const a = await todo(page, first, { due: day(-back) });
  const b = await todo(page, second, { due: day(-back + 1) });
  const tools = page.locator(".page .tools");
  await page.goto("/todos");
  await page.locator(".list a", { hasText: first }).click();
  await expect(page.locator(".page h1")).toHaveText(first);
  const where = page.locator("header .pager .at"); // beside Back, which names the list
  await expect(where).toHaveText(/^\d+ of \d+$/);
  const k = Number((await where.textContent())?.split(" ")[0]);
  await expect(page.locator(".pager")).toHaveAttribute("aria-label", "In Todos · Now");
  await tools.getByRole("button", { name: "Mark done" }).click();
  // On to the next, saying so
  await expect(page).toHaveURL(`/p/${b.slug}`);
  await expect(page.locator(".page h1")).toHaveText(second);
  await expect(where).toHaveText(new RegExp(`^${k + 1} of \\d+$`));
  await expect(page.locator(".toast")).toContainText(`Done: ${first}. Next todo, ${k + 1} of`);
  expect((await (await page.request.get(`/api/pages/${a.page_id}`)).json()).fields.status).toBe(
    "done",
  );
  // Undo: open again, and back on it
  await page.locator(".toast").getByRole("button", { name: "Undo" }).click();
  await expect(page).toHaveURL(`/p/${a.slug}`);
  await expect(page.locator(".page h1")).toHaveText(first);
  expect((await (await page.request.get(`/api/pages/${a.page_id}`)).json()).fields.status).toBe(
    "open",
  );
  // The top bar's Back: back to the list
  await page.locator("#back").click();
  await expect(page).toHaveURL(/\/todos$/);
  await expect(page.getByRole("radio", { name: "Now" })).toBeChecked();
  // From elsewhere (a search), Mark done stays on the page
  await page.goto(`/search?q=${encodeURIComponent(second)}`);
  await page.locator(".hits a", { hasText: second }).click();
  await tools.getByRole("button", { name: "Mark done" }).click();
  await expect(tools.getByRole("button", { name: "Reopen" })).toBeVisible();
  await expect(page).toHaveURL(`/p/${b.slug}`);
  await tools.getByRole("button", { name: "Reopen" }).click();
  await expect(tools.getByRole("button", { name: "Mark done" })).toBeVisible();
});

test("Snooze has its own line, with Tomorrow and Next week", async ({ page }) => {
  const t = await todo(page, "Bilby chips", { due: day(0) });
  await page.goto(`/p/${t.slug}`);
  await page.locator(".page .tags .duechip").click();
  const naps = page.getByRole("group", { name: "Snooze for" });
  await expect(naps.getByRole("button")).toHaveText(["No snooze", "Tomorrow", "Next week"]);
  await expect(naps.getByRole("button", { name: "No snooze" })).toHaveAttribute(
    "aria-pressed",
    "true",
  ); // none set yet
  await naps.getByRole("button", { name: "Next week" }).click();
  await expect(page.getByLabel("Snooze until")).toHaveValue(day(7));
  await expect(naps.getByRole("button", { name: "Next week" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  // Below Priority, not beside it
  const pri = await page.getByRole("combobox", { name: "Priority" }).boundingBox();
  const nap = await page.getByLabel("Snooze until").boundingBox();
  expect(nap && pri && nap.y > pri.y + pri.height - 1).toBe(true);
  await page.getByRole("button", { name: "Save" }).click();
  // Snoozed past today's due date: Move due date takes the due date to the snooze's day
  await page
    .getByRole("group", { name: "Due date" })
    .getByRole("button", { name: "Move due date" })
    .click();
  await expect(page.locator(".page > .meta")).toContainText("snoozed till");
  const saved = await (await page.request.get(`/api/pages/${t.page_id}`)).json();
  expect([saved.due, saved.snoozed_until]).toEqual([day(7), day(7)]);
});

test("a snooze on or before the due date saves without asking", async ({ page }) => {
  const t = await todo(page, "Bilby no ask", { due: day(9) });
  await page.goto(`/p/${t.slug}`);
  await page.locator(".page .tags .duechip").click();
  await page.getByLabel("Snooze until").fill(day(2));
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".page > .meta")).toContainText("snoozed till");
  await expect(page.getByRole("group", { name: "Due date" })).toHaveCount(0);
  expect((await (await page.request.get(`/api/pages/${t.page_id}`)).json()).due).toBe(day(9));
});

test("a todo's row has no thumbnail, every title in line; a photo is a mark on its line", async ({
  page,
}) => {
  // A 1x1 PNG: the todo has a photo, so its row would have had a thumbnail
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
    "base64",
  );
  const title = `Quokka ${word()} photo todo`; // the newest: at the top of All
  const r = await page.request.post("/api/captures", {
    multipart: {
      id: ulid(),
      text: title,
      kind: "todo",
      file: { name: "w.png", mimeType: "image/png", buffer: png },
    },
  });
  expect(r.ok()).toBeTruthy();
  await page.goto("/todos?view=all");
  const row = page.locator(".todos .list li", { hasText: title });
  await expect(row.locator("a strong")).toBeVisible();
  await expect(row.locator("a > img")).toBeHidden();
  const plain = page.locator(".todos .list li").filter({ hasNotText: "Quokka" }).first();
  const x = async (l: typeof row) => (await l.locator("a strong").boundingBox())?.x;
  // In line with the rest (both measured as drawn: other runs' todos may draw the list again)
  const apart = async () => {
    const [at, by] = [await x(row), await x(plain)];
    return at === undefined || by === undefined ? "not drawn" : at - by;
  };
  await expect.poll(apart).toBe(0);
  const mark = await row
    .locator(".sub")
    .evaluate((el) => getComputedStyle(el, "::after").getPropertyValue("mask-image"));
  expect(mark).toContain("svg");
  // Search still shows it
  await page.goto(`/search?q=${encodeURIComponent(title)}`);
  await expect(page.locator(".list li", { hasText: title }).locator("img")).toBeVisible();
});

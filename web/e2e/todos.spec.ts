// The Todos screen: Now (overdue, today, high priority with no date, then the rest; done
// ones folded away), Upcoming and All, the switch in the address, and its rows' tick.
import { expect, type Page, test } from "@playwright/test";
import { lowContrast } from "./contrast";
import { openFold } from "./panel";

/** A day from today on this machine's calendar (the server's too), as YYYY-MM-DD. */
const day = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
};

let n = 0;
async function todo(page: Page, text: string, extra: Record<string, string> = {}) {
  const id = `01E2ETDNW${String(++n).padStart(2, "0")}`.padEnd(26, "0");
  const r = await page.request.post("/api/captures", {
    data: { id, text, kind: "todo", ...extra },
  });
  expect(r.ok()).toBeTruthy();
  return (await r.json()) as { page_id: string; slug: string };
}

const made: Record<string, { page_id: string; slug: string }> = {};
test.beforeAll(async ({ request }) => {
  const page = { request } as Page;
  // Made in an order unlike the ranking, so last-edited order can't pass for it
  made.rest = await todo(page, "Quoll later none");
  made.soonMedium = await todo(page, "Quoll later medium", { due: day(3), priority: "medium" });
  made.lateNew = await todo(page, "Quoll late new", { due: day(-1), priority: "high" });
  made.todayLow = await todo(page, "Quoll today low", { due: day(0), priority: "low" });
  made.high = await todo(page, "Quoll high no date", { priority: "high" });
  made.lateOld = await todo(page, "Quoll late old", { due: day(-5), priority: "low" });
  made.todayHigh = await todo(page, "Quoll today high", { due: day(0), priority: "high" });
  made.farHigh = await todo(page, "Quoll later high", { due: day(10), priority: "high" });
  made.done = await todo(page, "Quoll done", { due: day(-3) });
  await request.patch(`/api/pages/${made.done.page_id}`, { data: { fields: { status: "done" } } });
});

/** The Quoll rows shown, in order (others' todos share the store). */
const quolls = async (page: Page, scope = ".todos > div > :is(section, ul) li") =>
  (await page.locator(`${scope} a strong`).allTextContents()).filter((t) => t.startsWith("Quoll"));

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
      "Quoll late old",
      "Quoll late new",
      "Quoll today high",
      "Quoll today low",
      "Quoll high no date",
      "Quoll later high",
      "Quoll later medium",
      "Quoll later none",
    ]);
  const section = (name: string) => page.getByRole("region", { name: new RegExp(`^${name}`) });
  await expect(section("Overdue").getByText("Quoll late old")).toBeVisible();
  await expect(section("Today").getByText("Quoll today high")).toBeVisible();
  // Each row says its priority and due date first; overdue in words (and red)
  const late = page.locator(".list li", { hasText: "Quoll late old" }).locator(".due");
  await expect(late).toHaveText(/^low · overdue /);
  await expect(late).toHaveClass("due late");
  // Done: folded away at the end
  const fold = page.locator(".donefold");
  await expect(fold.getByText("Quoll done")).toBeHidden();
  await fold.locator("summary").click();
  await expect(fold.getByText("Quoll done")).toBeVisible();
  // The rows tick like the search screen's
  const row = page.locator(".list li", { hasText: "Quoll today low" });
  await row.getByRole("button", { name: "Done: Quoll today low" }).click();
  await expect(row.locator("em")).toHaveText("done");
  await row.getByRole("button", { name: "Done: Quoll today low" }).click();
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
  // Due from tomorrow to a week away: not "Quoll later high", due in 10 days
  await expect.poll(() => quolls(page)).toEqual(["Quoll later medium"]);
  await expect(page.locator(".todos .count")).toHaveText(/ due in the next 7 days$/);
  await expect(page.getByRole("combobox", { name: "Sort" })).toHaveCount(0); // the view's order
  await page.getByText("All", { exact: true }).click();
  await expect(page).toHaveURL(/\/todos\?view=all$/);
  const all = await quolls(page, ".todos ul li");
  expect(all[0]).toBe("Quoll done"); // last edited first, done ones too
  expect(all).toHaveLength(9);
  // Two lines on every tab: what to do and when, never when it was last edited
  const edited = page.locator(".todos .list li .sub > small:not([class])");
  expect(await edited.count()).toBeGreaterThan(0);
  for (const s of await edited.all()) await expect(s).toBeHidden();
  await page.reload();
  await expect(page.getByRole("radio", { name: "All" })).toBeChecked();
  // A page opened from the list steps through it, and Back comes back to the same view
  await page.getByText("Upcoming", { exact: true }).click();
  await page.locator(".list a", { hasText: "Quoll later medium" }).click();
  await expect(page.locator(".pager")).toContainText("Todos · Upcoming");
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
  await expect(page.locator(".list li em").first()).toBeVisible();
  for (const chip of await page.locator(".list li em").allTextContents())
    expect(["todo", "done", "cancelled"]).toContain(chip); // todos only
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
  const q = encodeURIComponent("kind:todo due:<=today -is:done -is:cancelled");
  const due = async () =>
    (await (await page.request.get(`/api/search/facets?q=${q}`)).json()).total as number;
  await page.goto("/");
  await expect(page.locator("nav a")).toHaveText(["Capture", /Todos$/, "Search"]);
  const n = await due();
  expect(n).toBeGreaterThanOrEqual(4); // the Quolls: two overdue, two today
  await expect(badge).toHaveText(String(n));
  await expect(tab).toHaveAccessibleName(`Todos, ${n} due`);
  expect((await tab.boundingBox())?.height).toBeGreaterThanOrEqual(44);
  await tab.click();
  await expect(page).toHaveURL(/\/todos$/);
  await expect(tab).toHaveAttribute("aria-current");
  await expect(page.getByRole("radio", { name: "Now" })).toBeChecked();
  // Ticking one off counts down at once, and back up
  const tick = page.getByRole("button", { name: "Done: Quoll today high" });
  await tick.click();
  await expect(badge).toHaveText(String(n - 1));
  await tick.click();
  await expect(badge).toHaveText(String(n));
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
  const t = await todo(page, "Bilby snooze me", { due: day(-1), priority: "high" });
  const inNow = () => page.locator(".todos .list a strong", { hasText: "Bilby snooze me" });
  const badgeQ = encodeURIComponent("kind:todo due:<=today -is:done -is:cancelled -is:snoozed");
  const counted = async () =>
    (
      (await (await page.request.get(`/api/search?q=${badgeQ}&limit=100`)).json()) as {
        title: string;
      }[]
    ).some((h) => h.title === "Bilby snooze me");
  await page.goto("/todos");
  await expect(inNow()).toBeVisible();
  expect(await counted()).toBe(true);
  await page.goto(`/p/${t.slug}`);
  const line = page.locator(".todoline > button");
  await line.click();
  await page.getByLabel("Snooze until").fill(day(1));
  await page.getByRole("button", { name: "Save" }).click();
  await expect(line).toHaveText(/ · snoozed till /);
  expect((await (await page.request.get(`/api/pages/${t.page_id}`)).json()).snoozed_until).toBe(
    day(1),
  );
  expect(await counted()).toBe(false); // the Todos tab's count leaves it out
  await page.goto("/todos");
  // "1 snoozed" links to a search of them (open ones only: is:snoozed skips done ones)
  const asleep = page.locator(".todos .count a");
  await expect(asleep).toHaveText(/^\d+ snoozed$/);
  await expect(inNow()).toHaveCount(0);
  await asleep.click();
  await expect(page).toHaveURL(/\/search\?q=kind%3Atodo(%20|\+)is%3Asnoozed(%20|\+)sort%3Adue$/);
  await expect(page.locator(".hits li", { hasText: "Bilby snooze me" })).toBeVisible();
  await page.goto("/todos");
  await page.getByText("All", { exact: true }).click();
  const row = page.locator(".list li", { hasText: "Bilby snooze me" });
  await expect(row.locator(".due")).toHaveText(/^high · overdue .* · snoozed till /);
  // Woken by hand: back in Now
  await row.locator("a").click();
  await line.click();
  await page.getByRole("button", { name: "No snooze" }).click();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(line).not.toHaveText(/snoozed/);
  await page.goto("/todos");
  await expect(inNow()).toBeVisible();
});

test("task boxes drive a todo: filed as one, 2 of 3 on its row, done with the last box", async ({
  page,
}) => {
  const id = "01E2ETASKS01".padEnd(26, "0");
  const text = "Kowari trip\n\n- [x] tickets\n- [ ] tent\n- [ ] stove";
  const made = await (await page.request.post("/api/captures", { data: { id, text } })).json();
  const api = async () => (await page.request.get(`/api/pages/${made.page_id}`)).json();
  expect(await api()).toMatchObject({ kind: "todo", tasks: { done: 1, total: 3 } }); // a note: filed
  await page.goto("/todos?view=all");
  const row = page.locator(".list li", { hasText: "Kowari trip" });
  await expect(row.locator(".due")).toHaveText("1 of 3");
  const tick = row.getByRole("button", { name: /^Done: Kowari trip/ });
  await expect(tick).toHaveAttribute("aria-pressed", "mixed");
  // Ticked in place on its page: the last box makes it done; one unticked opens it again
  await row.locator("a").click();
  const boxes = page.locator(".page .md li.task input");
  const tools = page.locator(".page > .tools");
  await boxes.nth(1).click();
  await expect(page.locator(".todoline > button")).toHaveText(/2 of 3/);
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
  const other = await page.request.post("/api/captures", {
    data: { id: "01E2ETNEWT0D0".padEnd(26, "0"), text: "Quokka elsewhere" },
  });
  const { slug } = await other.json();
  for (const elsewhere of ["/", "/search", `/p/${slug}`, "/tags"]) {
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
  await text.fill("Quokka new todo https://example.com/x");
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
  const row = page.locator(".list li", { hasText: "Quokka new todo" });
  await expect(row.locator("a strong")).toBeVisible();
  await expect(row.getByRole("button", { name: /^Done: Quokka new todo/ })).toBeVisible();
  await expect(row.locator(".due")).toHaveText(/^high · due /);
  const [hit] = await (await page.request.get("/api/search?q=quokka+new+todo")).json();
  const made = await (await page.request.get(`/api/pages/${hit.slug}`)).json();
  expect(made).toMatchObject({ kind: "todo", due: day(1), priority: "high" });
});

test("Mark done on a todo from the Todos screen moves on to the next, with Undo and a way back", async ({
  page,
}) => {
  // The two oldest overdue: first in Now
  const a = await todo(page, "Dunnart first", { due: day(-40) });
  const b = await todo(page, "Dunnart second", { due: day(-39) });
  const tools = page.locator(".page .tools");
  await page.goto("/todos");
  await page.locator(".list a", { hasText: "Dunnart first" }).click();
  await expect(page.locator(".page h1")).toHaveText("Dunnart first");
  const where = page.locator(".pager .at"); // a label: Back is in the top bar
  await expect(where).toHaveText(/^1 of \d+ · Todos · Now$/);
  await tools.getByRole("button", { name: "Mark done" }).click();
  // On to the next, saying so
  await expect(page).toHaveURL(`/p/${b.slug}`);
  await expect(page.locator(".page h1")).toHaveText("Dunnart second");
  await expect(where).toHaveText(/^2 of \d+ · Todos · Now$/);
  await expect(page.locator(".toast")).toContainText("Done: Dunnart first. Next todo, 2 of");
  expect((await (await page.request.get(`/api/pages/${a.page_id}`)).json()).fields.status).toBe(
    "done",
  );
  // Undo: open again, and back on it
  await page.locator(".toast").getByRole("button", { name: "Undo" }).click();
  await expect(page).toHaveURL(`/p/${a.slug}`);
  await expect(page.locator(".page h1")).toHaveText("Dunnart first");
  expect((await (await page.request.get(`/api/pages/${a.page_id}`)).json()).fields.status).toBe(
    "open",
  );
  // The top bar's Back: back to the list
  await page.locator("#back").click();
  await expect(page).toHaveURL(/\/todos$/);
  await expect(page.getByRole("radio", { name: "Now" })).toBeChecked();
  // From elsewhere (a search), Mark done stays on the page
  await page.goto("/search?q=dunnart+second");
  await page.locator(".hits a", { hasText: "Dunnart second" }).click();
  await tools.getByRole("button", { name: "Mark done" }).click();
  await expect(tools.getByRole("button", { name: "Reopen" })).toBeVisible();
  await expect(page).toHaveURL(`/p/${b.slug}`);
  await tools.getByRole("button", { name: "Reopen" }).click();
  await expect(tools.getByRole("button", { name: "Mark done" })).toBeVisible();
});

test("Snooze has its own line, with Tomorrow and Next week", async ({ page }) => {
  const t = await todo(page, "Bilby chips", { due: day(0) });
  await page.goto(`/p/${t.slug}`);
  await page.locator(".todoline > button").click();
  const naps = page.getByRole("group", { name: "Snooze for" });
  await expect(naps.getByRole("button")).toHaveText(["Tomorrow", "Next week"]);
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
  await expect(page.locator(".todoline > button")).toHaveText(/ · snoozed till /);
});

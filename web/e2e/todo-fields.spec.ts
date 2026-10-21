// A todo's due date and priority (#104): set on its page and in the editor, shown on its row
// (overdue in red until done), and a todo search's orders and typed due: searches.
import { expect, type Page, test } from "@playwright/test";
import { lowContrast } from "./contrast";

/** A day from today on this machine's calendar (the server's too), as YYYY-MM-DD. */
const day = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
};

let n = 0;
async function todo(page: Page, text: string, extra: Record<string, string> = {}) {
  const id = `01E2ETD${String(++n).padStart(2, "0")}`.padEnd(26, "0");
  const r = await page.request.post("/api/captures", {
    data: { id, text, kind: "todo", ...extra },
  });
  expect(r.ok()).toBeTruthy();
  return (await r.json()) as { page_id: string; slug: string };
}
const api = async (page: Page, id: string) =>
  (await (await page.request.get(`/api/pages/${id}`)).json()) as {
    due: string | null;
    priority: string | null;
  };
/** Open the search screen's Filters sheet. */
async function filters(page: Page) {
  await page.getByRole("button", { name: /^Filters/ }).click();
  return page.getByRole("dialog", { name: "Filters" });
}
const hits = (page: Page) => page.locator(".hits li a strong");
const rowOf = (page: Page, title: string) => page.locator(".list li").filter({ hasText: title });

const made: Record<string, { page_id: string; slug: string }> = {};
test.beforeAll(async ({ request }) => {
  const page = { request } as Page;
  made.late = await todo(page, "Numbat late", { due: day(-3), priority: "high" });
  made.today = await todo(page, "Numbat today", { due: day(0), priority: "low" });
  made.soon = await todo(page, "Numbat soon", { due: day(5) });
  made.none = await todo(page, "Numbat none", { priority: "medium" });
  made.done = await todo(page, "Numbat done", { due: day(-2) });
  await request.patch(`/api/pages/${made.done.page_id}`, { data: { fields: { status: "done" } } });
});

test("rows show priority and due date, overdue until ticked done", async ({ page }) => {
  await page.goto("/search?q=numbat+kind%3Atodo");
  await expect(hits(page)).toHaveCount(5);
  const late = rowOf(page, "Numbat late").locator(".due");
  await expect(late).toHaveText(/^high · overdue /);
  await expect(late).toHaveClass("due late");
  await expect(rowOf(page, "Numbat today").locator(".due")).toHaveText("low · due today");
  await expect(rowOf(page, "Numbat none").locator(".due")).toHaveText("medium");
  const done = rowOf(page, "Numbat done").locator(".due");
  await expect(done).toHaveText(/^due \D*\d/); // done: its date kept, no longer overdue
  await expect(done).toHaveClass("due closed"); // and greyed
  await rowOf(page, "Numbat late").getByRole("button", { name: "Done: Numbat late" }).click();
  await expect(late).toHaveClass("due closed");
  await expect(late).toHaveText(/^high · due /);
  await rowOf(page, "Numbat late").getByRole("button", { name: "Done: Numbat late" }).click();
  await expect(late).toHaveClass("due late");
});

test("a todo search: its orders in Filters, and due: typed (no due views there)", async ({
  page,
}) => {
  await page.goto("/search?q=numbat+kind%3Atodo");
  const box = page.getByRole("searchbox");
  const sheet = await filters(page);
  await expect(sheet.getByRole("region", { name: "Due" })).toHaveCount(0); // the Todos screen has them
  await expect(sheet.getByRole("button", { name: "Overdue" })).toHaveCount(0);
  // A todo search's own orders
  const sort = sheet.getByRole("combobox", { name: "Sort" });
  await expect(hits(page)).toHaveCount(5);
  await sort.selectOption({ label: "Priority" });
  await expect(box).toHaveValue("numbat kind:todo sort:priority");
  await expect(hits(page).first()).toHaveText("Numbat late");
  await sort.selectOption({ label: "Due soonest" });
  await expect(hits(page)).toHaveText([
    "Numbat late",
    "Numbat done",
    "Numbat today",
    "Numbat soon",
    "Numbat none",
  ]);
  // Typed, the views' filters still work
  await page.goto("/search?q=numbat+kind%3Atodo+due%3A%3Ctoday+-is%3Adone");
  await expect(hits(page)).toHaveText(["Numbat late"]);
  await page.goto("/search?q=numbat+kind%3Atodo+due%3Atoday");
  await expect(hits(page)).toHaveText(["Numbat today"]);
  await page.goto("/search?q=numbat+kind%3Atodo+due%3A%3Etoday+-is%3Adone");
  await expect(hits(page)).toHaveText(["Numbat soon"]);
  expect(await box.inputValue()).toBe("numbat kind:todo due:>today -is:done");
});

test("due date and priority are set and cleared on a todo's page", async ({ page }) => {
  await page.goto(`/p/${made.none.slug}`);
  const line = page.locator(".todoline > button");
  await expect(line).toHaveText("medium");
  await line.click();
  const due = page.getByLabel("Due", { exact: true });
  await expect(due).toBeFocused();
  await due.fill(day(-1));
  await page.getByRole("combobox", { name: "Priority" }).selectOption("high");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(line).toHaveText(/^high · overdue /);
  await expect(line).toBeFocused(); // back where it was
  expect(await api(page, made.none.page_id)).toMatchObject({ due: day(-1), priority: "high" });
  await line.click();
  await page.getByRole("button", { name: "No date" }).click();
  await page.getByRole("combobox", { name: "Priority" }).selectOption("");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(line).toHaveText("Add due date");
  expect(await api(page, made.none.page_id)).toMatchObject({ due: null, priority: null });
  await line.click();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(line).toBeFocused();
  // Not a todo: no line
  const note = await page.request.post("/api/captures", {
    data: { id: "01E2ETDNTE".padEnd(26, "0"), text: "Numbat note" },
  });
  await page.goto(`/p/${(await note.json()).slug}`);
  await expect(page.locator(".page h1")).toHaveText("Numbat note");
  await expect(page.locator(".todoline")).toHaveCount(0);
});

test("Today, Tomorrow and Next week set the due date in one tap", async ({ page }) => {
  await page.goto(`/p/${made.soon.slug}`);
  const line = page.locator(".todoline > button");
  await line.click();
  const due = page.getByLabel("Due", { exact: true });
  const chips = page.getByRole("group", { name: "Due soon" });
  const pressed = () => chips.locator('[aria-pressed="true"]').allTextContents();
  await expect(chips.getByRole("button")).toHaveText(["Today", "Tomorrow", "Next week"]);
  await expect.poll(pressed).toEqual([]); // due in 5 days: none of them
  await chips.getByRole("button", { name: "Tomorrow" }).click();
  await expect(due).toHaveValue(day(1));
  await expect.poll(pressed).toEqual(["Tomorrow"]);
  await chips.getByRole("button", { name: "Next week" }).click();
  await expect(due).toHaveValue(day(7));
  await expect.poll(pressed).toEqual(["Next week"]);
  await due.fill(day(3)); // another day: none pressed
  await expect.poll(pressed).toEqual([]);
  await chips.getByRole("button", { name: "Today" }).click();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(line).toHaveText("due today");
  expect(await api(page, made.soon.page_id)).toMatchObject({ due: day(0) });
  // Opened again on today: Today pressed
  await line.click();
  await expect.poll(pressed).toEqual(["Today"]);
  await page.getByRole("button", { name: "Cancel" }).click();
  await page.request.patch(`/api/pages/${made.soon.page_id}`, { data: { due: day(5) } });
});

test("a done todo's page keeps its due date greyed, and offers no date when it has none", async ({
  page,
}) => {
  await page.goto(`/p/${made.done.slug}`);
  await expect(page.locator(".todoline > button span")).toHaveClass("due closed");
  await expect(page.locator(".todoline > button")).toHaveText(/^due \D*\d/);
  const bare = await todo(page, "Numbat bare");
  await page.request.patch(`/api/pages/${bare.page_id}`, { data: { fields: { status: "done" } } });
  await page.goto(`/p/${bare.slug}`);
  await expect(page.locator(".page h1")).toHaveText("Numbat bare");
  await expect(page.locator(".todoline")).toHaveCount(0); // no "Add due date": Reopen it first
});

test("the editor sets them while the kind is Todo", async ({ page }) => {
  await page.goto(`/p/${made.soon.slug}`);
  await page.locator(".page .tools").getByRole("button", { name: "Edit" }).click();
  const editor = page.locator(".editor");
  const due = editor.getByLabel("Due", { exact: true });
  await expect(due).toHaveValue(day(5));
  await editor.getByRole("radio", { name: "Note" }).check({ force: true });
  await expect(due).toBeHidden();
  await editor.getByRole("radio", { name: "Todo" }).check({ force: true });
  await due.fill(day(1));
  await editor.getByRole("combobox", { name: "Priority" }).selectOption("medium");
  await editor.getByRole("button", { name: "Save" }).click();
  await expect(editor).toBeHidden();
  await expect(page.locator(".todoline > button")).toHaveText(/^medium · due /);
  expect(await api(page, made.soon.page_id)).toMatchObject({ due: day(1), priority: "medium" });
});

test("the todo views meet AA contrast, in both themes", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    await page.goto("/search?q=numbat+kind%3Atodo");
    await expect(rowOf(page, "Numbat late").locator(".due.late")).toBeVisible();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} rows`).toEqual([]);
    await filters(page);
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} filters`).toEqual([]);
    await expect(rowOf(page, "Numbat done").locator(".due.closed")).toBeVisible();
    await page.goto(`/p/${made.late.slug}`);
    await expect(page.locator(".todoline .late")).toBeVisible();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} page`).toEqual([]);
    await page.locator(".todoline > button").click();
    await expect(page.getByLabel("Due", { exact: true })).toBeVisible();
    await page
      .getByRole("group", { name: "Due soon" })
      .getByRole("button", { name: "Today" })
      .click();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} form`).toEqual([]);
    await page.goto(`/p/${made.done.slug}`);
    await expect(page.locator(".todoline .closed")).toBeVisible();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} done page`).toEqual([]);
  }
});

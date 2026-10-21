// A todo's due date and priority (#104): set on its page and in the editor, shown on its row
// (overdue in red until done), and the Todos screen's views Today, Overdue and Upcoming.
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
const refine = (page: Page) => page.getByRole("group", { name: "Refine" });
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
  await expect(done).toHaveText(/^due /); // done: no longer overdue
  await expect(done).toHaveClass("due");
  await rowOf(page, "Numbat late").getByRole("button", { name: "Done: Numbat late" }).click();
  await expect(late).toHaveClass("due");
  await expect(late).toHaveText(/^high · due /);
  await rowOf(page, "Numbat late").getByRole("button", { name: "Done: Numbat late" }).click();
  await expect(late).toHaveClass("due late");
});

test("the Todos screen's views: Today, Overdue, Upcoming", async ({ page }) => {
  await page.goto("/search?q=kind%3Atodo");
  const box = page.getByRole("searchbox");
  await refine(page).getByRole("button", { name: "Overdue" }).click();
  await expect(box).toHaveValue("kind:todo due:<today -is:done -is:cancelled sort:due");
  await expect(hits(page)).toHaveText(["Numbat late"]); // not the done one
  await expect(refine(page).getByRole("button", { name: "Overdue" })).toHaveClass(/\bon\b/);
  await expect(refine(page).getByRole("button", { name: /^Remove/ })).toHaveCount(0);
  await expect(refine(page).getByRole("combobox", { name: "Sort" })).toHaveValue("sort:due");
  await refine(page).getByRole("button", { name: "Today" }).click();
  await expect(box).toHaveValue("kind:todo due:today -is:done -is:cancelled sort:due");
  await expect(hits(page)).toHaveText(["Numbat today"]);
  await refine(page).getByRole("button", { name: "Upcoming" }).click();
  await expect(hits(page)).toHaveText(["Numbat soon"]);
  await refine(page).getByRole("button", { name: "Upcoming" }).click(); // again: cleared
  await expect(box).toHaveValue("kind:todo");
  // The Todos screen's own orders
  const sort = refine(page).getByRole("combobox", { name: "Sort" });
  await box.fill("numbat kind:todo");
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
  await page.goto("/search?q=numbat");
  await expect(refine(page).getByRole("button", { name: "Overdue" })).toHaveCount(0); // todos only
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
    await expect(refine(page).getByRole("button", { name: "Overdue" })).toBeVisible();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} rows`).toEqual([]);
    await page.goto(`/p/${made.late.slug}`);
    await expect(page.locator(".todoline .late")).toBeVisible();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} page`).toEqual([]);
    await page.locator(".todoline > button").click();
    await expect(page.getByLabel("Due", { exact: true })).toBeVisible();
    expect(await page.evaluate(lowContrast, ""), `${colorScheme} form`).toEqual([]);
  }
});

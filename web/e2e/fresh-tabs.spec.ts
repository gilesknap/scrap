// Two tabs of one browser: a fresh capture open in one is not "recovered" by the other (#139).
import { expect, type Page, test } from "@playwright/test";

const row = (p: Page) => p.locator(".capture .draft");
const draft = (p: Page, first: string) => row(p).getByRole("button", { name: `Draft: ${first}` });
const text = (p: Page) => p.getByPlaceholder("Note or link");

/** The fresh captures' drafts kept in IndexedDB (fresh.ts): their texts. */
const freshTexts = (p: Page) =>
  p.evaluate(
    () =>
      new Promise<string[]>((ok, fail) => {
        const req = indexedDB.open("scrap");
        req.onerror = () => fail(req.error);
        req.onsuccess = () => {
          const all = req.result
            .transaction("drafts")
            .objectStore("drafts")
            .getAll(IDBKeyRange.bound("new-fresh", "new-fresh\uffff"));
          all.onsuccess = () => {
            ok(all.result.map((d: { text: string }) => d.text));
            req.result.close();
          };
        };
      }),
  );

/** Keep a draft (Back with it typed), then open a fresh capture over it and type. */
async function keptAndFresh(p: Page, kept: string, typed: string) {
  await p.goto("/");
  await p.getByRole("button", { name: "Note" }).click();
  await text(p).fill(kept);
  await p.goBack();
  await expect(draft(p, kept)).toBeVisible();
  await p.getByRole("button", { name: "Note" }).click();
  await text(p).fill(typed);
  await expect.poll(() => freshTexts(p)).toContain(typed); // kept a moment after typing
}

test("a fresh capture open in one tab is left alone by another, and Back and Undo work in both", async ({
  page: a,
  context,
}) => {
  await keptAndFresh(a, "Kept in A", "Typing in A");

  // Tab B opens Capture: the kept draft is as it was, nothing recovered
  const b = await context.newPage();
  await b.goto("/");
  await expect(draft(b, "Kept in A")).toBeVisible();
  await expect(b.locator(".toast", { hasText: "Recovered" })).toHaveCount(0);
  await expect(draft(b, "Kept in A")).toBeVisible();

  // B's own fresh capture, on a key of its own: Back puts it in the kept one's place, Undo back
  await b.getByRole("button", { name: "Note" }).click();
  await expect(text(b)).toHaveValue("");
  await text(b).fill("Typing in B");
  await b.goBack();
  await expect(draft(b, "Typing in B")).toBeVisible();
  await b
    .locator(".toast", { hasText: "in place of the older one" })
    .getByRole("button", { name: "Undo" })
    .click();
  await expect(draft(b, "Kept in A")).toBeVisible();

  // A's composer still has its text; its Back and Undo give back the kept draft, not a stale one
  await expect(text(a)).toHaveValue("Typing in A");
  await a.goBack();
  await expect(draft(a, "Typing in A")).toBeVisible();
  await a
    .locator(".toast", { hasText: "in place of the older one" })
    .getByRole("button", { name: "Undo" })
    .click();
  await expect(draft(a, "Kept in A")).toBeVisible();

  // Nothing left over for either tab to recover later
  await b.reload();
  await expect(draft(b, "Kept in A")).toBeVisible();
  await expect.poll(() => freshTexts(b)).toEqual([]);
  await expect(b.locator(".toast", { hasText: "Recovered" })).toHaveCount(0);
});

test("a tab closed mid-capture lets go of its fresh draft: the next tab recovers it", async ({
  page: a,
  context,
}) => {
  await keptAndFresh(a, "Kept older", "Closed mid-capture");
  await a.close(); // the browser lets go of its lock
  const b = await context.newPage();
  await b.goto("/");
  await expect(draft(b, "Closed mid-capture")).toBeVisible();
  await b
    .locator(".toast", { hasText: "Recovered your unsaved capture, in place of the older draft" })
    .getByRole("button", { name: "Undo" })
    .click();
  await expect(draft(b, "Kept older")).toBeVisible();
});

test("with no Web Locks (older browsers), another tab recovers a fresh draft as before", async ({
  page: a,
  context,
}) => {
  await context.addInitScript(() => {
    delete (Navigator.prototype as { locks?: unknown }).locks;
  });
  await keptAndFresh(a, "Kept no locks", "Fresh no locks");
  expect(await a.evaluate(() => "locks" in navigator)).toBe(false);
  const b = await context.newPage();
  await b.goto("/");
  await expect(draft(b, "Fresh no locks")).toBeVisible();
  await expect(
    b.locator(".toast", { hasText: "Recovered your unsaved capture, in place of the older draft" }),
  ).toBeVisible();
});

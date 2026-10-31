// Ticking off todos and Reads: the tick on a list row (beside its link, so tapping it neither
// opens the page nor swipes the row) and Done / Reopen on the page, for every status.
import { expect, type Page, test } from "@playwright/test";
import { ulid } from "./helpers";

/** A new page of that kind (and status), newest in Recent: [its title, slug, id]. */
async function make(page: Page, kind: string, status?: string) {
  const title = `Tick ${kind} ${status ?? ""} ${ulid().slice(-6)}`;
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text: title, kind } });
  const { slug, page_id } = await r.json();
  if (status) await page.request.patch(`/api/pages/${page_id}`, { data: { fields: { status } } });
  return [title, slug as string, page_id as string] as const;
}

const statusOf = async (page: Page, id: string) =>
  (await (await page.request.get(`/api/pages/${id}`)).json()).fields.status;

test("a todo's row ticks off in place: no page opens, no swipe; keys too", async ({ page }) => {
  const [title, slug, id] = await make(page, "todo");
  await page.goto("/recent");
  const row = page.locator(".list li").filter({ has: page.locator(`a[href="/p/${slug}"]`) });
  const tick = row.getByRole("button", { name: `Done: ${title}` });
  await expect(tick).toHaveAttribute("aria-pressed", "false");
  await expect(row.locator("em")).toHaveCount(0); // open: no chip (its icon says todo)

  await tick.tap(); // a finger
  await expect(tick).toHaveAttribute("aria-pressed", "true");
  await expect(row.locator("em")).toHaveText("done");
  expect(await statusOf(page, id)).toBe("done");
  await page.waitForTimeout(300);
  await expect(page).toHaveURL("/search");
  await expect(row).not.toHaveClass(/to-edit|to-delete|armed/);
  await expect(row.locator("a")).not.toHaveAttribute("style", /translate/);

  // A drag that starts on the tick swipes the row (all of it moves), never ticks it
  const cdp = await page.context().newCDPSession(page);
  const box = await tick.boundingBox();
  if (!box) throw new Error("no tick");
  const y = box.y + box.height / 2;
  const x0 = box.x + box.width / 2;
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: x0, y }] });
  for (const dx of [-10, -20, -30, -40]) {
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [{ x: x0 + dx, y }],
    });
    await page.waitForTimeout(120); // slow and short: settles back
  }
  await expect(tick).toHaveAttribute("style", /translateX\(-/); // it moved with the row
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await expect(row.locator("a")).not.toHaveAttribute("style", /translate/);
  await page.waitForTimeout(300);
  await expect(tick).toHaveAttribute("aria-pressed", "true");
  expect(await statusOf(page, id)).toBe("done");

  // The keyboard: Tab from the row's link to its tick, Space reopens it, Enter ticks it again
  await row.locator("a").focus();
  await page.keyboard.press("Tab");
  await expect(tick).toBeFocused();
  await page.keyboard.press("Space");
  await expect(tick).toHaveAttribute("aria-pressed", "false");
  await expect(row.locator("em")).toHaveCount(0);
  expect(await statusOf(page, id)).toBe("open");
  await page.keyboard.press("Enter");
  await expect(tick).toHaveAttribute("aria-pressed", "true");
  await expect(page).toHaveURL("/search");

  // The row itself still opens its page
  await row.locator("strong").click();
  await expect(page).toHaveURL(`/p/${slug}`);
  await expect(page.getByRole("button", { name: "Reopen" })).toBeVisible();
});

test("ticks on Read rows and search results; none on notes", async ({ page }) => {
  const [title, , id] = await make(page, "consume", "cancelled");
  const [noteTitle] = await make(page, "note");
  await page.goto("/recent");
  const row = page.locator(".list li").filter({ hasText: title });
  await expect(row.locator("em")).toHaveText("cancelled");
  await expect(row).toHaveClass(/\bcancelled\b/); // struck, a grey dash in its box
  const tick = row.getByRole("button", { name: `Done: ${title}` });
  await expect(tick).toHaveAttribute("aria-pressed", "false");
  await expect(
    page.locator(".list li").filter({ hasText: noteTitle }).locator(".tick"),
  ).toHaveCount(0);

  await page.goto(`/search?q=${encodeURIComponent(title)}`);
  const hit = page.locator(".hits li").filter({ hasText: title });
  await hit.getByRole("button", { name: `Done: ${title}` }).tap();
  await expect(hit.getByRole("button", { name: `Done: ${title}` })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(await statusOf(page, id)).toBe("done");
  await expect(page).toHaveURL(/\/search/);
});

test("a page offers Mark done while open, only Reopen once done or cancelled", async ({ page }) => {
  const tools = page.locator(".page > .tools");
  const offered = () =>
    tools.getByRole("button", { name: /^(Mark done|Reopen)$/ }).allTextContents();

  const [, busy, busyId] = await make(page, "todo", "in_progress");
  await page.goto(`/p/${busy}`);
  await expect.poll(offered).toEqual(["Mark done"]);
  await tools.getByRole("button", { name: "Mark done" }).click();
  await expect.poll(offered).toEqual(["Reopen"]);
  expect(await statusOf(page, busyId)).toBe("done");

  const [, gone, goneId] = await make(page, "todo", "cancelled");
  await page.goto(`/p/${gone}`);
  await expect.poll(offered).toEqual(["Reopen"]); // a cancelled one looks closed
  await expect
    .poll(() => page.locator(".page > .meta .parts > *").allInnerTexts())
    .toEqual(["Todo", "cancelled"]);
  await page.setViewportSize({ width: 320, height: 700 }); // its tools still fit
  await page.screenshot({ path: test.info().outputPath("cancelled-320.png") });
  await tools.getByRole("button", { name: "Reopen" }).click();
  await expect.poll(offered).toEqual(["Mark done"]);
  expect(await statusOf(page, goneId)).toBe("open");

  // A Read has them too, and a done todo turned into a Read can be reopened (#69)
  const [, read] = await make(page, "consume");
  await page.goto(`/p/${read}`);
  await expect.poll(offered).toEqual(["Mark done"]);
  const [, was, wasId] = await make(page, "todo", "done");
  await page.request.patch(`/api/pages/${wasId}`, { data: { kind: "consume" } });
  await page.goto(`/p/${was}`);
  await expect.poll(offered).toEqual(["Reopen"]);
  await tools.getByRole("button", { name: "Reopen" }).click();
  await expect.poll(offered).toEqual(["Mark done"]);

  const [, note] = await make(page, "note");
  await page.goto(`/p/${note}`);
  await expect(tools.getByRole("button", { name: "Edit" })).toBeVisible();
  await expect.poll(offered).toEqual([]);
});

test("Mark done leads a todo's toolbar, filled and wider; Download is in Share's menu", async ({
  page,
}) => {
  const tools = page.locator(".page > .tools");
  const names = () =>
    tools.locator(":scope > *").evaluateAll((els) => els.map((e) => (e.textContent ?? "").trim()));
  const [, slug] = await make(page, "todo");
  // No share sheet on this browser: Download stays in Share's place
  await page.goto(`/p/${slug}`);
  await expect.poll(names).toEqual(["Mark done", "Edit", "Download", "Delete"]);
  const done = tools.getByRole("button", { name: "Mark done" });
  await expect(done).toHaveClass(/primary/);
  const width = async (name: string) =>
    (await tools.getByText(name, { exact: true }).boundingBox())?.width ?? 0;
  expect(await width("Mark done")).toBeGreaterThan(await width("Edit"));
  // Every label whole at 360 px
  await page.setViewportSize({ width: 360, height: 740 });
  const cut = await tools
    .locator(":scope > *")
    .evaluateAll((els) => els.filter((e) => e.scrollWidth > e.clientWidth).length);
  expect(cut).toBe(0);

  // With a share sheet: Share's menu ends with Download, and a tap on it closes the menu
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "share", { value: async () => {}, configurable: true });
  });
  await page.goto(`/p/${slug}`);
  await expect.poll(names).toEqual(["Mark done", "Edit", "Share", "Delete"]);
  await tools.getByRole("button", { name: "Share" }).click();
  const menu = page.locator(".share-menu");
  await expect(menu.locator(":scope > *")).toHaveText([
    "Link",
    "Text",
    "Print / Save as PDF",
    "Download HTML", // this phone can't share the file: saved
    "Download",
    "Pin to Search",
  ]);
  const saved = page.waitForEvent("download");
  await menu.getByRole("link", { name: "Download" }).click();
  await expect(menu).toHaveCount(0);
  expect((await saved).suggestedFilename()).toMatch(/\.md$/);

  // A share sheet but no menu (no Popover API): Download beside Share, not lost
  await page.addInitScript(() => {
    delete (HTMLElement.prototype as Partial<HTMLElement>).showPopover; // as on an older browser
  });
  await page.goto(`/p/${slug}`);
  await expect.poll(names).toEqual(["Mark done", "Edit", "Share", "Download", "Delete"]);
});

test("unticking an in-progress row restores in_progress; a kind changed meanwhile is not ticked (#80)", async ({
  page,
}) => {
  const [title, slug, id] = await make(page, "todo", "in_progress");
  await page.goto("/recent");
  const row = page.locator(".list li").filter({ has: page.locator(`a[href="/p/${slug}"]`) });
  const tick = row.getByRole("button", { name: `Done: ${title}` });
  await tick.click();
  await expect(tick).toHaveAttribute("aria-pressed", "true");
  await tick.click();
  await expect(tick).toHaveAttribute("aria-pressed", "false");
  expect(await statusOf(page, id)).toBe("in_progress");

  // Its kind changes elsewhere to one with no status: the tick leaves no chip and no pressed tick
  const [t2, s2, id2] = await make(page, "todo");
  await page.goto("/recent");
  const row2 = page.locator(".list li").filter({ has: page.locator(`a[href="/p/${s2}"]`) });
  // Drawn as a todo before its kind changes: else the list may come after, drawn as a note
  await expect(row2.getByRole("button", { name: `Done: ${t2}` })).toBeVisible();
  await page.request.patch(`/api/pages/${id2}`, { data: { kind: "note" } });
  await row2.getByRole("button", { name: `Done: ${t2}` }).click();
  await expect(row2.getByRole("button", { name: `Done: ${t2}` })).toHaveCount(0);
  await expect(row2.locator("em")).toHaveCount(0);
});

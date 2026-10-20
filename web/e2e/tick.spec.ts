// Ticking off todos and Reads: the tick on a list row (beside its link, so tapping it neither
// opens the page nor swipes the row) and Done / Reopen on the page, for every status.
import { expect, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

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
  await expect(row.locator("em")).toHaveText("todo");

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
  await expect(row.locator("em")).toHaveText("todo");
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

test("a page offers Done from any status but done, Reopen from done or cancelled", async ({
  page,
}) => {
  const tools = page.locator(".page > .tools");
  const offered = () => tools.getByRole("button", { name: /^(Done|Reopen)$/ }).allTextContents();

  const [, busy, busyId] = await make(page, "todo", "in_progress");
  await page.goto(`/p/${busy}`);
  await expect.poll(offered).toEqual(["Done"]);
  await tools.getByRole("button", { name: "Done" }).click();
  await expect.poll(offered).toEqual(["Reopen"]);
  expect(await statusOf(page, busyId)).toBe("done");

  const [, gone, goneId] = await make(page, "todo", "cancelled");
  await page.goto(`/p/${gone}`);
  await expect.poll(offered).toEqual(["Done", "Reopen"]);
  await page.setViewportSize({ width: 320, height: 700 }); // six tools still fit
  await page.screenshot({ path: test.info().outputPath("cancelled-320.png") });
  await tools.getByRole("button", { name: "Reopen" }).click();
  await expect.poll(offered).toEqual(["Done"]);
  expect(await statusOf(page, goneId)).toBe("open");

  // A Read has them too, and a done todo turned into a Read can be reopened (#69)
  const [, read] = await make(page, "consume");
  await page.goto(`/p/${read}`);
  await expect.poll(offered).toEqual(["Done"]);
  const [, was, wasId] = await make(page, "todo", "done");
  await page.request.patch(`/api/pages/${wasId}`, { data: { kind: "consume" } });
  await page.goto(`/p/${was}`);
  await expect.poll(offered).toEqual(["Reopen"]);
  await tools.getByRole("button", { name: "Reopen" }).click();
  await expect.poll(offered).toEqual(["Done"]);

  const [, note] = await make(page, "note");
  await page.goto(`/p/${note}`);
  await expect(tools.getByRole("button", { name: "Edit" })).toBeVisible();
  await expect.poll(offered).toEqual([]);
});

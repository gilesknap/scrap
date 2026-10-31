// Every page, tag and list is a real link (a page's tag chips: tags.spec.ts): Ctrl-click (or a long press on a phone) opens it in
// a new tab; a plain tap still routes in the app, without loading it again.
import { expect, type Page, test } from "@playwright/test";
import { capture, ulid } from "./helpers";

async function note(page: Page, text: string) {
  const { slug, page_id } = await capture(page, text);
  return [slug, page_id] as const;
}

test("rows, tags, wiki links and the pager are links; Ctrl-click opens a new tab", async ({
  page,
  context,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  // Other tests' fake photos have no preview (the row shows the kind's icon): not an error here
  page.on("console", (m) => {
    if (m.type() === "error" && !m.text().startsWith("Failed to load resource"))
      errors.push(m.text());
  });
  page.on("response", (r) => {
    if (r.status() >= 400 && !r.url().includes("/preview?"))
      errors.push(`${r.status()} ${r.url()}`);
  });
  const tag = `t${ulid().slice(-6).toLowerCase()}`;
  const [first] = await note(page, `Linked first ${tag}`);
  const [second] = await note(
    page,
    `Linked second ${tag}\n\nSee [[${first}|the first]], [[${first}#a-heading]].`,
  );

  await page.goto("/search"); // newest first: second, then first
  const row = page.locator(`.list li a[href="/p/${second}"]`);
  await expect(row).toBeVisible();
  await expect(page.locator(`.list li a[href="/p/${first}"]`)).toBeVisible();

  // Ctrl-click: a new tab with that page; this one stays on the list
  const [tab] = await Promise.all([
    context.waitForEvent("page"),
    row.click({ modifiers: ["ControlOrMeta"] }),
  ]);
  await tab.waitForLoadState();
  expect(new URL(tab.url()).pathname).toBe(`/p/${second}`);
  await expect(tab.getByRole("heading", { name: `Linked second ${tag}` })).toBeVisible();
  await tab.close();
  await expect(page).toHaveURL(/\/search$/);

  // A middle click too
  const [tab2] = await Promise.all([context.waitForEvent("page"), row.click({ button: "middle" })]);
  await tab2.waitForLoadState();
  expect(new URL(tab2.url()).pathname).toBe(`/p/${second}`);
  await tab2.close();

  // A plain tap routes here: the app is not loaded again
  await page.evaluate(() => {
    (window as unknown as { kept: boolean }).kept = true;
  });
  await row.click();
  await expect(page).toHaveURL(`/p/${second}`);
  expect(await page.evaluate(() => (window as unknown as { kept?: boolean }).kept)).toBe(true);

  // On the page: the wiki link and the pager's next are links too
  const wiki = page.locator(".md a", { hasText: "the first" });
  await expect(wiki).toHaveAttribute("href", `/p/${first}`);
  // One to a heading links to the page (#498)
  const heading = page.locator(".md a", { hasText: `${first}#a-heading` });
  await expect(heading).toHaveAttribute("href", `/p/${first}`);
  const next = page.getByRole("link", { name: "Next" });
  await expect(next).toHaveAttribute("href", `/p/${first}`);
  const [tab3] = await Promise.all([
    context.waitForEvent("page"),
    next.click({ modifiers: ["ControlOrMeta"] }),
  ]);
  await tab3.waitForLoadState();
  await expect(tab3.getByRole("heading", { name: `Linked first ${tag}` })).toBeVisible();
  await tab3.close();
  await expect(page).toHaveURL(`/p/${second}`); // the pager did not step here
  await next.click(); // a plain tap steps in place
  await expect(page).toHaveURL(`/p/${first}`);
  await page.goBack();
  await expect(page).toHaveURL(/\/search$/); // Back is still the list

  // Every such address loads fresh: a page, a tag search
  for (const path of [`/p/${first}`, `/search?q=${encodeURIComponent(`tag:${tag}`)}`]) {
    const fresh = await context.newPage();
    await fresh.goto(path);
    await expect(fresh.locator("#view > *").first()).toBeVisible();
    await expect(fresh.getByText("Not found")).toHaveCount(0);
    await fresh.close();
  }
  expect(errors).toEqual([]);
});

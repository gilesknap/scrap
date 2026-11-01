// A page link with no label of its own shows the linked page's title (#508): [[slug]],
// [[slug#heading]] and a page's bare address, in the page and the editor's Preview, its title
// as it is now; a typed label stays, and a link to no page shows what was typed.
import { expect, test } from "@playwright/test";
import { capture, deletedAfterEach, ulid } from "./helpers";

const made = deletedAfterEach();

test("a bare link shows the page's title; a label and a dangling link stay as typed", async ({
  page,
  baseURL,
}) => {
  const tag = ulid().slice(-6).toLowerCase();
  const b = await capture(page, `Front border in flower ${tag}`);
  const gone = `no-such-page-${tag}`;
  const a = await capture(
    page,
    `Index ${tag}\n\n- [[${b.slug}]]\n- [[${b.slug}#roses]]\n- [[${b.slug}|my own words]]\n` +
      `- [[${gone}]]\n- ${baseURL}/p/${b.slug}`,
  );
  made.push(a.page_id, b.page_id);
  await page.goto(`/p/${a.slug}`);
  const links = page.locator(".page .body a");
  const title = `Front border in flower ${tag}`;
  await expect(links).toHaveText([title, title, "my own words", gone, title]);
  const hrefs = [b.slug, b.slug, b.slug, gone, b.slug].map((s) => `/p/${s}`);
  expect(await links.evaluateAll((all) => all.map((l) => l.getAttribute("href")))).toEqual(hrefs);

  // Renamed: the link shows its title as it is now
  const now = await (await page.request.get(`/api/pages/${b.page_id}`)).json();
  const renamed = await page.request.patch(`/api/pages/${b.page_id}`, {
    data: { base_rev: now.rev, title: `Summer border ${tag}` },
  });
  expect(renamed.ok()).toBe(true);
  await page.reload();
  await expect(links.first()).toHaveText(`Summer border ${tag}`);

  // The editor's Preview: the same, a link added since showing its slug until it is saved
  await page.locator(".page .tools").getByRole("button", { name: "Edit" }).click();
  const box = page.locator(".editor textarea").first();
  await box.fill(`[[${b.slug}]] [[${b.slug}|mine]] [[${gone}]]`);
  await page.locator(".editor").getByRole("button", { name: "Preview" }).click();
  await expect(page.locator(".editor .preview a")).toHaveText([
    `Summer border ${tag}`,
    "mine",
    gone,
  ]);
});

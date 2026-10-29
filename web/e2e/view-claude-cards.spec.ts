// Claude's cards on a page: each a brown card titled by what it holds, its action at the
// line's end (Generate the first time, Regenerate after), its parts as folds. About this page:
// Summary and Related, open until closed. The e2e server runs with Claude off, so the page's
// answer is given what Claude would have made of it. Named to run after smoke.spec.ts, which
// wants an empty store.
import { expect, type Page, test } from "@playwright/test";

const ulid = () => {
  const c = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  return Array.from({ length: 26 }, (_, i) => c[i ? Math.floor(Math.random() * 32) : 0]).join("");
};

async function note(page: Page, text: string) {
  const r = await page.request.post("/api/captures", { data: { id: ulid(), text } });
  expect(r.ok()).toBe(true);
  return (await r.json()) as { page_id: string; slug: string };
}

/** The page's answer as if Claude were on and had (or had not) read it. */
async function asRead(page: Page, slug: string, enrich: object, related: object[] = []) {
  await page.route(`**/api/pages/${slug}`, async (r) => {
    if (r.request().method() !== "GET") return r.continue();
    const json = await (await r.fetch()).json();
    await r.fulfill({ json: { ...json, enrich: { on: true, error: null, ...enrich }, related } });
  });
}

test("About this page: titled, Regenerate at the end, Summary and Related open until closed", async ({
  page,
}) => {
  const other = await note(page, `Card other ${ulid().slice(-6)}`);
  const n = await note(page, `Card note ${ulid().slice(-6)}`);
  await asRead(page, n.slug, { state: "done", summary: "What the note is about." }, [
    { id: other.page_id, slug: other.slug, title: "The other note", kind: "note", via: "claude" },
  ]);
  await page.goto(`/p/${n.slug}`);
  const card = page.locator(".enrich.claude");
  await expect(card.getByRole("heading", { name: "About this page" })).toBeVisible();
  await expect(card.getByRole("button", { name: "Regenerate" })).toBeVisible();
  await expect(card.getByRole("status")).toHaveCount(0); // no pill once read
  const summary = card.locator("details", { hasText: "Summary" });
  const related = card.locator("details.related");
  await expect(summary).toHaveAttribute("open", "");
  await expect(related).toHaveAttribute("open", "");
  await expect(summary.getByText("What the note is about.")).toBeVisible();
  await expect(related.getByRole("link", { name: "The other note" })).toBeVisible();
  // Closed, it stays closed when the page is opened again
  await summary.locator("summary").click();
  await expect(summary).not.toHaveAttribute("open", "");
  await page.reload();
  await expect(page.locator(".enrich details", { hasText: "Summary" })).not.toHaveAttribute(
    "open",
    "",
  );
  await expect(page.locator(".enrich details.related")).toHaveAttribute("open", "");
});

test("never read: what Claude would do, and Generate", async ({ page }) => {
  const n = await note(page, `Card unread ${ulid().slice(-6)}`);
  await asRead(page, n.slug, { state: null, summary: null });
  await page.goto(`/p/${n.slug}`);
  const card = page.locator(".enrich.claude");
  await expect(card.getByRole("heading", { name: "About this page" })).toBeVisible();
  await expect(card).toContainText("Claude can summarise it, suggest tags and find related pages.");
  await expect(card.getByRole("button", { name: "Generate" })).toBeVisible();
  await expect(card.locator("details")).toHaveCount(0);
});

test("a page made by sharing a PDF: the file comes before About this page (#445)", async ({
  page,
}) => {
  const r = await page.request.post("/api/captures", {
    multipart: {
      id: ulid(),
      text: `Shared pdf ${ulid().slice(-6)}`,
      file: { name: "shared.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") },
    },
  });
  const n = (await r.json()) as { slug: string };
  await asRead(page, n.slug, { state: "done", summary: "A shared PDF." });
  await page.goto(`/p/${n.slug}`);
  await expect(page.locator(".enrich.claude")).toBeVisible();
  const file = await page.locator(".originals a.file, .filerow a.file").first().boundingBox();
  const card = await page.locator(".enrich.claude").boundingBox();
  expect(file && card && file.y < card.y).toBe(true);
});

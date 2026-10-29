// Settings > Import Markdown (#417): pick a zip, see its pages and photos with what Claude
// would cost for each (both choices unticked; off here, as this server has no Claude), import
// it, and read what was done. A second import of the same zip adds nothing.
import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";

/** A zip of two pages, one embedding a photo, made with Python's zipfile. */
function vault(stamp: number): string {
  const path = join(mkdtempSync(join(tmpdir(), "scrap-import-")), "vault.zip");
  const script = `
import io, sys, zipfile
from PIL import Image
img = io.BytesIO(); Image.new("RGB", (8, 8), "red").save(img, "PNG")
with zipfile.ZipFile(sys.argv[1], "w") as z:
    z.writestr("imp-a-${stamp}.md", "---\\ntags: [e2e]\\n---\\nFirst ![[dot.png]] and [[imp-b-${stamp}]]\\n")
    z.writestr("deep/imp-b-${stamp}.md", "Second\\n")
    z.writestr("dot.png", img.getvalue())
    z.writestr(".obsidian/app.json", "{}")
`;
  execFileSync("uv", ["run", "--locked", "python", "-c", script, path], { cwd: ".." });
  return path;
}

test("Import Markdown shows the zip's pages and costs, then imports it once", async ({ page }) => {
  const stamp = Date.now();
  const zip = vault(stamp);
  await page.goto("/");
  await page.getByRole("button", { name: "Settings" }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  const pick = dialog.getByRole("button", { name: "Import Markdown…" });
  await expect(pick).toBeVisible();
  const box = (await pick.boundingBox()) as { height: number };
  expect(box.height).toBeGreaterThanOrEqual(48);

  await dialog.locator("input[type=file]").setInputFiles(zip);
  await expect(dialog).toContainText("vault.zip: 2 pages, 1 photo.");
  const enrich = dialog.getByRole("checkbox", { name: /Enrich text pages with Claude/ });
  const photos = dialog.getByRole("checkbox", { name: /Read photos with Claude/ });
  await expect(enrich).not.toBeChecked();
  await expect(photos).not.toBeChecked();
  await expect(enrich).toBeDisabled(); // no Claude on this server
  await expect(dialog).toContainText("Claude is off on this server");

  await dialog.getByRole("button", { name: "Import", exact: true }).click();
  const status = dialog.getByRole("status");
  await expect(status).toContainText("Imported 2 pages");
  await expect(status).toContainText("Nothing queued for Claude.");
  const day = new Date().toISOString().slice(0, 10);
  await expect(status).toContainText(`tagged import/${day}`);

  const a = await (await page.request.get(`/api/pages/imp-a-${stamp}`)).json();
  expect(a.tags).toEqual(expect.arrayContaining(["e2e", `import/${day}`]));
  expect(a.body).toMatch(/^First !\[\]\(\/api\/blobs\/[0-9a-f]{64}\/preview\?size=2048\) and /);

  await dialog.locator("input[type=file]").setInputFiles(zip);
  await dialog.getByRole("button", { name: "Import", exact: true }).click();
  await expect(status).toContainText("Imported 0 pages; 2 here already");
  await expect(dialog).toBeVisible();
  // Deleted after, so other specs' counts of the store's pages hold
  for (const slug of [`imp-a-${stamp}`, `imp-b-${stamp}`]) {
    expect((await page.request.delete(`/api/pages/${slug}`)).ok()).toBe(true);
  }
});

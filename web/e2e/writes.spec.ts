// A page Claude wrote over MCP (#37): written through /mcp, shown with its badge, and
// is:claude finds it. Runs after the others (alphabetical; smoke.spec.ts wants an empty store).
import { expect, test } from "@playwright/test";

test("a page written over MCP shows a Written by Claude badge", async ({ page, request }) => {
  const r = await request.post("/mcp", {
    headers: { Accept: "application/json, text/event-stream" },
    data: {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: {
        name: "write",
        arguments: {
          title: "Quokka findings from Claude",
          body: "Synthetic test page.",
          origin: "e2e test",
          tags: ["e2e"],
        },
      },
    },
  });
  expect(r.ok()).toBeTruthy();
  const { slug } = (await r.json()).result.structuredContent;
  await page.goto(`/p/${slug}`);
  const badge = page.locator(".meta .badge");
  await expect(badge).toHaveText("Written by Claude");
  await expect(badge).toHaveAttribute("title", "e2e test");
  await badge.click();
  await expect(page).toHaveURL(/q=is%3Aclaude/);
  await expect(page.locator(".hits li a strong")).toHaveText(["Quokka findings from Claude"]);
});

test("text over 1 MB is not saved: the editor and composer say so first (#62)", async ({
  page,
}) => {
  const big = "x".repeat(1_020_000); // over 1 MB, under the e2e server's 1 MiB upload limit
  const id = "01E2EB16PAGE".padEnd(26, "0");
  const made = await (
    await page.request.post("/api/captures", { data: { id, text: "Small" } })
  ).json();
  await page.goto(`/p/${made.slug}`);
  await page.locator(".page .tools").getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Body").fill(big);
  await page.locator(".editor").getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".toast")).toHaveText(
    "Not saved: the text is 1.02 MB, and a page holds at most 1 MB",
  );
  await expect(page.locator(".editor")).toBeVisible(); // still editing, nothing lost
  expect((await (await page.request.get(`/api/pages/${made.page_id}`)).json()).rev).toBe(1);
  // The server refuses it too
  const r = await page.request.patch(`/api/pages/${made.page_id}`, {
    data: { base_rev: 1, body: big },
  });
  expect(r.status()).toBe(422);
  expect((await r.json()).detail).toContain("a page holds at most 1 MB");
  // The composer: not queued
  page.once("dialog", (d) => d.accept());
  await page.locator(".editor").getByRole("button", { name: "Cancel" }).click();
  await page.goto("/");
  await page.getByRole("button", { name: "Note", exact: true }).click();
  await page.locator(".editor textarea").fill(big);
  await page.locator(".editor").getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".toast")).toContainText("a page holds at most 1 MB");
  await expect(page.locator(".editor")).toBeVisible();
  await expect(page.locator("#queue")).toBeHidden();
  page.once("dialog", (d) => d.accept());
  await page.locator(".editor").getByRole("button", { name: "Cancel" }).click();
});

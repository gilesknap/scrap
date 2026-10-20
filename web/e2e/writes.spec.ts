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

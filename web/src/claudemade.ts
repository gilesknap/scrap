// Images Claude placed itself over MCP (#521): add_svg's, or Claude's /mcp upload (a capture
// of source mcp, author claude). Claude doesn't read them, so each shows on its own, with
// nothing under it, in the app (figure.ts) and on its public page (publicask.ts's warning).
// A file one of the owner's captures holds too (Claude reused it) is still read.
import type { Page } from "./api";

/** Whether a capture is one Claude made over MCP. */
export const byClaude = (c: Page["captures"][number]): boolean =>
  c.source === "mcp" && c.author === "claude";

/** The page's files (by SHA-256) that only captures Claude made hold. */
export function claudeMade(p: Pick<Page, "captures">): Set<string> {
  const mine = new Set<string>();
  const claude = new Set<string>();
  for (const c of p.captures) for (const b of c.blobs) (byClaude(c) ? claude : mine).add(b.sha256);
  for (const sha of mine) claude.delete(sha);
  return claude;
}

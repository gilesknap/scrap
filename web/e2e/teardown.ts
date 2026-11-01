// After a run: the public site's throwaway folder and token (playwright.config.ts), if this
// run made them.
import { rmSync } from "node:fs";

export default function teardown() {
  const dir = process.env.SCRAP_E2E_PUB;
  if (dir && process.env.SCRAP_E2E_PUB_MADE === "1") rmSync(dir, { recursive: true, force: true });
}

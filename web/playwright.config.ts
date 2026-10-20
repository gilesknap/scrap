// Smoke test against a real `scrap serve` on a throwaway data folder (build the PWA first).
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

// Made once: test workers load this file again, and inherit it from the runner
const data = process.env.SCRAP_E2E_DATA || mkdtempSync(join(tmpdir(), "scrap-e2e-"));
const port = 8791;
process.env.SCRAP_E2E_DATA = data; // whiteboard.spec.ts has e2e/draw.py add fixtures to it

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  workers: 1,
  use: { ...devices["Pixel 7"], baseURL: `http://127.0.0.1:${port}` },
  webServer: {
    command: `uv run --locked scrap serve --port ${port} --data-dir ${data}`,
    cwd: "..",
    url: `http://127.0.0.1:${port}/healthz`,
    env: { SCRAP_MAX_UPLOAD_MB: "1" }, // so a 2 MB photo is refused
  },
});

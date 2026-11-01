// Smoke test against a real `scrap serve` on a throwaway data folder (build the PWA first).
import { randomBytes } from "node:crypto";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";
import { RECEIVER as receiver, SITE as sitePort } from "./e2e/ports";

// Made once: test workers load this file again, and inherit it from the runner
const data = process.env.SCRAP_E2E_DATA || mkdtempSync(join(tmpdir(), "scrap-e2e-"));
const port = Number(process.env.SCRAP_E2E_PORT) || 8791; // another, to run beside a run
process.env.SCRAP_E2E_DATA = data; // whiteboard.spec.ts has e2e/draw.py add fixtures to it
// Public pages (#497): scrap publishes to the real receiver (scrap-public/receiver.py), with
// a throwaway site folder and token file (removed after the run: e2e/teardown.ts), and
// e2e/site.py serves that site as nginx would, for public-pages.spec.ts to read (e2e/ports.ts)
if (!process.env.SCRAP_E2E_PUB) {
  process.env.SCRAP_E2E_PUB = mkdtempSync(join(tmpdir(), "scrap-e2e-pub-"));
  process.env.SCRAP_E2E_PUB_MADE = "1";
  mkdirSync(join(process.env.SCRAP_E2E_PUB, "site"));
  writeFileSync(join(process.env.SCRAP_E2E_PUB, "token"), randomBytes(24).toString("hex"));
}
const site = join(process.env.SCRAP_E2E_PUB, "site");
const tokenFile = join(process.env.SCRAP_E2E_PUB, "token");

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  workers: 1,
  globalTeardown: "./e2e/teardown.ts",
  use: { ...devices["Pixel 7"], baseURL: `http://127.0.0.1:${port}` },
  webServer: [
    {
      command: "uv run --locked python scrap-public/receiver.py",
      cwd: "..",
      url: `http://127.0.0.1:${receiver}/healthz`,
      stdout: "ignore",
      stderr: "ignore", // a line per request: the run's own output says what matters
      env: {
        RECEIVER_LISTEN: `tcp:127.0.0.1:${receiver}`,
        RECEIVER_TOKEN_FILE: tokenFile,
        RECEIVER_SITE: site,
      },
    },
    {
      command: `uv run --locked python web/e2e/site.py ${site} ${sitePort}`,
      cwd: "..",
      url: `http://127.0.0.1:${sitePort}/robots.txt`,
    },
    {
      command: `uv run --locked scrap serve --port ${port} --data-dir ${data}`,
      cwd: "..",
      url: `http://127.0.0.1:${port}/healthz`,
      env: {
        SCRAP_MAX_UPLOAD_MB: "1", // so a 2 MB photo is refused
        // A second address: view-links.spec.ts follows a page's full address on it (#290)
        SCRAP_PUBLIC_URL: `http://127.0.0.1:${port},http://scrap-lan.example:8000`,
        SCRAP_PUBLISH_TO: `http://127.0.0.1:${receiver}`,
        SCRAP_PUBLISH_SITE: `http://127.0.0.1:${sitePort}`,
        SCRAP_PUBLISH_TOKEN_FILE: tokenFile,
      },
    },
  ],
});

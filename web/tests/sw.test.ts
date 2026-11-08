// The service worker answers page loads from its cached shell, except the login's own pages
// and a load marked to log in again (login.ts), which must reach the login in front of scrap.
import { expect, it, vi } from "vitest";

const on: Record<string, (e: unknown) => void> = {};
vi.stubGlobal("self", {
  addEventListener: (type: string, f: (e: unknown) => void) => (on[type] = f),
});
vi.stubGlobal("location", { origin: "https://scrap.example" });
const match = vi.fn(async (key: unknown) => `shell for ${String(key)}`);
vi.stubGlobal("caches", { match });
await import("../src/sw");

/** A GET for this path; what the worker answered with, or undefined if it left it alone. */
async function load(path: string, mode = "navigate") {
  const request = { url: `https://scrap.example${path}`, method: "GET", mode };
  let answer: Promise<unknown> | undefined;
  on.fetch?.({ request, respondWith: (r: Promise<unknown>) => (answer = r) });
  return answer && (await answer);
}

it("serves the app's pages from the cached shell", async () => {
  expect(await load("/")).toBe("shell for /");
  expect(await load("/p/a")).toBe("shell for /");
  expect(await load("/search?q=login")).toBe("shell for /");
});

it("leaves the login's pages and a load marked to log in to the network", async () => {
  expect(await load("/oauth2/start?rd=%2Fp%2Fa")).toBeUndefined();
  expect(await load("/oauth2/callback?code=c&state=s")).toBeUndefined();
  expect(await load("/cdn-cgi/access/authorized?token=t")).toBeUndefined();
  expect(await load("/p/a?login=1")).toBeUndefined();
});

it("leaves the API alone, as before", async () => {
  expect(await load("/api/pages", "cors")).toBeUndefined();
});

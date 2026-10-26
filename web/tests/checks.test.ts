import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { CHECKS, checkName, checkSearch } from "../src/checks";

it("lists the server's health checks, in its order", () => {
  // scrap/store/health.py's CHECKS: the terms GET /api/health counts, in order
  const py = readFileSync(new URL("../../src/scrap/store/health.py", import.meta.url), "utf8");
  const block = py.slice(py.indexOf("CHECKS = ["), py.indexOf("]", py.indexOf("CHECKS = [")));
  const server = [...block.matchAll(/\("(\w+)", "(\w+)"\)/g)].map((m) => `${m[1]}:${m[2]}`);
  expect(server.length).toBe(6);
  expect(CHECKS.map(([term]) => term)).toEqual(server);
});

it("names a check, and nothing else", () => {
  expect(checkName("is:orphan")).toBe("Orphans");
  expect(checkName("has:dangling")).toBe("Dangling links");
  expect(checkName("is:outdated")).toBe("Outdated write-ups");
  expect(checkName("is:done")).toBeUndefined();
  expect(new Set(CHECKS.map(([, name]) => name)).size).toBe(CHECKS.length);
});

it("links a check to its search", () => {
  expect(checkSearch("is:outdated")).toBe("/search?q=is%3Aoutdated");
});

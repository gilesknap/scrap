import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";

const html = readFileSync("index.html", "utf8");

function policy(): Map<string, string> {
  const m = html.match(/http-equiv="Content-Security-Policy"\s+content="([^"]+)"/);
  expect(m).not.toBeNull();
  const out = new Map<string, string>();
  for (const d of (m as RegExpMatchArray)[1].split(";")) {
    const [name, ...src] = d.trim().split(/\s+/);
    if (name) out.set(name, src.join(" "));
  }
  return out;
}

describe("Content-Security-Policy (issue 105)", () => {
  test("has a default-src and a script-src limited to this origin", () => {
    const p = policy();
    expect(p.get("default-src")).toBe("'self'");
    expect(p.get("script-src")).toBe("'self'");
  });
  test("allows no inline or eval scripts", () => {
    for (const [name, src] of policy()) {
      if (name === "script-src" || name === "default-src")
        expect(src).not.toMatch(/unsafe-inline|unsafe-eval|\*|https?:/);
    }
  });
  test("index.html has no inline script, which script-src would block", () => {
    const inline = [...html.matchAll(/<script\b([^>]*)>/g)].filter((s) => !/\bsrc=/.test(s[1]));
    expect(inline).toEqual([]);
    expect(html).not.toMatch(/\son[a-z]+="/); // no inline event handlers
  });
});

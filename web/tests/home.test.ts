// scrap's home (home.ts) and Back up from a page opened cold (back.ts) on a phone and on a
// computer: "/" is Capture on a phone and Search on a computer, and a page whose parent is home
// says so and goes there; todos and topics keep their own lists.
import { afterEach, describe, expect, it, vi } from "vitest";
import { up } from "../src/back";
import { capturePath, DESK, desk, home, homeAt } from "../src/home";

/** matchMedia as a device of this kind answers it: true for DESK on a computer only. */
const device = (computer: boolean) =>
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: computer && q === DESK }));

/** A page opened cold at /p/x, drawn as this kind (none: still loading). */
const page = (kind?: string) => {
  vi.stubGlobal("location", { pathname: "/p/x" });
  vi.stubGlobal("document", {
    querySelector: () => (kind ? { dataset: { kind } } : null),
  });
};

afterEach(() => vi.unstubAllGlobals());

describe.each([
  [false, "Capture", "/"],
  [true, "Search", "/capture"],
])("computer %s", (computer, name, capture) => {
  it(`home is ${name}, Capture is at ${capture}`, () => {
    device(computer);
    expect(desk()).toBe(computer);
    expect(home()).toBe(name);
    expect(capturePath()).toBe(capture);
  });

  it("opening scrap at home shows Search on a computer, Capture on a phone", () => {
    device(computer);
    expect(homeAt("")).toBe(computer ? "/search" : null);
    // A share always lands on Capture, at its own address on a computer
    expect(homeAt("?shared=1")).toBe(computer ? "/capture?shared=1" : null);
  });

  it.each([
    [undefined, "/"],
    ["note", "/"],
    ["read", "/"],
    ["todo", "/todos"],
    ["topic", "/topics"],
  ])("a cold %s page's Back goes to %s", (kind, to) => {
    device(computer);
    page(kind);
    const go = vi.fn();
    up(go);
    expect(go).toHaveBeenCalledWith(to, true);
  });
});

it("Back does nothing once the app has left the page", () => {
  device(true);
  page("note");
  const go = vi.fn();
  up(go, "/p/elsewhere");
  expect(go).not.toHaveBeenCalled();
});

it("DESK is css/desktop.css's query", async () => {
  const { readFileSync } = await import("node:fs");
  const css = readFileSync(new URL("../src/css/desktop.css", import.meta.url), "utf8");
  expect(css).toContain(`@media ${DESK} {`);
});

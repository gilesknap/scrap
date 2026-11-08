// scrap's home (home.ts) and Back up from a page opened cold (back.ts) on a phone and on a
// computer: "/" is Capture on a phone and Search on a computer (Capture there when offline or
// for a share), and a page whose parent is home says so and goes there; todos and topics keep
// their own lists.
import { afterEach, describe, expect, it, vi } from "vitest";
import { up } from "../src/back";
import { capturePath, DESK, desk, home, homeAt, parent } from "../src/home";

/** matchMedia as a device of this kind answers it (true for DESK on a computer only), online
 * or not. */
const device = (computer: boolean, onLine = true) => {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: computer && q === DESK }));
  vi.stubGlobal("navigator", { onLine });
};

/** A page opened cold at /p/x, drawn as this kind (none: still loading). */
const page = (kind?: string) => {
  vi.stubGlobal("location", { pathname: "/p/x" });
  vi.stubGlobal("document", {
    querySelector: () => (kind ? { dataset: { kind } } : null),
  });
};

/** The screen an in-app address shows: "/" as the router resolves it (main.ts, homeAt). */
const screen = (path: string) =>
  path === "/" ? ((homeAt("") ?? "/capture").startsWith("/search") ? "Search" : "Capture") : path;

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
    // A query is kept for the search screen
    expect(homeAt("?q=tea")).toBe(computer ? "/search?q=tea" : null);
    // A share always lands on Capture, at its own address on a computer
    expect(homeAt("?shared=1")).toBe(computer ? "/capture?shared=1" : null);
  });

  it("offline, home is Capture on both", () => {
    device(computer, false);
    expect(home()).toBe("Capture");
    expect(homeAt("")).toBe(computer ? "/capture" : null);
    expect(homeAt("?q=tea")).toBe(computer ? "/capture" : null);
    expect(capturePath()).toBe(capture); // the tab does not move
  });

  // Back's label (main.ts's nameBack takes parent()'s name) and where up() sends it, which
  // must show the screen the label names
  it.each([
    [undefined, name],
    ["note", name],
    ["read", name],
    ["todo", "Todos"],
    ["topic", "Topics"],
  ])("a cold %s page: Back says %s and goes there", (kind, label) => {
    device(computer);
    page(kind);
    const [said, path] = parent(kind);
    expect(said).toBe(label);
    const go = vi.fn();
    up(go);
    expect(go).toHaveBeenCalledWith(path, true);
    const shown = screen(path);
    expect(shown === label || shown === `/${label.toLowerCase()}`).toBe(true);
  });
});

it("offline on a computer, a cold note's Back says Capture and shows it", () => {
  device(true, false);
  page("note");
  expect(parent("note")).toEqual(["Capture", "/"]);
  expect(screen("/")).toBe("Capture");
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

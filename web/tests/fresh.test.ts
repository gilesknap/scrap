import "fake-indexeddb/auto";
import { beforeEach, expect, it, vi } from "vitest";
import { drafts } from "../src/db";
import { DRAFT, FRESH, promote, recover } from "../src/fresh";
import { fresh } from "../src/freshlock";
import { stash } from "../src/stash";
import { toast } from "../src/ui";

vi.mock("../src/ui", () => ({ toast: vi.fn() }));
const said = vi.mocked(toast);
const events = vi.fn();
vi.stubGlobal("document", { dispatchEvent: events });

beforeEach(async () => {
  await drafts.del(DRAFT);
  for (const k of await drafts.keys(FRESH)) await drafts.del(k);
  said.mockClear();
  events.mockClear();
});

it("moves a draft to another key in one go, giving it and the one it replaced", async () => {
  await drafts.put("a", { text: "newer" });
  await drafts.put("b", { text: "older" });
  expect(await drafts.move("a", "b")).toEqual([{ text: "newer" }, { text: "older" }]);
  expect(await drafts.get("a")).toBeUndefined();
  expect(await drafts.get("b")).toEqual({ text: "newer" });
  // Nothing to move: nothing changes
  expect(await drafts.move("a", "b")).toEqual([undefined, undefined]);
  expect(await drafts.get("b")).toEqual({ text: "newer" });
  await drafts.put("c", { text: "alone" });
  expect(await drafts.move("c", "d")).toEqual([{ text: "alone" }, undefined]);
  await drafts.del("b");
  await drafts.del("d");
});

it("makes a fresh capture's draft the kept one, with Undo for the older", async () => {
  await drafts.put(DRAFT, { text: "older" });
  await drafts.put(FRESH, { text: "fresh" }); // as autosaved while typing
  expect(await recover()).toBe(true); // the app was killed: found on the next open
  expect(await drafts.get(DRAFT)).toEqual({ text: "fresh" });
  expect(await drafts.get(FRESH)).toBeUndefined();
  expect(events).toHaveBeenCalled(); // Capture's draft row draws it again
  const [message, action, undo] = said.mock.calls[0];
  expect([message, action]).toEqual([
    "Recovered your unsaved capture, in place of the older draft",
    "Undo",
  ]);
  undo?.();
  await vi.waitFor(async () => expect(await drafts.get(DRAFT)).toEqual({ text: "older" }));
});

it("says only that it is kept when there was no older draft, and nothing with no fresh one", async () => {
  expect(await promote(FRESH, () => "x")).toBe(false);
  expect(said).not.toHaveBeenCalled();
  await drafts.put(FRESH, { text: "fresh" });
  expect(await promote(FRESH, (older) => (older ? "replaced" : "kept"))).toBe(true);
  expect(said.mock.calls[0]).toEqual(["kept"]);
  expect(await drafts.get(DRAFT)).toEqual({ text: "fresh" });
});

it("says whether a draft was kept: storage that refuses it is not a silent success", async () => {
  await drafts.put(DRAFT, { text: "older" });
  expect(await stash(DRAFT, { text: "newer" })).toBe(true);
  expect(await drafts.get(DRAFT)).toEqual({ text: "newer" });
  const full = vi
    .spyOn(drafts, "put")
    .mockRejectedValueOnce(new DOMException("", "QuotaExceededError"));
  expect(await stash(DRAFT, { text: "newest" })).toBe(false);
  full.mockRestore();
  expect(await drafts.get(DRAFT)).toEqual({ text: "newer" }); // the old save, which Back must not trust
});

it("says a draft was not kept when storage refuses it, so no one claims 'Kept as a draft'", async () => {
  const put = vi.spyOn(drafts, "put").mockRejectedValueOnce(new DOMException("full"));
  expect(await stash("k", { text: "x" })).toBe(false);
  put.mockRestore();
  expect(await stash("k", { text: "x" })).toBe(true);
  await drafts.del("k");
});

it("with no Web Locks, takes any fresh draft, oldest first, one per open", async () => {
  expect(globalThis.navigator?.locks).toBeUndefined();
  const a = await fresh();
  const b = await fresh();
  expect(a.key < b.key).toBe(true); // in time order
  await drafts.put(b.key, { text: "newer" });
  await drafts.put(a.key, { text: "older" });
  expect(await recover()).toBe(true);
  expect(await drafts.get(DRAFT)).toEqual({ text: "older" });
  expect(await recover()).toBe(true);
  expect(await drafts.get(DRAFT)).toEqual({ text: "newer" });
  expect(await recover()).toBe(false);
});

// Web Locks as a browser has them, for one tab: a lock named is held until fn's promise settles
function fakeLocks() {
  const held = new Set<string>();
  const request = async (
    name: string,
    a: { ifAvailable?: boolean } | ((l: unknown) => unknown),
    b?: (l: unknown) => unknown,
  ) => {
    const [opts, fn] = typeof a === "function" ? [{}, a] : [a, b as (l: unknown) => unknown];
    if (held.has(name)) {
      if (opts.ifAvailable) return fn(null);
      throw new Error("the fake does not queue");
    }
    held.add(name);
    try {
      return await fn({ name });
    } finally {
      held.delete(name);
    }
  };
  return { request, held };
}

it("leaves a fresh draft whose lock is held (another tab's, open) and takes it once let go", async () => {
  const locks = fakeLocks();
  const before = globalThis.navigator;
  vi.stubGlobal("navigator", { locks });
  try {
    await drafts.put(DRAFT, { text: "kept" });
    const open = await fresh(); // tab A's composer
    expect(locks.held.size).toBe(1);
    await drafts.put(open.key, { text: "typing in A" });
    expect(await recover()).toBe(false); // tab B opens: A's draft is left be
    expect(await drafts.get(DRAFT)).toEqual({ text: "kept" });
    expect(await drafts.get(open.key)).toEqual({ text: "typing in A" });
    expect(said).not.toHaveBeenCalled();
    // An older build's fresh draft holds no lock: still found
    await drafts.put(FRESH, { text: "older build" });
    expect(await recover()).toBe(true);
    expect(await drafts.get(DRAFT)).toEqual({ text: "older build" });
    // A closed (its lock let go): its draft is recovered on the next open
    open.release();
    open.release(); // as often as it likes
    await vi.waitFor(() => expect(locks.held.size).toBe(0));
    expect(await recover()).toBe(true);
    expect(await drafts.get(DRAFT)).toEqual({ text: "typing in A" });
    expect(locks.held.size).toBe(0); // recover() lets go straight after
  } finally {
    vi.stubGlobal("navigator", before);
  }
});

import "fake-indexeddb/auto";
import { beforeEach, expect, it, vi } from "vitest";
import { drafts } from "../src/db";
import { DRAFT, FRESH, promote, recover, stash } from "../src/fresh";
import { toast } from "../src/ui";

vi.mock("../src/ui", () => ({ toast: vi.fn() }));
const said = vi.mocked(toast);
const events = vi.fn();
vi.stubGlobal("document", { dispatchEvent: events });

beforeEach(async () => {
  await drafts.del(DRAFT);
  await drafts.del(FRESH);
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
  expect(await promote(() => "x")).toBe(false);
  expect(said).not.toHaveBeenCalled();
  await drafts.put(FRESH, { text: "fresh" });
  expect(await promote((older) => (older ? "replaced" : "kept"))).toBe(true);
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

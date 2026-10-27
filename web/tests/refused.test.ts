import "fake-indexeddb/auto";
import { afterEach, expect, it, vi } from "vitest";

// A capture the server refused before the "Saved" toast's follow-up was listening (#345): the
// refusal fired its queuechange inside addAll, and no event follows it. The queue holds the
// state, so refused() has to look once itself.
// The tests run in node: the document is only an event target here
vi.stubGlobal("document", new EventTarget());
const items = vi.fn();
const toast = vi.fn();
vi.mock("../src/app", () => ({ queue: { items: () => items() } }));
vi.mock("../src/ui", async (orig) => ({ ...(await orig<object>()), toast }));
const { refused } = await import("../src/refused");

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

it("says Kept on this phone for a refusal that landed before it listened", async () => {
  items.mockResolvedValue([{ id: "a", failed: true }]);
  refused(["a"]);
  await vi.waitFor(() => expect(toast).toHaveBeenCalledWith("Kept on this phone"));
});

it("says nothing for an upload that went through, and stops listening", async () => {
  items.mockResolvedValue([]); // sent: gone from the queue
  refused(["a"]);
  await vi.waitFor(() => expect(items).toHaveBeenCalledTimes(1));
  document.dispatchEvent(new Event("queuechange"));
  await new Promise((r) => setTimeout(r, 20));
  expect(items).toHaveBeenCalledTimes(1);
  expect(toast).not.toHaveBeenCalled();
});

it("still waits while it uploads, and a later refusal is told once", async () => {
  items.mockResolvedValue([{ id: "a", failed: false }]);
  refused(["a"]);
  await vi.waitFor(() => expect(items).toHaveBeenCalledTimes(1));
  expect(toast).not.toHaveBeenCalled();
  items.mockResolvedValue([{ id: "a", failed: true }]);
  document.dispatchEvent(new Event("queuechange"));
  await vi.waitFor(() => expect(toast).toHaveBeenCalledTimes(1));
  document.dispatchEvent(new Event("queuechange"));
  await new Promise((r) => setTimeout(r, 20));
  expect(toast).toHaveBeenCalledTimes(1);
});

it("toasts once when two looks overlap", async () => {
  const gate: (() => void)[] = [];
  items.mockImplementation(
    () => new Promise((done) => gate.push(() => done([{ id: "a", failed: true }]))),
  );
  refused(["a"]); // its first look, waiting on the queue
  document.dispatchEvent(new Event("queuechange")); // a second one, in flight beside it
  await vi.waitFor(() => expect(gate).toHaveLength(2));
  for (const release of gate) release();
  await vi.waitFor(() => expect(toast).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 20));
  expect(toast).toHaveBeenCalledTimes(1);
});

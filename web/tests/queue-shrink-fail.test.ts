// If the downscale chunk cannot be loaded (offline, never cached), photos are queued as they are.
import "fake-indexeddb/auto";
import { beforeEach, expect, it, vi } from "vitest";
import { idb } from "../src/db";
import { Queue } from "../src/queue";

vi.mock("../src/downscale", () => {
  throw new Error("Failed to fetch dynamically imported module");
});

beforeEach(async () => {
  for (const i of await idb.all()) await idb.del(i.id);
});

it("queues the photo unchanged when the chunk will not load", async () => {
  const blob = new Blob([new Uint8Array(9)]);
  const q = new Queue(
    idb,
    async () => ({ status: 201 }),
    undefined,
    () => false,
  );
  const [item] = await q.addAll([{ source: "pwa", files: [{ name: "a.jpg", blob }] }]);
  expect(item.files[0].blob).toBe(blob);
  expect(await idb.all()).toHaveLength(1);
});

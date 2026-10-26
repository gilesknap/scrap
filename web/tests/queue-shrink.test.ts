// The queue makes photos smaller as it stores them (#89), but not when it re-queues a stored one.
import "fake-indexeddb/auto";
import { beforeEach, expect, it, vi } from "vitest";
import { idb } from "../src/db";
import { Queue } from "../src/queue";

const shrinkAll = vi.hoisted(() => vi.fn());
vi.mock("../src/downscale", () => ({ shrinkAll }));

const photo = (blob: Blob) => ({ source: "pwa" as const, files: [{ name: "a.jpg", blob }] });
const queue = () =>
  new Queue(
    idb,
    async () => ({ status: 201 }),
    undefined,
    () => false,
  );

beforeEach(async () => {
  shrinkAll.mockReset();
  for (const i of await idb.all()) await idb.del(i.id);
});

it("stores what shrinkAll gives back", async () => {
  const small = new Blob([new Uint8Array(3)]);
  shrinkAll.mockImplementation(async (cs) =>
    cs.map((c: ReturnType<typeof photo>) => ({ ...c, files: [{ name: "a.jpg", blob: small }] })),
  );
  const [item] = await queue().addAll([photo(new Blob([new Uint8Array(9)]))]);
  expect(shrinkAll).toHaveBeenCalledOnce();
  expect(item.files[0].blob.size).toBe(3);
  expect((await idb.all())[0].files[0].blob.size).toBe(3);
});

it("does not call it for text alone, or when replacing a stored item", async () => {
  const q = queue();
  await q.addAll([{ source: "pwa", text: "hi", files: [] }]);
  expect(shrinkAll).not.toHaveBeenCalled();
  shrinkAll.mockImplementation(async (cs) => cs);
  const [old] = await q.addAll([photo(new Blob([new Uint8Array(9)]))]);
  expect(shrinkAll).toHaveBeenCalledOnce();
  await q.addAll([photo(new Blob([new Uint8Array(9)]))], old);
  expect(shrinkAll).toHaveBeenCalledOnce(); // not again
});

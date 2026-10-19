import "fake-indexeddb/auto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { idb } from "../src/db";
import { backoff, type Item, Queue } from "../src/queue";
import { fromShare } from "../src/share";

const ULID = /^[0-9A-HJKMNP-TV-Z]{26}$/;

let clock = 1_000_000;
let sent: Item[] = [];
let replies: number[] = [];
const send = async (item: Item) => {
  sent.push(item);
  const status = replies.shift() ?? 201;
  if (status === 0) throw new TypeError("Failed to fetch");
  return status;
};
const queue = () => new Queue(idb, send, () => clock);

beforeEach(async () => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  sent = [];
  replies = [];
  for (const i of await idb.all()) await idb.del(i.id);
});
afterEach(() => vi.useRealTimers());

describe("queue", () => {
  it("stores a capture under a fresh ULID before sending it, then forgets it", async () => {
    const q = queue();
    replies = [0]; // offline
    const item = await q.add({ text: "milk", source: "pwa", files: [] });
    expect(item.id).toMatch(ULID);
    await q.flush();
    expect((await q.items()).map((i) => i.id)).toEqual([item.id]); // survives in IndexedDB
    clock += backoff(0);
    await q.flush();
    expect(await q.items()).toEqual([]);
    expect(sent.map((i) => i.id)).toEqual([item.id, item.id]); // the same id: idempotent
  });

  it("keeps photos as Blobs", async () => {
    const q = queue();
    replies = [503];
    const blob = new Blob(["jpeg bytes"], { type: "image/jpeg" });
    await q.add({ source: "pwa", files: [{ name: "a.jpg", blob }] });
    await q.flush();
    const [stored] = await new Queue(idb, send).items(); // as after a reload
    expect(await stored.files[0].blob.text()).toBe("jpeg bytes");
    expect(stored.files[0].blob.type).toBe("image/jpeg");
  });

  it("backs off on network and server errors", async () => {
    const q = queue();
    replies = [0, 500, 0];
    await q.add({ text: "x", source: "pwa", files: [] });
    await q.flush();
    let [item] = await q.items();
    expect(item).toMatchObject({ attempts: 1, next: clock + backoff(0), error: "offline" });
    await q.flush(); // not due yet: nothing sent
    expect(sent).toHaveLength(1);
    clock = item.next;
    await q.flush();
    [item] = await q.items();
    expect(item).toMatchObject({
      attempts: 2,
      next: clock + backoff(1),
      error: "server error (500)",
    });
    expect(backoff(2)).toBe(2 * backoff(1));
    expect(backoff(20)).toBe(5 * 60_000);
  });

  it("retries by timer once an item is due", async () => {
    const q = queue();
    replies = [0];
    await q.add({ text: "x", source: "pwa", files: [] });
    await q.flush();
    clock += backoff(0);
    await vi.advanceTimersByTimeAsync(backoff(0));
    await q.flush();
    expect(await q.items()).toEqual([]);
  });

  it("treats a 200 retry reply as success", async () => {
    const q = queue();
    replies = [200];
    await q.add({ text: "x", source: "pwa", files: [] });
    await q.flush();
    expect(await q.items()).toEqual([]);
  });

  it("marks refused captures failed until retry, and stops on no network", async () => {
    const q = queue();
    replies = [0];
    await q.add({ text: "a", source: "pwa", files: [] });
    clock += 1;
    await q.add({ text: "b", source: "pwa", files: [] });
    await q.flush();
    expect(sent.map((i) => i.text)).toEqual(["a"]); // b not tried while offline
    clock += backoff(0);
    replies = [413, 422];
    await q.flush();
    const items = await q.items();
    expect(items.map((i) => [i.failed, i.error])).toEqual([
      [true, "too large for the server"],
      [true, "refused (422)"],
    ]);
    sent = [];
    await q.flush();
    expect(sent).toEqual([]); // failed items wait for the user
    replies = [201, 201];
    await q.retry();
    expect(await q.items()).toEqual([]);
  });

  it("shares one run between concurrent flushes", async () => {
    const q = queue();
    replies = [0];
    await q.add({ text: "x", source: "pwa", files: [] });
    await Promise.all([q.flush(), q.flush(), q.flush()]);
    expect(sent).toHaveLength(1);
  });

  it("does not send while the browser is offline", async () => {
    const q = new Queue(
      idb,
      send,
      () => clock,
      () => false,
    );
    await q.add({ text: "x", source: "pwa", files: [] });
    await q.flush();
    expect(sent).toEqual([]);
  });
});

describe("share target", () => {
  const form = (fields: Record<string, string | File>) => {
    const f = new FormData();
    for (const [k, v] of Object.entries(fields)) f.append(k, v);
    return f;
  };

  it("lifts a link sent as text, keeping the page title", () => {
    expect(
      fromShare(form({ title: "A story", text: "A story https://example.com/a?b=1" })),
    ).toEqual({
      text: "A story",
      url: "https://example.com/a?b=1",
      source: "share",
      files: [],
    });
    expect(fromShare(form({ text: "https://example.com/" }))).toMatchObject({
      url: "https://example.com/",
      text: undefined,
    });
  });

  it("keeps plain text and a separate url", () => {
    expect(
      fromShare(form({ title: "Subject", text: "body text", url: "https://e.com" })),
    ).toMatchObject({
      text: "Subject\n\nbody text",
      url: "https://e.com",
    });
  });

  it("takes shared files and ignores an empty share", () => {
    const photo = new File(["px"], "p.jpg", { type: "image/jpeg" });
    const c = fromShare(form({ files: photo }));
    expect(c?.files.map((f) => f.name)).toEqual(["p.jpg"]);
    expect(fromShare(form({ files: new File([], "empty") }))).toBeNull();
    expect(fromShare(form({ title: " " }))).toBeNull();
  });

  it("queues a share like any other capture", async () => {
    const c = fromShare(form({ text: "shared note" }));
    if (!c) throw new Error("no capture");
    const q = queue();
    await q.add(c);
    await q.flush();
    expect(sent.map((i) => [i.source, i.text])).toEqual([["share", "shared note"]]);
  });
});

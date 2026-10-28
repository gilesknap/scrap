import "fake-indexeddb/auto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { drafts, idb } from "../src/db";
import { backoff, type Item, type Lock, newItem, Queue } from "../src/queue";
import { fromShare } from "../src/share";
import { firstOnly, split } from "../src/split";

const ULID = /^[0-9A-HJKMNP-TV-Z]{26}$/;

let clock = 1_000_000;
let sent: Item[] = [];
let replies: number[] = [];
const send = async (item: Item) => {
  sent.push(item);
  const status = replies.shift() ?? 201;
  if (status === 0) throw new TypeError("Failed to fetch");
  return { status, detail: status === 413 ? "over the 9 MB upload limit" : undefined };
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
    expect(item).toMatchObject({ attempts: 1, next: clock + backoff(0), error: "connection lost" });
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
      [true, "too large: over the 9 MB upload limit"],
      [true, "refused: HTTP 422"],
    ]);
    sent = [];
    await q.flush();
    expect(sent).toEqual([]); // failed items wait for the user
    replies = [201, 201];
    await q.retry();
    expect(await q.items()).toEqual([]);
  });

  it("retries or discards one failed capture", async () => {
    const q = queue();
    replies = [413, 413];
    const keep = await q.add({ text: "keep", source: "pwa", files: [] });
    await q.flush();
    clock += 1;
    const drop = await q.add({
      text: "drop",
      source: "pwa",
      files: [{ name: "big.jpg", blob: new Blob(["x"]) }],
    });
    await q.flush();
    expect((await q.items()).every((i) => i.failed)).toBe(true);
    const changes = vi.fn();
    q.onchange = changes;
    await q.discard(drop.id);
    expect(changes).toHaveBeenCalled(); // the badge updates
    expect((await idb.all()).map((i) => i.id)).toEqual([keep.id]); // Blob gone with it
    sent = [];
    await q.retry(keep.id);
    expect(sent.map((i) => i.id)).toEqual([keep.id]);
    expect(await q.items()).toEqual([]);
  });

  it("splits a capture refused as too large into one per photo", async () => {
    const q = queue();
    replies = [413];
    const photos = ["a", "b", "c"].map((n) => ({ name: `${n}.jpg`, blob: new Blob([n]) }));
    const big = await q.add({ text: "board", kind: "todo", source: "pwa", files: photos });
    await q.flush();
    replies = [0];
    await q.splitRetry(big.id, split);
    const parts = await q.items();
    expect(parts.map((i) => [i.text, i.kind, i.files.map((f) => f.name), i.failed])).toEqual([
      ["board", "todo", ["a.jpg"], undefined],
      [undefined, undefined, ["b.jpg"], undefined], // one todo, not three (#403)
      [undefined, undefined, ["c.jpg"], undefined],
    ]);
    expect(new Set(parts.map((i) => i.id)).size).toBe(3);
    expect(parts.map((i) => i.id)).not.toContain(big.id);
    expect(parts.every((i) => i.created_at === big.created_at)).toBe(true);
    expect(split({ source: "pwa", files: [] })).toEqual([]);
  });

  it("gives every part of a split capture its tags; the kind only the first, with the text", () => {
    const photos = ["a", "b"].map((n) => ({ name: `${n}.jpg`, blob: new Blob([n]) }));
    const parts = split({ text: "t", tags: ["diy", "garden"], source: "pwa", files: photos });
    expect(parts.map((p) => p.tags)).toEqual([
      ["diy", "garden"],
      ["diy", "garden"],
    ]);
    expect(split({ source: "pwa", files: photos }).every((p) => !("tags" in p))).toBe(true);
    const kinds = split({ text: "t", kind: "todo", hint: "todo", source: "pwa", files: photos });
    expect(kinds.map((p) => [p.text, p.kind, p.hint])).toEqual([
      ["t", "todo", "todo"],
      [undefined, undefined, undefined],
    ]);
    expect(split({ source: "pwa", files: photos }).every((p) => !("kind" in p))).toBe(true);
    // a todo's due date and priority too
    const due = { due: "2026-11-01", priority: "high" };
    const dated = split({
      text: "t",
      kind: "todo",
      ...due,
      place: "1",
      source: "pwa",
      files: photos,
    });
    expect(dated.map((p) => [p.due, p.priority, p.place])).toEqual([
      ["2026-11-01", "high", "1"],
      [undefined, undefined, undefined],
    ]);
    expect(split({ source: "pwa", files: photos }).every((p) => !("due" in p))).toBe(true);
  });

  it("leaves no stray token when a capture with tokens is split (#403)", async () => {
    const q = queue();
    replies = [413];
    const files = [
      { name: "a.jpg", blob: new Blob(["a"], { type: "image/jpeg" }) },
      { name: "m.pdf", blob: new Blob(["m"], { type: "application/pdf" }) },
      { name: "b.jpg", blob: new Blob(["b"], { type: "image/jpeg" }) },
    ];
    const text = "Trip\n\n⟦file 2⟧\n\nthe view ⟦image 3⟧ from the top\n\n⟦image 1⟧\n\nend";
    const big = await q.add({ text, source: "pwa", files });
    await q.flush();
    replies = [0];
    await q.splitRetry(big.id, split);
    const parts = await q.items();
    // The text with the first file, and only its token; the others' pages have no text
    expect(parts.map((i) => [i.text, i.files.map((f) => f.name)])).toEqual([
      ["Trip\n\n\nthe view  from the top\n\n⟦image 1⟧\n\nend", ["a.jpg"]],
      [undefined, ["m.pdf"]],
      [undefined, ["b.jpg"]],
    ]);
    expect(firstOnly("⟦file 2: m.pdf⟧\n⟦image 1⟧\n⟦image 12⟧")).toBe("⟦image 1⟧");
    expect(firstOnly("no tokens\n\nat all")).toBe("no tokens\n\nat all");
  });

  it("splits in one transaction: all parts and no original, or nothing", async () => {
    const q = queue();
    replies = [413];
    const files = ["a", "b"].map((n) => ({ name: n, blob: new Blob([n]) }));
    const big = await q.add({ text: "t", source: "pwa", files });
    await q.flush();
    // The second part cannot be stored: the first must not be kept, nor the original lost.
    const good = { ...big, id: "01J0000000000000000000000B" };
    const bad = { ...big, id: "01J0000000000000000000000C", oops: () => {} };
    await expect(idb.replace([good, bad], big.id)).rejects.toThrow();
    expect((await q.items()).map((i) => i.id)).toEqual([big.id]); // untouched: split again later
    replies = [0];
    await q.splitRetry(big.id, split);
    expect((await q.items()).map((i) => i.files[0].name)).toEqual(["a", "b"]);
  });

  it("splits once when two tabs split at the same moment", async () => {
    const q = queue();
    replies = [413];
    const files = ["a", "b", "c"].map((n) => ({ name: n, blob: new Blob([n]) }));
    const big = await q.add({ text: "t", source: "pwa", files });
    await q.flush();
    replies = [0, 0];
    const other = new Queue(idb, send, () => clock + 10); // its own ids, as another tab
    await Promise.all([q.splitRetry(big.id, split), other.splitRetry(big.id, split)]);
    expect((await q.items()).map((i) => i.files[0].name)).toEqual(["a", "b", "c"]);
  });

  it("says when an upload timed out", async () => {
    const slow = () => Promise.reject(new DOMException("too slow", "TimeoutError"));
    const q = new Queue(idb, slow, () => clock);
    await q.add({ text: "x", source: "pwa", files: [] });
    await q.flush();
    expect((await q.items())[0].error).toBe("timed out");
  });

  it("nudge sends what waits now, backoff or not, but not what failed", async () => {
    const q = queue();
    replies = [0, 413];
    await q.add({ text: "waiting", source: "pwa", files: [] });
    await q.flush(); // offline: backs off
    {
      const [item] = await q.items();
      expect(item.next).toBeGreaterThan(clock);
    }
    await q.flush(); // the timer's way: not due, nothing sent
    expect(sent).toHaveLength(1);
    await q.nudge(); // the app opened: sent now
    expect(sent).toHaveLength(2);
    expect((await q.items())[0]).toMatchObject({ failed: true }); // 413
    await q.nudge(); // failed stays failed until the user taps retry
    expect(sent).toHaveLength(2);
  });

  it("nudge makes no second attempt while an upload is running", async () => {
    let finish: () => void = () => {};
    let calls = 0;
    const slow = () => {
      calls++;
      return new Promise<{ status: number }>((ok) => (finish = () => ok({ status: 201 })));
    };
    const q = new Queue(idb, slow, () => clock);
    await q.add({ text: "big photo", source: "pwa", files: [] }); // starts sending
    await vi.waitFor(() => expect(calls).toBe(1));
    const nudged = q.nudge();
    // Whole macrotasks (setTimeout is faked, setImmediate is what fake-indexeddb runs on), not one
    // microtask: the store has had time to answer
    for (let i = 0; i < 20; i++) await new Promise((ok) => setImmediate(ok));
    expect(calls).toBe(1);
    finish();
    await nudged;
    expect(calls).toBe(1);
    expect(await q.items()).toEqual([]);
  });

  it("nudge waits for another tab's lock, then sends: a tab that died holding it", async () => {
    let release: () => void = () => {};
    let held: Promise<void> | null = new Promise<void>((ok) => (release = ok));
    const lock: Lock = async (fn, ifFree) => {
      if (held) {
        if (ifFree) return false; // another tab is uploading (or died mid-upload)
        await held;
      }
      await fn();
      return true;
    };
    const q = new Queue(
      idb,
      send,
      () => clock,
      () => true,
      lock,
    );
    await idb.put(newItem({ text: "waiting", source: "pwa", files: [] }, clock)); // queued earlier
    const nudged = q.nudge();
    await new Promise((ok) => queueMicrotask(() => ok(null)));
    expect(sent).toHaveLength(0); // no second upload on top of the other tab's
    held = null;
    release(); // that tab is gone: its lock comes free
    await nudged;
    expect(sent.map((i) => i.text)).toEqual(["waiting"]);
    expect(await q.items()).toEqual([]);
  });

  it("says the connection was lost, not offline, when an upload drops while online", async () => {
    let online = true;
    const q = new Queue(
      idb,
      send,
      () => clock,
      () => online,
    );
    replies = [0];
    await q.add({ text: "x", source: "pwa", files: [] });
    await q.flush();
    expect((await q.items())[0].error).toBe("connection lost");
    online = false;
    clock += backoff(1);
    replies = [0];
    await q.flush(); // offline: not even tried
    expect(sent).toHaveLength(1);
  });

  it("leaves nothing behind when storage refuses a capture", async () => {
    const full = {
      ...idb,
      replace: () => Promise.reject(new DOMException("full", "QuotaExceededError")),
    };
    const q = new Queue(full, send, () => clock);
    await expect(q.add({ text: "x", source: "pwa", files: [] })).rejects.toThrow("full");
    expect(sent).toEqual([]);
  });

  it("does not send one item from two tabs at once", async () => {
    let held = Promise.resolve();
    const lock = (fn: () => Promise<void>) => {
      const run = held.then(fn);
      held = run.catch(() => {});
      return run.then(() => true);
    };
    const a = new Queue(
      idb,
      send,
      () => clock,
      () => true,
      lock,
    );
    const b = new Queue(
      idb,
      send,
      () => clock,
      () => true,
      lock,
    );
    await idb.put({
      id: "01J0000000000000000000000A",
      text: "x",
      source: "pwa",
      files: [],
      created_at: "",
      attempts: 0,
      next: 0,
    });
    await Promise.all([a.flush(), b.flush()]);
    expect(sent).toHaveLength(1);
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

describe("drafts", () => {
  it("keeps text and photos, and forgets them", async () => {
    const photo = new Blob(["jpeg bytes"], { type: "image/jpeg" });
    await drafts.put("new", { text: "half a thought", files: [photo] });
    const kept = await drafts.get<{ text: string; files: Blob[] }>("new");
    expect(kept?.text).toBe("half a thought");
    expect(await kept?.files[0].text()).toBe("jpeg bytes");
    expect(await idb.all()).toEqual([]); // not in the queue
    await drafts.del("new");
    expect(await drafts.get("new")).toBeUndefined();
  });
});

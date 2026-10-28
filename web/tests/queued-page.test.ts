// An older build's queued Add photo (a capture for a page that exists): this build queues none,
// but one still waiting on a phone is sent as before, to its page.
import "fake-indexeddb/auto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { send } from "../src/api";
import { idb } from "../src/db";
import { type Item, newItem, Queue } from "../src/queue";

// The queue and send() for photos added to a page
class FakeXhr {
  static last: FakeXhr;
  upload = {};
  status = 0;
  responseText = "";
  url = "";
  body: unknown;
  onload?: () => void;
  constructor() {
    FakeXhr.last = this;
  }
  open(_: string, url: string) {
    this.url = url;
  }
  setRequestHeader() {}
  send(body: unknown) {
    this.body = body;
  }
  abort() {}
  answer(status: number, body: string) {
    this.status = status;
    this.responseText = body;
    this.onload?.();
  }
}
const Xhr = FakeXhr as unknown as typeof XMLHttpRequest;
const blob = new Blob(["jpeg"], { type: "image/jpeg" });
const photos = {
  source: "pwa" as const,
  files: [{ name: "p.jpg", blob }],
  page: "P1",
};

describe("sending photos for a page", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("posts them to the page, and says what the page is now", async () => {
    const seen: CustomEvent[] = [];
    const listen = (e: Event) => seen.push(e as CustomEvent);
    vi.stubGlobal("dispatchEvent", listen);
    const item = newItem(photos);
    const sent = send(item, Xhr);
    expect(FakeXhr.last.url).toBe("/api/pages/P1/captures");
    const form = FakeXhr.last.body as FormData;
    expect(form.get("id")).toBe(item.id);
    expect(form.has("base_rev")).toBe(false);
    expect(form.has("text")).toBe(false);
    FakeXhr.last.answer(201, '{"id": "P1", "rev": 3, "appended_on": 2}');
    await expect(sent).resolves.toMatchObject({ status: 201 });
    expect(seen[0].type).toBe("scrap:added");
    expect(seen[0].detail).toEqual({ id: "P1", rev: 3, appended_on: 2 });
    vi.unstubAllGlobals();

    const refused = send(item, Xhr);
    FakeXhr.last.answer(415, '{"detail": "Only images can be added to a page"}');
    await expect(refused).resolves.toEqual({
      status: 415,
      detail: expect.stringMatching(/images/),
    });
  });
});

describe("the queue, for photos added to a page", () => {
  beforeEach(async () => {
    for (const i of await idb.all()) await idb.del(i.id);
  });

  it("keeps them while offline and sends them once, to their page", async () => {
    const sent: Item[] = [];
    const replies = [0, 201];
    const q = new Queue(idb, async (item) => {
      sent.push(item);
      const status = replies.shift() ?? 201;
      if (!status) throw new TypeError("Failed to fetch");
      return { status };
    });
    const item = await q.add(photos);
    await q.flush();
    expect((await q.items()).map((i) => i.page)).toEqual(["P1"]);
    await q.retry();
    expect(sent.map((i) => [i.id, i.page])).toEqual([
      [item.id, "P1"],
      [item.id, "P1"],
    ]);
    expect(await q.items()).toEqual([]);
  });

  it("marks a refusal failed, as for any capture", async () => {
    const q = new Queue(idb, async () => ({ status: 415, detail: "Only images" }));
    await q.add(photos);
    await q.flush();
    expect((await q.items())[0]).toMatchObject({ failed: true, error: "refused: Only images" });
  });
});

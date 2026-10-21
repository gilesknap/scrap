import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { send, stallLimit } from "../src/api";
import { newItem } from "../src/queue";

// Just enough XMLHttpRequest to drive send(): the test plays the network.
class FakeXhr {
  static last: FakeXhr;
  upload: { onprogress?: () => void; onload?: () => void } = {};
  status = 0;
  responseText = "";
  timeout = 0;
  headers: Record<string, string> = {};
  body: unknown;
  onprogress?: () => void;
  onload?: () => void;
  onerror?: () => void;
  onabort?: () => void;
  ontimeout?: () => void;
  constructor() {
    FakeXhr.last = this;
  }
  open() {}
  setRequestHeader(k: string, v: string) {
    this.headers[k] = v;
  }
  send(body: unknown) {
    this.body = body;
  }
  abort() {
    this.onabort?.();
  }
  answer(status: number, body = "{}") {
    this.status = status;
    this.responseText = body;
    this.onload?.();
  }
}
const Xhr = FakeXhr as unknown as typeof XMLHttpRequest;
const photo = newItem({ source: "pwa", files: [{ name: "p.jpg", blob: new Blob(["x"]) }] });

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

it("lets a slow upload finish while it keeps moving", async () => {
  const sent = send(photo, Xhr, 60_000);
  const xhr = FakeXhr.last;
  expect(xhr.body).toBeInstanceOf(FormData);
  expect(xhr.timeout).toBe(15 * 60_000); // the hard ceiling
  for (let minute = 0; minute < 10; minute++) {
    vi.advanceTimersByTime(50_000); // 10 minutes in all, never 60 s without progress
    xhr.upload.onprogress?.();
  }
  xhr.upload.onload?.();
  vi.advanceTimersByTime(30_000); // the server takes a while to answer
  xhr.answer(201);
  await expect(sent).resolves.toEqual({ status: 201, detail: undefined });
});

it("gives up after a minute with no progress", async () => {
  const sent = send(photo, Xhr, 60_000);
  FakeXhr.last.upload.onprogress?.();
  vi.advanceTimersByTime(60_000);
  await expect(sent).rejects.toMatchObject({ name: "TimeoutError" });
});

it("passes on the server's answer and reason", async () => {
  const note = newItem({ text: "hi", source: "pwa", files: [] });
  const sent = send(note, Xhr);
  expect(FakeXhr.last.headers["Content-Type"]).toBe("application/json");
  expect(JSON.parse(FakeXhr.last.body as string)).toMatchObject({ id: note.id, text: "hi" });
  FakeXhr.last.answer(413, '{"detail": "over the 1 MB upload limit"}');
  await expect(sent).resolves.toEqual({ status: 413, detail: "over the 1 MB upload limit" });
  const lost = send(note, Xhr);
  FakeXhr.last.onerror?.();
  await expect(lost).rejects.toBeInstanceOf(TypeError);
});

it("waits generously for the answer once the body is handed over", async () => {
  // The phone's send buffer may still be draining: silence now is not a stall.
  const big = newItem({
    source: "pwa",
    files: [{ name: "p.jpg", blob: new Blob([new Uint8Array(4 * 2 ** 20)]) }],
  });
  const sent = send(big, Xhr, 60_000);
  const xhr = FakeXhr.last;
  xhr.upload.onprogress?.();
  xhr.upload.onload?.();
  vi.advanceTimersByTime(90_000);
  xhr.answer(201);
  await expect(sent).resolves.toMatchObject({ status: 201 });

  const lost = send(big, Xhr, 60_000);
  FakeXhr.last.upload.onload?.();
  vi.advanceTimersByTime(800_000); // 4 MB at 5 KB/s is about 820 s
  FakeXhr.last.answer(200);
  await expect(lost).resolves.toMatchObject({ status: 200 });
  const never = send(big, Xhr, 60_000);
  FakeXhr.last.upload.onload?.();
  vi.advanceTimersByTime(820_000);
  await expect(never).rejects.toMatchObject({ name: "TimeoutError" });

  const small = send(photo, Xhr, 60_000); // a tiny body still gets two minutes
  FakeXhr.last.upload.onload?.();
  vi.advanceTimersByTime(119_000);
  FakeXhr.last.answer(201);
  await expect(small).resolves.toMatchObject({ status: 201 });
});

it("accepts only a sane stall limit from the test hook", () => {
  expect(stallLimit(null)).toBe(60_000);
  expect(stallLimit("3000")).toBe(3000);
  for (const bad of ["", "1", "-1", "abc", "NaN", "Infinity", "999", "600001"]) {
    expect(stallLimit(bad)).toBe(60_000);
  }
});

it("sends a capture's tags: a JSON list, or a form field per tag", () => {
  const note = newItem({ text: "hi", tags: ["diy", "garden tools"], source: "pwa", files: [] });
  void send(note, Xhr);
  expect(JSON.parse(FakeXhr.last.body as string).tags).toEqual(["diy", "garden tools"]);
  const shot = newItem({ ...note, files: [{ name: "p.jpg", blob: new Blob(["x"]) }] });
  void send(shot, Xhr);
  const form = FakeXhr.last.body as FormData;
  expect(form.getAll("tags")).toEqual(["diy", "garden tools"]);
  expect(form.get("text")).toBe("hi");
  void send(photo, Xhr); // none: no field
  expect((FakeXhr.last.body as FormData).has("tags")).toBe(false);
});

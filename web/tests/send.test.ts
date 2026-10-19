import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { send } from "../src/api";
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

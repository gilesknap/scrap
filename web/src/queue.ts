// The offline capture queue. Every capture is stored here (IndexedDB) under a ULID minted
// before it is queued, then posted; the server answers 201 the first time and 200 to a
// retry, so sending twice is harmless. Network and 5xx errors retry with backoff; other
// 4xx answers mark the item failed until the user taps retry.
import type { Store } from "./db";
import { ulid } from "./ulid";

export type Hint = "todo" | "consume";

export interface Capture {
  text?: string;
  url?: string;
  hint?: Hint;
  source: "pwa" | "share";
  files: { name: string; blob: Blob }[];
}

export interface Item extends Capture {
  id: string;
  created_at: string;
  attempts: number;
  next: number; // not before this time (ms)
  failed?: boolean;
  error?: string;
}

/** POST the item; resolve to the HTTP status and the server's reason, or reject. */
export type Send = (item: Item) => Promise<{ status: number; detail?: string }>;

/** Run fn holding the queue lock, so two open tabs never send the same item at once. */
export type Lock = (fn: () => Promise<void>) => Promise<void>;
const webLock: Lock = (fn) =>
  globalThis.navigator?.locks ? navigator.locks.request("scrap-queue", fn) : fn();

export const backoff = (attempts: number) => Math.min(5 * 60_000, 2000 * 2 ** attempts);

export function newItem(c: Capture, now = Date.now()): Item {
  return { ...c, id: ulid(now), created_at: new Date(now).toISOString(), attempts: 0, next: 0 };
}

/** One capture per file, the text with the first: for photos too big to send together. */
export const split = ({ text, url, hint, source, files }: Capture): Capture[] =>
  files.map((f, i) => ({
    text: i ? undefined : text,
    url: i ? undefined : url,
    hint: i ? undefined : hint, // the hint goes with the text
    source,
    files: [f],
  }));

const permanent = (status: number) => status >= 400 && status < 500 && ![408, 429].includes(status);

export class Queue {
  onchange = () => {};
  private running?: Promise<void>;
  private timer?: ReturnType<typeof setTimeout>;

  constructor(
    private store: Store,
    private send: Send,
    private now = () => Date.now(),
    private online = () => true,
    private lock = webLock,
  ) {}

  /** Store a capture and start sending it; resolves once it is safely queued. */
  async add(c: Capture): Promise<Item> {
    return (await this.addAll([c]))[0];
  }

  /** Store captures (all or none: one transaction) and start sending them. */
  async addAll(cs: Capture[], replacing?: Item): Promise<Item[]> {
    const items = cs.map((c, n) => newItem(c, this.now() + n));
    if (replacing) for (const i of items) i.created_at = replacing.created_at;
    await this.store.replace(items, replacing?.id);
    this.onchange();
    void this.flush();
    return items;
  }

  async items(): Promise<Item[]> {
    return (await this.store.all()).sort((a, b) => (a.id < b.id ? -1 : 1));
  }

  /** Send everything that is due, one at a time; concurrent calls share one run. */
  flush(): Promise<void> {
    this.running ??= this.run().finally(() => {
      this.running = undefined;
    });
    return this.running;
  }

  /** Tap to retry: failed and waiting items (or just the one with id) are due now. */
  async retry(id?: string): Promise<void> {
    await this.running;
    for (const item of await this.items()) {
      if (id && item.id !== id) continue;
      await this.store.put({ ...item, failed: false, error: undefined, next: 0 });
    }
    return this.flush();
  }

  /** Re-queue a capture refused as too large as one capture per photo (new ids). */
  async splitRetry(id: string): Promise<void> {
    await this.running;
    const item = (await this.items()).find((i) => i.id === id);
    if (!item) return;
    await this.addAll(split(item), item); // in one transaction: no double upload
    return this.flush();
  }

  /** Give up on a capture: it and its files leave the phone. */
  async discard(id: string): Promise<void> {
    await this.running;
    await this.store.del(id);
    this.onchange();
  }

  private run() {
    return this.lock(() => this.sendDue());
  }

  private async sendDue() {
    clearTimeout(this.timer);
    if (!this.online()) return; // no timer: the "online" event flushes again
    for (const item of await this.items()) {
      if (item.failed || item.next > this.now()) continue;
      const { status, detail } = await this.send(item).catch((e) => ({
        status: 0,
        detail: e?.name === "TimeoutError" ? "timed out" : "offline",
      }));
      if (status === 200 || status === 201) {
        await this.store.del(item.id);
      } else if (permanent(status)) {
        const error = `${status === 413 ? "too large" : "refused"}: ${detail || `HTTP ${status}`}`;
        await this.store.put({ ...item, failed: true, error });
      } else {
        const error = status ? `server error (${status})` : detail;
        const next = this.now() + backoff(item.attempts);
        await this.store.put({ ...item, attempts: item.attempts + 1, next, error });
      }
      this.onchange();
      if (!status) break; // no network: the rest would fail too
    }
    const due = (await this.items()).filter((i) => !i.failed).map((i) => i.next);
    if (due.length) {
      const wait = Math.max(1000, Math.min(...due) - this.now());
      this.timer = setTimeout(() => void this.flush(), wait);
    }
  }
}

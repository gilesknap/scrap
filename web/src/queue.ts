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

/** POST the item; resolve to the HTTP status, or 0 if the network failed. */
export type Send = (item: Item) => Promise<number>;

export const backoff = (attempts: number) => Math.min(5 * 60_000, 2000 * 2 ** attempts);

export function newItem(c: Capture, now = Date.now()): Item {
  return { ...c, id: ulid(now), created_at: new Date(now).toISOString(), attempts: 0, next: 0 };
}

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
  ) {}

  /** Store a capture and start sending it; resolves once it is safely queued. */
  async add(c: Capture): Promise<Item> {
    const item = newItem(c, this.now());
    await this.store.put(item);
    this.onchange();
    void this.flush();
    return item;
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

  /** Tap to retry: failed and waiting items are all due now. */
  async retry(): Promise<void> {
    await this.running;
    for (const item of await this.items()) {
      await this.store.put({ ...item, failed: false, error: undefined, next: 0 });
    }
    return this.flush();
  }

  private async run() {
    clearTimeout(this.timer);
    if (this.online()) {
      for (const item of await this.items()) {
        if (item.failed || item.next > this.now()) continue;
        const status = await this.send(item).catch(() => 0);
        if (status === 200 || status === 201) {
          await this.store.del(item.id);
        } else if (permanent(status)) {
          const error = status === 413 ? "too large for the server" : `refused (${status})`;
          await this.store.put({ ...item, failed: true, error });
        } else {
          const error = status ? `server error (${status})` : "offline";
          const next = this.now() + backoff(item.attempts);
          await this.store.put({ ...item, attempts: item.attempts + 1, next, error });
        }
        this.onchange();
        if (!status) break; // no network: the rest would fail too
      }
    }
    const due = (await this.items()).filter((i) => !i.failed).map((i) => i.next);
    if (due.length) {
      const wait = Math.max(1000, Math.min(...due) - this.now());
      this.timer = setTimeout(() => void this.flush(), wait);
    }
  }
}

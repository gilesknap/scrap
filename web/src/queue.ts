// The offline capture queue. Every capture is stored here (IndexedDB) under a ULID minted
// before it is queued, then posted; the server answers 201 the first time and 200 to a
// retry, so sending twice is harmless. Network and 5xx errors retry with backoff; other
// 4xx answers mark the item failed until the user taps retry.
import type { Store } from "./db";
import { ulid } from "./ulid";

/** A page kind the user can choose (the API names them). */
export type Kind = "note" | "todo" | "consume" | "whiteboard" | "document";

export interface Capture {
  text?: string;
  url?: string;
  kind?: Kind; // chosen in the composer; none: the server decides (a note, or ingest)
  hint?: string; // the kind, as queued by older builds
  tags?: string[]; // the new page's, as the server cleans them
  due?: string; // a todo's (YYYY-MM-DD) and its priority, from the composer
  priority?: string;
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

/** Run fn holding the queue lock, so two open tabs never send the same item at once;
 * resolves true once it ran. ifFree: skip fn (resolve false at once) if another tab holds it. */
export type Lock = (fn: () => Promise<void>, ifFree?: boolean) => Promise<boolean>;
const webLock: Lock = (fn, ifFree = false) =>
  globalThis.navigator?.locks
    ? navigator.locks.request("scrap-queue", { ifAvailable: ifFree }, (l) =>
        l ? fn().then(() => true) : false,
      )
    : fn().then(() => true);

export const backoff = (attempts: number) => Math.min(5 * 60_000, 2000 * 2 ** attempts);

export function newItem(c: Capture, now = Date.now()): Item {
  return { ...c, id: ulid(now), created_at: new Date(now).toISOString(), attempts: 0, next: 0 };
}

/** One capture per file, the text with the first: for photos too big to send together.
 * Each page gets the tags. */
export const split = (c: Capture): Capture[] =>
  c.files.map((f, i) => {
    const part: Capture = { ...(!i && { text: c.text, url: c.url }), source: c.source, files: [f] };
    // The text once; the kind, its due date and priority, and the tags on every part
    for (const k of ["kind", "hint", "tags", "due", "priority"] as const)
      if (c[k]) Object.assign(part, { [k]: c[k] });
    return part;
  });

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

  /** The app opened, came back into view or online: send what is waiting now, backoff or
   * not (failed items stay failed). No second attempt on top of an upload already running:
   * here, it joins it; in another tab, it waits for that tab's lock and then sends what is
   * due, as a flush does (if that tab died holding it, the lock comes free). */
  nudge(): Promise<void> {
    this.running ??= this.lock(() => this.sendDue(true), true)
      .then(async (ran) => {
        if (!ran) await this.run(); // not flush(): that would wait on this very promise
      })
      .finally(() => {
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

  private async run() {
    await this.lock(() => this.sendDue());
  }

  private async sendDue(now = false) {
    clearTimeout(this.timer);
    if (!this.online()) return; // no timer: the "online" event flushes again
    for (const item of await this.items()) {
      if (item.failed || (!now && item.next > this.now())) continue;
      const { status, detail } = await this.send(item).catch((e) => ({
        status: 0,
        // A dropped upload while the phone says it is online is not "offline"
        detail:
          e?.name === "TimeoutError" ? "timed out" : this.online() ? "connection lost" : "offline",
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

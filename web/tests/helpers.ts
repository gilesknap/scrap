// Helpers shared by the unit tests: a localStorage, and a file's ingest state.
import type { FileIngest } from "../src/api";

/** A localStorage that keeps what is set, as a phone's would: its map. Put it away after
 * each test with afterEach(dropStorage). */
export function storage() {
  const m = new Map<string, string>();
  (globalThis as { localStorage?: Storage }).localStorage = {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, String(v)),
    removeItem: (k: string) => void m.delete(k),
  } as Storage;
  return m;
}

/** Take away the localStorage storage() put in place. */
export function dropStorage() {
  delete (globalThis as { localStorage?: Storage }).localStorage;
}

/** A PDF's ingest state, read whole (12 pages, searchable), with o laid over it. */
export const pdf = (o: Partial<FileIngest>): FileIngest => ({
  state: "done",
  failures: 0,
  error: null,
  kind: "pdf",
  pages: 12,
  pages_read: 12,
  truncated: false,
  text_chars: 900,
  searchable: true,
  ...o,
});

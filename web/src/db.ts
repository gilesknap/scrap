// The smallest IndexedDB wrapper the app needs: the offline queue (keyed by id), and
// drafts of unsaved text and photos (keyed by what they are a draft of).
import type { Item } from "./queue";

export interface Store {
  all(): Promise<Item[]>;
  put(item: Item): Promise<unknown>;
  del(id: string): Promise<unknown>;
  /** In one transaction: store add, then delete id (if given). All or nothing. */
  replace(add: Item[], id?: string): Promise<unknown>;
}

let db: Promise<IDBDatabase> | undefined;

function open(): Promise<IDBDatabase> {
  return new Promise((ok, fail) => {
    const req = indexedDB.open("scrap", 2);
    req.onupgradeneeded = (e) => {
      if (e.oldVersion < 1) req.result.createObjectStore("queue", { keyPath: "id" });
      if (e.oldVersion < 2) req.result.createObjectStore("drafts");
    };
    req.onsuccess = () => {
      const d = req.result;
      d.onclose = d.onversionchange = () => {
        d.close();
        db = undefined; // open again on the next call
      };
      ok(d);
    };
    req.onerror = () => {
      db = undefined;
      fail(req.error);
    };
  });
}

function run<T>(
  mode: IDBTransactionMode,
  op: (s: IDBObjectStore) => IDBRequest | undefined,
  name = "queue",
): Promise<T> {
  db ??= open();
  return db.then(
    (d) =>
      new Promise<T>((ok, fail) => {
        const tx = d.transaction(name, mode);
        let req: IDBRequest | undefined;
        try {
          req = op(tx.objectStore(name));
        } catch (e) {
          tx.abort(); // nothing of a failed replace is kept
          return fail(e);
        }
        tx.oncomplete = () => ok(req?.result);
        tx.onerror = tx.onabort = () => fail(tx.error);
      }),
  );
}

export const idb: Store = {
  all: () => run("readonly", (s) => s.getAll()),
  put: (item) => run("readwrite", (s) => s.put(item)),
  del: (id) => run("readwrite", (s) => s.delete(id)),
  replace: (add, id) =>
    run("readwrite", (s) => {
      const write = () => {
        for (const item of add) s.put(item);
        if (id) s.delete(id);
      };
      if (!id) {
        write();
        return;
      }
      // Only if the original is still there: another tab may have split it already.
      const req = s.get(id);
      req.onsuccess = () => req.result && write();
    }),
};

/** Drafts: whatever an editor needs to put its fields back, Blobs included. */
export const drafts = {
  get: <T>(key: string) => run<T | undefined>("readonly", (s) => s.get(key), "drafts"),
  put: (key: string, value: unknown) => run("readwrite", (s) => s.put(value, key), "drafts"),
  del: (key: string) => run("readwrite", (s) => s.delete(key), "drafts"),
  /** In one transaction: the draft under from, if there is one, takes to's place. Gives it and
   * the one it replaced (undefined: none). */
  move: <T>(from: string, to: string) => {
    let out: [T | undefined, T | undefined] = [undefined, undefined];
    return run(
      "readwrite",
      (s) => {
        const a = s.get(from);
        a.onsuccess = () => {
          if (a.result === undefined) return;
          const b = s.get(to);
          b.onsuccess = () => {
            out = [a.result, b.result];
            s.put(a.result, to);
            s.delete(from);
          };
        };
        return undefined;
      },
      "drafts",
    ).then(() => out);
  },
};

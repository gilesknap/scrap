// The smallest IndexedDB wrapper the offline queue needs: one object store keyed by id.
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
    const req = indexedDB.open("scrap", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("queue", { keyPath: "id" });
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
): Promise<T> {
  db ??= open();
  return db.then(
    (d) =>
      new Promise<T>((ok, fail) => {
        const tx = d.transaction("queue", mode);
        let req: IDBRequest | undefined;
        try {
          req = op(tx.objectStore("queue"));
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

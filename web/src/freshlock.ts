// A fresh capture's key and its Web Lock, held while its composer is open (fresh.ts says why).
// Apart from fresh.ts, which Capture loads, so it comes only with the composer's chunk.
import { FRESH, lockName, locks, promote } from "./fresh";
import { ulid } from "./ulid";

/** A key for a fresh capture's draft, and its lock, held until release() (idempotent). With no
 * Web Locks (older browsers) nothing is held: recover() then takes any fresh draft, as before. */
export async function fresh(): Promise<{ key: string; release: () => void }> {
  const key = `${FRESH}-${ulid()}`; // in time order, as recover() takes them
  let release = () => {};
  const held = new Promise<void>((r) => {
    release = r;
  });
  const l = locks();
  if (l)
    await new Promise<void>((granted) => {
      // A name no one else has: granted at once; held until released (or the tab is gone)
      l.request(lockName(key), () => {
        granted();
        return held;
      }).catch(() => granted());
    });
  return { key, release };
}

/** Left by Back: the fresh draft takes the kept one's place (promote()), its lock let go only
 * once it has, so no other tab's recover() can take it meanwhile. */
export const leave = (
  slot: { key: string; release: () => void },
  said: (older: boolean) => string,
) => void promote(slot.key, said).finally(slot.release);

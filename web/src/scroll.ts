// Back (the top bar's, the jump, the phone's own) and Forward come back to a screen scrolled
// where it was left: where it is scrolled to rides in its history entry (y), written as it
// scrolls (debounced, so the phone's Back finds it) and just before go() leaves it, and read
// once the screen is drawn and tall enough. The search screen keeps its own (search.ts).

const OWN = "/search"; // keeps and restores its own scroll
let saving = 0;
let hold = false; // a screen is being drawn or put back: its scroll events are not the user's

const overlay = (s: { [k: string]: unknown } | null) =>
  !!(s?.editor || s?.settings || s?.viewer || s?.drawing);

/** Write where the screen is scrolled to into its entry, now. */
export function keepScroll() {
  clearTimeout(saving);
  const s = history.state;
  if (hold || location.pathname === OWN || overlay(s)) return;
  history.replaceState({ ...s, y: Math.round(scrollY) }, "");
}

/** Keep each screen's scroll as it scrolls (main.ts, once): the browser's own restore is off,
 * since it would come before the screen is drawn. */
export function watchScroll() {
  history.scrollRestoration = "manual";
  addEventListener(
    "scroll",
    () => {
      clearTimeout(saving);
      saving = window.setTimeout(keepScroll, 150);
    },
    { passive: true },
  );
}

/** A new screen is being drawn (main.ts): no scroll is kept until it is put back. */
export function holdScroll() {
  clearTimeout(saving); // a late write would land on the new entry
  hold = true;
}

/** Put the screen just drawn back where it was left, once it is tall enough (its content may
 * still be coming: a page's text, a list's rows), for up to 3 s; never against the user (a
 * touch, click, wheel or key stops it) and never smoothly. */
export function restoreScroll(signal: AbortSignal) {
  const y = location.pathname === OWN ? 0 : Number(history.state?.y) || 0;
  if (!y) {
    hold = false;
    return;
  }
  const view = document.getElementById("view") as HTMLElement;
  const until = Date.now() + 3000;
  const user = ["pointerdown", "touchstart", "wheel", "keydown"];
  const stop = () => {
    watch.disconnect();
    for (const t of user) removeEventListener(t, stop, true);
    if (!signal.aborted) hold = false; // else the next screen's to release
  };
  const put = () => {
    if (signal.aborted) return stop();
    const max = document.documentElement.scrollHeight - innerHeight;
    scrollTo({ top: Math.min(y, Math.max(0, max)), behavior: "instant" });
    if (max >= y || Date.now() > until) stop();
  };
  const watch = new ResizeObserver(put);
  signal.addEventListener("abort", stop);
  watch.observe(view);
  for (const t of user) addEventListener(t, stop, { capture: true, passive: true });
  setTimeout(stop, 3000); // not that tall by now: as far as it goes, and the user's again
  put();
}

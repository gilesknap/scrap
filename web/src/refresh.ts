// The search screen's refresh when the capture queue changes (a lazy chunk, so not in the shell).
// It waits, trying again, while the user is mid-gesture: a finger down, the page scrolling,
// focus or a text selection inside the results. Otherwise a swipe, tap or selection would be
// replaced under them.

/** Call go() 300 ms after a queue change (a queue drains in a burst) once it is safe to; stale()
 * says the screen has something else to do first (typing: its own run is coming). */
export function watch(
  signal: AbortSignal,
  results: Element,
  o: { stale: () => boolean; go: () => void },
) {
  let down = 0; // pointers down
  let moved = 0; // when the page last scrolled
  let timer: ReturnType<typeof setTimeout>;
  const on = { capture: true, passive: true, signal };
  addEventListener("pointerdown", () => down++, on);
  addEventListener("pointerup", () => (down = Math.max(0, down - 1)), on);
  addEventListener("pointercancel", () => (down = 0), on);
  addEventListener("scroll", () => (moved = Date.now()), on);
  const refresh = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (o.stale()) return;
      const sel = getSelection();
      const busy =
        down ||
        Date.now() - moved < 400 ||
        (results.contains(document.activeElement) && document.activeElement !== results) ||
        (sel && !sel.isCollapsed && results.contains(sel.anchorNode));
      if (busy) return refresh();
      o.go();
    }, 300);
  };
  document.addEventListener("queuechange", refresh, { signal });
  signal.addEventListener("abort", () => clearTimeout(timer));
}

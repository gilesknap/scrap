// The search screen's refresh when the capture queue changes (a lazy chunk, so not in the shell).
// It waits, trying again, while the user is mid-gesture: a finger down, the page scrolling,
// focus anywhere but the search box (a panel's box, a panel, a control) or a text selection. Otherwise a swipe, tap or selection would be
// replaced under them.

/** Call go() 300 ms after a queue change (a queue drains in a burst) once it is safe to. Not
 * while the box holds other than the query that ran (the address: typing, its own run is
 * coming) or a scroll is being restored. */
export function watch(
  signal: AbortSignal,
  input: HTMLInputElement,
  restoring: () => boolean,
  go: () => void,
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
      if (
        input.value.trim() !== (new URLSearchParams(location.search).get("q") ?? "") ||
        restoring()
      )
        return;
      const sel = getSelection();
      const busy =
        down ||
        Date.now() - moved < 400 ||
        (document.activeElement !== input && document.activeElement !== document.body) ||
        (sel && !sel.isCollapsed);
      if (busy) return refresh();
      go();
    }, 300);
  };
  document.addEventListener("queuechange", refresh, { signal });
  signal.addEventListener("abort", () => clearTimeout(timer));
}

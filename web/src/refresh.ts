import { h } from "./ui";

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
): (() => void) & { calm: () => boolean } {
  let down = 0; // pointers down
  let moved = 0; // when the page last scrolled
  let touched = 0; // when a pointer last went down or up (its click comes after the up)
  let timer: ReturnType<typeof setTimeout>;
  const on = { capture: true, passive: true, signal };
  const touch = (delta: (n: number) => number) => () => {
    touched = Date.now();
    down = delta(down);
  };
  addEventListener(
    "pointerdown",
    touch((n) => n + 1),
    on,
  );
  addEventListener(
    "pointerup",
    touch((n) => Math.max(0, n - 1)),
    on,
  );
  addEventListener(
    "pointercancel",
    touch(() => 0),
    on,
  );
  addEventListener("scroll", () => (moved = Date.now()), on);
  // Whether the user is mid-gesture or has something selected or focused in the results
  const busy = () => {
    const sel = getSelection();
    return !!(
      down ||
      Date.now() - moved < 400 ||
      Date.now() - touched < 400 ||
      // (focus on the screen's own controls: the top bar's New, back from its composer, is not)
      (document.activeElement !== input && !!document.activeElement?.closest("#view")) ||
      (sel && !sel.isCollapsed)
    );
  };
  const refresh = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (
        input.value.trim() !== (new URLSearchParams(location.search).get("q") ?? "") ||
        restoring()
      )
        return refresh();
      if (busy()) return refresh();
      go();
    }, 300);
  };
  signal.addEventListener("abort", () => clearTimeout(timer));
  // For the screen to call on a queue change; calm() asks again just before it draws what a
  // refresh read: a finger that came down while it was read must not have the rows replaced
  // before its tap's click (pointerdown, pointerup and click are a few ms apart)
  return Object.assign(refresh, { calm: () => !busy() });
}

/** Whether a refresh leaves the rows be: the server out of reach is not an answer, and nothing
 * new in the links and snippets (a row the swipe chunk has dressed has more text) is no change. */
export const keeps = (shown: Node, now: Node) => {
  const text = (el: Node) =>
    [...(el as Element).querySelectorAll("a, small")].map((e) => e.textContent).join();
  return !!h("div", {}, shown).querySelector(".failed") || text(shown) === text(now);
};

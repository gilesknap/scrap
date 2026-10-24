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
): () => void {
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
        return refresh();
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
  signal.addEventListener("abort", () => clearTimeout(timer));
  return refresh; // for the screen to call on a queue change
}

/** Whether a refresh leaves the rows be: the server out of reach is not an answer, and nothing
 * new in the links and snippets (a row the swipe chunk has dressed has more text) is no change. */
export const keeps = (shown: Node, now: Node) => {
  const text = (el: Node) =>
    [...(el as Element).querySelectorAll("a, small")].map((e) => e.textContent).join();
  return !!h("div", {}, shown).querySelector(".failed") || text(shown) === text(now);
};

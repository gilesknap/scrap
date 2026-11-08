// Where scrap opens (its home, "/"): Capture on a phone, Search on a computer, where Capture
// has an address of its own (/capture). Asked at each navigation, so a window that crosses the
// line is right next time. Below ui.ts: imports nothing.

/** A computer, as css/desktop.css has it: a mouse and a wide window. */
export const DESK = "(min-width: 900px) and (hover: hover) and (pointer: fine)";
export const desk = () => matchMedia(DESK).matches;
/** The screen "/" shows, as Back and "Back to …" name it. */
export const home = () => (desk() ? "Search" : "Capture");
/** Capture's address, as the nav links it: home on a phone, /capture on a computer. */
export const capturePath = () => (desk() ? "/capture" : "/");
/** The address "/" (with this query) takes: none on a phone, where it is Capture; on a computer
 * the search screen's, or Capture's for a share (the share target lands on "/?shared=1"). */
export const homeAt = (query: string) =>
  !desk() ? null : new URLSearchParams(query).has("shared") ? `/capture${query}` : "/search";

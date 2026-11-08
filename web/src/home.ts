// Where scrap opens (its home, "/"): Capture on a phone, Search on a computer, where Capture
// has an address of its own (/capture). Asked at each navigation, so a window that crosses the
// line is right next time. Below ui.ts: imports nothing.

/** A computer, as css/desktop.css has it: a mouse and a wide window. */
export const DESK = "(min-width: 900px) and (hover: hover) and (pointer: fine)";
export const desk = () => matchMedia(DESK).matches;
/** Home is Search: on a computer, and online (offline, Search has nothing to show, Capture
 * does: the installed app opened with no connection). */
const searchHome = () => desk() && navigator.onLine;
/** The screen "/" shows, as Back and "Back to …" name it. */
export const home = () => (searchHome() ? "Search" : "Capture");
/** Capture's address, as the nav links it: home on a phone, /capture on a computer. */
export const capturePath = () => (desk() ? "/capture" : "/");
/** The address "/" (with this query: "" or "?…") takes: none on a phone, where it is Capture;
 * on a computer Capture's for a share (the share target lands on "/?shared=1"), else the
 * search screen's with the query, or offline, Capture's. */
export const homeAt = (query: string) =>
  !desk()
    ? null
    : new URLSearchParams(query).has("shared")
      ? `/capture${query}`
      : searchHome()
        ? `/search${query}`
        : "/capture";
/** A page opened cold goes up to its parent, by its kind as drawn (none while it loads): a
 * todo's is Todos, a topic page's Topics, any other's home. Back's label and where it goes. */
export const parent = (kind?: string): [name: string, path: string] =>
  kind === "todo" ? ["Todos", "/todos"] : kind === "topic" ? ["Topics", "/topics"] : [home(), "/"];

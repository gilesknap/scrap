// The top bar's Back on a page opened cold: a chunk of its own, which the service worker keeps
// (vite.config.ts OFFLINE), so a stalled link cannot hold its import.

/** Up from a page with nothing of the app's behind it (main.ts's Back goes up one level, to
 * the linking page or the list, while go()'s marks say one is): the page was opened cold from a
 * link or a share, so up to a parent, where Back's label (main.ts's nameBack) says, with no
 * request: from the page as drawn, a todo's is Todos, a topic's Topics, any other page's
 * Capture; while it is still loading, Capture. Delete on such a page goes there too (page.ts).
 * from: the address Back was tapped on, so Back does nothing if the app has left it since. */
export function up(go: (path: string, replace: boolean) => void, from = location.pathname) {
  // as page.ts marks it ("topic" for a topic page), and as nameBack reads it
  const kind = document.querySelector<HTMLElement>("#view .page[data-kind]")?.dataset.kind;
  const parents: Record<string, string> = { todo: "/todos", topic: "/topics" };
  const to = (kind && parents[kind]) ?? "/";
  if (location.pathname === from) go(to, true); // unless gone elsewhere meanwhile
}

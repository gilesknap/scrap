// The top bar's Back (iPhone's home-screen app only): a chunk of its own.
import { api } from "./api";

const ASK_MS = 1500; // a kind not known by then (a stalled link): Capture, not a dead button

/** The kind of the page on screen: as drawn (no request), else (still loading) asked for, for
 * ASK_MS at most; "" unknown. */
async function kindShown() {
  const drawn = document.querySelector<HTMLElement>("#view .page[data-kind]")?.dataset.kind;
  if (drawn) return drawn;
  const key = decodeURIComponent(location.pathname.slice("/p/".length));
  const signal = AbortSignal.timeout(ASK_MS); // its request ends then, its late answer unheard
  return api<{ kind: string; topic?: unknown }>(`pages/${encodeURIComponent(key)}`, {
    signal,
  }).then(
    (p) => (p.topic ? "topic" : p.kind), // as page.ts marks it
    () => "",
  );
}

/** Up from a page with nothing of the app's behind it (main.ts's Back goes up one level, to
 * the linking page or the list, while go()'s marks say one is): the page was opened cold from a
 * link or a share, so up to a parent: a todo's is Todos, a topic's Topics, any other page's
 * Capture, as is one whose kind is not known soon (a stalled link). Delete on such a page goes
 * there too (page.ts). */
export async function up(go: (path: string, replace: boolean) => void) {
  const from = location.pathname;
  const parents: Record<string, string> = { todo: "/todos", topic: "/topics" };
  const to = parents[await kindShown()] ?? "/";
  if (location.pathname === from) go(to, true); // unless gone elsewhere meanwhile
}

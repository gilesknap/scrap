// The top bar's Back (iPhone's home-screen app only): a chunk of its own.
import { api } from "./api";

/** The kind of the page on screen: as drawn, else (still loading) asked for; "" unknown. */
async function kindShown() {
  const drawn = document.querySelector<HTMLElement>("#view .page[data-kind]")?.dataset.kind;
  if (drawn) return drawn;
  const key = decodeURIComponent(location.pathname.slice("/p/".length));
  return api<{ kind: string }>(`pages/${encodeURIComponent(key)}`).then(
    (p) => p.kind,
    () => "",
  );
}

/** Up (main.ts goes Back while an entry of the app's is behind this one; go() marks them): the entry was opened
 * from a link or a share, so up to a parent: a todo's is Todos, Tags' is Search, any other
 * page's is Capture. */
export async function up(go: (path: string, replace: boolean) => void) {
  const from = location.pathname;
  const to = from === "/tags" ? "/search" : (await kindShown()) === "todo" ? "/todos" : "/";
  if (location.pathname === from) go(to, true); // unless gone elsewhere meanwhile
}

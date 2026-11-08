// Logging in again, once the login in front of scrap (an oauth2-proxy, Cloudflare Access) has
// expired (api.ts LoginExpired). The service worker answers every page load from its cached
// shell, which never reaches the login, so a load meant to log in is marked (?login=1) and the
// worker leaves it, and the login's own pages, to the network. Shared by the page and sw.ts.
const MARK = "login";

/** This address, marked as a load to log in again. */
export function marked(href: string): string {
  const u = new URL(href);
  u.searchParams.set(MARK, "1");
  return u.href;
}

/** Whether a page load at this address goes to the network, not the cached shell: the login's
 * own pages (oauth2-proxy's /oauth2/, Cloudflare Access's /cdn-cgi/, their callbacks
 * included), or a load marked to log in again. */
export const toNetwork = (url: URL) =>
  /^\/(oauth2|cdn-cgi)\//.test(url.pathname) || url.searchParams.has(MARK);

/** Take the mark off a page's query (once loaded it has done its job); whether it had one. */
export function unmark(query: URLSearchParams): boolean {
  const had = query.has(MARK);
  query.delete(MARK);
  return had;
}

// The public pages' calls to scrap (#497), as docs/reference/public-site.md "The PWA's API in
// scrap" has them; the types are in api.ts. Kept apart from api.ts, which is in the app shell:
// only the page view, Settings and publicpages.ts use these.
import { ApiError, api, type Page, type PublicPage, type Published } from "./api";

const JSON_TYPE = { "Content-Type": "application/json" };

/** The public pages not in the trash; with linksTo, only those whose published copy refers to
 * that page (a link, Linked from or Related). */
export const publicPages = (linksTo?: string) =>
  api<PublicPage[]>(linksTo ? `public?links_to=${encodeURIComponent(linksTo)}` : "public");

/** Make a page public (only sets the flag: it is published when the PWA renders it) or
 * private (scrap takes it off the site at once). */
export const setPublic = (key: string, on: boolean) =>
  api<Page>(`pages/${encodeURIComponent(key)}`, {
    method: "PATCH",
    headers: JSON_TYPE,
    body: JSON.stringify({ public: on }),
  });

/** Publish the page's HTML, rendered from revision base_rev. defer: push the page alone, not
 * the home page, tag pages or search (Refresh all, then rebuild() once). confirmed: the owner
 * has just said yes to it going public (Make public's warning, Refresh all's question), which
 * scrap needs for a page not published before (else 409 unconfirmed). */
export const publishPage = (
  key: string,
  html: string,
  base_rev: number,
  defer = false,
  confirmed = false,
) =>
  api<Published>(`pages/${encodeURIComponent(key)}/published`, {
    method: "PUT",
    headers: JSON_TYPE,
    body: JSON.stringify({ html, base_rev, defer, ...(confirmed && { confirmed }) }),
  });

/** Whether publishing is on on the server (/healthz's publish block; offline: assumed on). */
export const publishOn = () =>
  fetch("/healthz").then(
    (r) => r.json().then((j) => j?.publish?.enabled !== false),
    () => true,
  );

/** Build the home page, the tag pages and search once, after deferred publishes. */
export const rebuild = () => api<{ units: string[] }>("public/rebuild", { method: "POST" });

/** A page's address on the public site, as scrap gives it (null: no SCRAP_PUBLISH_SITE). */
export const publicUrl = (p: Pick<Page, "public_url">) => p.public_url || null;

/** The public site's name, for a toast or the warning: its host, else "the public site". */
export const siteName = (p: Pick<Page, "site">) =>
  p.site?.replace(/^https?:\/\//, "") || "the public site";

/** The error's code from scrap ("stale", "not_public", "stale_tags", ...), if it has one. */
export const codeOf = (err: unknown) => (err instanceof ApiError ? err.body.error : undefined);

/** A publish refused because the page changed after it was drawn: draw it again, once. */
export const redraw = (err: unknown) =>
  err instanceof ApiError &&
  ((err.status === 409 && codeOf(err) === "stale") ||
    (err.status === 422 && codeOf(err) === "stale_tags"));

/** Not sent at all: offline, or the server not reached. */
export const unreached = (err: unknown) => !(err instanceof ApiError);

/** Why a publish failed, in words for a toast. */
export function whyNot(err: unknown, online = navigator.onLine): string {
  if (!(err instanceof ApiError)) return online ? "can't reach the server" : "you're offline";
  const code = codeOf(err);
  if (err.status === 503) return "publishing is off on this server";
  if (err.status === 502) return `the public site refused it (${err.message})`;
  if (err.status === 409 && code === "not_public") return "the page isn't public any more";
  if (err.status === 409 && code === "unconfirmed")
    return "it has never been published: Refresh public pages in Settings asks first";
  if (redraw(err)) return "the page changed meanwhile; try again";
  if (err.status === 413) return "the page is too big to publish";
  return err.message; // a 422 from scrap's check: its detail says which rule
}

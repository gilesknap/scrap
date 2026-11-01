// Public pages (#497), what the PWA does: Share's Make public… (after its warning) and Make
// private (at once, with Undo), a public page published again when it is saved here, the
// public pages that link to one drawn and published again when it is made public or private
// (links coming alive), and Settings' Refresh all. Each page is published from its own view,
// on the screen or drawn off it (page.ts, quiet), by publish.ts, with its drawings and its PDFs'
// text read for its reading folds (#521) fetched. A chunk of its own, loaded
// on the first use. docs/reference/public-site.md has the routes and the rules.
//
// A page never published (made public over MCP, by a revert or an undelete) goes out only
// once the owner has said yes here: Make public's warning, or Refresh all's question. A save,
// a tick or a link coming alive passes it by; scrap refuses it too (409 unconfirmed).
import type { Page, PublicPage } from "./api";
import { ApiError, api } from "./api";
import type { Drawing } from "./board/frame";
import { copyText } from "./clipboard";
import { loadBoard } from "./drawing";
import { KATEX } from "./katexopts";
import { page, pages, type View } from "./page";
import { publishing } from "./pagehead";
import { swapsOf } from "./pagehtml";
import {
  codeOf,
  publicPages,
  publishOn,
  publishPage,
  rebuild,
  redraw,
  setPublic,
  siteName,
  unreached,
  whyNot,
} from "./publicapi";
import { ask, firstTime, warning } from "./publicask";
import { bareSlugs, drawingsOf, fileTextsOf, hasMaths, publishHtml } from "./publish";
import { origins } from "./render";
import { toast } from "./ui";

export const OFFLINE =
  "Saved. Not published while offline: Refresh all public pages in Settings later.";
const LONG = 8000; // a toast with an action, or an error, stays this long

/** What one run of publishes knows: the public pages, when each was published (null: never),
 * and the titles of pages bare links name. */
interface Run {
  live: Set<string>;
  published: Map<string, string | null>;
  titles: Map<string, string>;
}
const runOf = (list: PublicPage[]): Run => ({
  live: new Set(list.map((q) => q.slug)),
  published: new Map(list.map((q) => [q.slug, q.published_at])),
  titles: new Map(list.map((q) => [q.slug, q.title])),
});
const run = async () => runOf(await publicPages());

/** A view drawn with a page: the article and the page it shows. */
interface Drawn {
  root: HTMLElement;
  page: Page;
}

/** The page's view drawn off the screen (and let go once published). */
async function offscreen(slug: string, signal: AbortSignal): Promise<Drawn> {
  const root = (await page(slug, signal, true)) as HTMLElement;
  const p = pages.get(root);
  if (!p) throw new Error("the page could not be drawn");
  return { root, page: p };
}

let katex: ((tex: string, display: boolean) => string) | null = null;
async function tex() {
  if (!katex) {
    const k = (await import("katex")).default;
    katex = (t, display) => k.renderToString(t, { ...KATEX, displayMode: display });
  }
  return katex;
}

/** A photo's 2048 px preview as a data: URL, as the drawing of it embeds it (scrap matches
 * these bytes to the page's photo). */
async function photoUrl(sha: string): Promise<string> {
  let got = await fetch(`/api/blobs/${sha}/preview?size=2048`);
  for (let tries = 0; got.status === 503 && tries < 3; tries++) {
    // its preview is being made (scrap's decoder is busy): as scrap asks, a little later
    await new Promise((ok) => setTimeout(ok, 1000 * Number(got.headers.get("Retry-After") || 2)));
    got = await fetch(`/api/blobs/${sha}/preview?size=2048`);
  }
  if (!got.ok)
    throw new ApiError(got.status === 503 ? 422 : got.status, {
      error: "drawing",
      detail: `the photo of a drawing could not be fetched (HTTP ${got.status})`,
    });
  const bytes = new Uint8Array(await got.arrayBuffer());
  let text = "";
  for (let i = 0; i < bytes.length; i += 0x8000)
    text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return `data:${got.headers.get("Content-Type") || "image/jpeg"};base64,${btoa(text)}`;
}

/** The view's drawings drawn as public pages show them (#520), by id: Excalidraw's chunk is
 * loaded only for a page that has one. */
export async function drawingsFor(root: HTMLElement): Promise<{ key: string; svg: string }[]> {
  const found = drawingsOf(root);
  if (!found.length) return [];
  const board = await loadBoard().catch(() => {
    throw new TypeError("Excalidraw could not be loaded"); // as offline: not reached
  });
  const out: { key: string; svg: string }[] = [];
  for (const d of found) {
    const path = `captures/${encodeURIComponent(d.cid)}/photos/${d.sha}/drawing`;
    const drawing = await api<Drawing>(path); // an ApiError, or not reached, as it is
    const photo = await photoUrl(d.sha); // offline: not reached, as it is
    try {
      out.push({ key: d.id, svg: await board.publishSvg(drawing.data, photo) });
    } catch (err) {
      // said as scrap's own refusals are (publicapi.ts whyNot), not as "offline"
      const why = err instanceof Error ? err.message : String(err);
      throw new ApiError(422, { error: "drawing", detail: `a drawing could not be drawn: ${why}` });
    }
  }
  return out;
}

/** The text of each PDF whose reading fold the view shows (#521), by sha, as the fold shows
 * it when opened (filecard.ts): fetched, as the view has only "…" until then. */
export async function fileTextsFor(root: HTMLElement): Promise<Map<string, string>> {
  const out = new Map<string, string>();
  for (const f of fileTextsOf(root)) {
    const path = `captures/${encodeURIComponent(f.cid)}/files/${f.sha}/text`;
    const r = await api<{ text: string | null; truncated: boolean }>(path); // as a drawing's
    if (r.text) out.set(f.sha, r.text + (r.truncated ? "\n\n… (the start only)" : ""));
  }
  return out;
}

/** What a page is published as: its HTML and its drawings' SVGs. */
export interface Rendered {
  html: string;
  drawings: { key: string; svg: string }[];
}

/** The page's public HTML from its view, with its drawings: the public pages known, the
 * titles of private pages its bare links name fetched. */
export async function renderedOf(d: Drawn, r: Run): Promise<Rendered> {
  const drawn = await drawingsFor(d.root);
  const html = await htmlOf(d, r, new Set(drawn.map((x) => x.key)));
  // only those the page shows (a drawing without its photo's figure is not)
  const drawings = drawn.filter((x) => html.includes(`"scrap-drawing:${x.key}"`));
  return { html, drawings };
}

/** The page's public HTML from its view: the public pages known, the titles of private pages
 * its bare links name fetched; drawn, the drawings drawn (shown with their photos). */
export async function htmlOf(
  d: Drawn,
  r: Run,
  drawn: ReadonlySet<string> = new Set(),
): Promise<string> {
  const swaps = await swapsOf(d.root);
  // A public page that links to itself is public: this one is
  r.live.add(d.page.slug);
  r.titles.set(d.page.slug, d.page.title);
  // the titles the page came with (#508: its links' pages, private ones too)
  for (const [slug, title] of Object.entries(d.page.titles ?? {}))
    if (!r.titles.has(slug)) r.titles.set(slug, title);
  const texts = await fileTextsFor(d.root);
  const named = bareSlugs(d.root, swaps).filter((s) => !r.titles.has(s));
  await Promise.all(
    named.map((s) =>
      api<Page>(`pages/${encodeURIComponent(s)}`).then(
        (q) => r.titles.set(s, q.title),
        () => {}, // gone: "a private page"
      ),
    ),
  );
  // As the site's own pages write dates ("1 Nov 2026"), whatever the device's language
  const date = new Date().toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  return publishHtml(
    d.root,
    {
      title: d.page.title,
      tags: d.page.tags,
      live: r.live,
      titles: Object.fromEntries(r.titles),
      origins: origins(),
      site: d.page.site ?? null,
      tex: hasMaths(d.root) ? await tex() : null,
      date,
      drawn,
      texts,
    },
    swaps,
  );
}

/** Draw and publish a page; drawn again once if it changed since (a 409 stale, a 422
 * stale_tags). Null, publishing nothing, for a page never published unless confirmed (the
 * owner has just said yes to it). */
async function publishOne(
  draw: (again: boolean) => Promise<Drawn>,
  r: Run,
  defer: boolean,
  confirmed = false,
) {
  for (let again = false; ; again = true) {
    const d = await draw(again);
    if (!confirmed && !d.page.published_at) return null;
    const { html, drawings } = await renderedOf(d, r);
    try {
      const done = await publishPage(d.page.id, html, d.page.rev, defer, confirmed, drawings);
      return { page: d.page, done };
    } catch (err) {
      if (codeOf(err) === "unconfirmed") return null; // unpublished meanwhile
      if (again || !redraw(err)) throw err;
    }
  }
}

/** Draws for the page on the screen: as it is shown, then (again) as it is now. */
const onScreen =
  (view: View) =>
  async (again: boolean): Promise<Drawn> => {
    if (again) view.show(await api<Page>(`pages/${encodeURIComponent(view.shown().id)}`));
    return { root: view.root, page: view.shown() };
  };

/** Draws for a page off the screen. */
const offScreen = (slug: string, signal: AbortSignal) => () => offscreen(slug, signal);

/** Publish the page on the screen, its dates line saying Publishing… meanwhile, and show
 * when; the answer, or the error. */
async function publishShown(view: View, r: Run, defer: boolean, confirmed = false) {
  const id = view.shown().id;
  publishing.add(id);
  view.show(view.shown());
  try {
    const got = await publishOne(onScreen(view), r, defer, confirmed);
    if (!got) return null;
    const { page, done } = got;
    publishing.delete(id);
    view.show({
      ...page,
      published_at: done.published_at,
      public_url: done.url ?? page.public_url,
    });
    return done;
  } finally {
    if (publishing.delete(id)) view.show(view.shown());
  }
}

/** The published pages to publish again now that this one is public or private (or gone):
 * those whose published copy refers to it (scrap's list), and those that link to it as its
 * card says (Linked from), which are public. Never one not published yet: that waits for
 * the owner's yes. */
async function linking(p: Pick<Page, "slug" | "related">, r: Run): Promise<PublicPage[]> {
  const listed = await publicPages(p.slug).catch(() => [] as PublicPage[]);
  const known = new Set(listed.map((q) => q.slug));
  const backlinks = (p.related ?? [])
    .filter((q) => q.via === "link" && r.live.has(q.slug) && !known.has(q.slug))
    .map((q) => ({
      id: q.id,
      slug: q.slug,
      title: q.title,
      published_at: r.published.get(q.slug) ?? null,
    }));
  return [...listed, ...backlinks].filter((q) => q.slug !== p.slug && q.published_at);
}

/** Publish each of these pages again, drawn off the screen, deferred: how many were (one
 * never published is passed by unless fresh: the owner has just said yes to those). */
export async function again(list: PublicPage[], r: Run, each?: (i: number) => void, fresh = false) {
  let done = 0;
  const failed: string[] = [];
  for (const [i, q] of list.entries()) {
    each?.(i);
    if (!q.published_at && !fresh) continue;
    const ac = new AbortController();
    try {
      // confirmed only for a page never published: one published before needs no yes
      const first = fresh && !q.published_at;
      if (await publishOne(offScreen(q.slug, ac.signal), r, true, first)) done++;
    } catch (err) {
      if (codeOf(err) !== "not_public") failed.push(`${q.title} (${whyNot(err)})`);
    } finally {
      ac.abort(); // the view drawn off the screen: nothing left running
    }
  }
  return { done, failed };
}

const pagesWord = (n: number) => (n === 1 ? "1 page" : `${n} pages`);
const linkingSaid = (n: number) => (n ? ` · ${pagesWord(n)} linking here updated` : "");

/** Make public: the warning (not again for Undo), the flag on, the page published, then
 * the public pages linking to it; then the toast, with Copy link. */
export async function makePublic(view: View, warned = false) {
  const p = view.shown();
  if (!warned && !(await ask(warning(p, siteName(p))))) return;
  let on: Page;
  try {
    on = await setPublic(p.id, true);
  } catch (err) {
    return toast(`Not made public: ${whyNot(err)}`, "", undefined, LONG);
  }
  view.show(on);
  let url: string | null;
  let n = 0;
  try {
    const r = await run();
    const others = await linking(on, r);
    // (confirmed: the warning was just answered, or this is Undo, the owner's own tap)
    url = (await publishShown(view, r, others.length > 0, true))?.url ?? null;
    if (others.length) {
      n = (await again(others, r)).done;
      await rebuild().catch(() => {}); // scrap's reconcile builds them anyway
    }
  } catch (err) {
    // Publishing is off on this server: the page is put back as it was
    if (codeOf(err) === "not_configured") {
      view.show(await setPublic(p.id, false).catch(() => view.shown()));
      return toast("Not made public: publishing is off on this server", "", undefined, LONG);
    }
    return toast(
      `Public, but not published: ${whyNot(err)}. Refresh public pages in Settings later.`,
      "",
      undefined,
      LONG,
    );
  }
  if (warned) return; // Undo: as it was, nothing more to say
  const said = `Page is public${linkingSaid(n)}`;
  if (!url) return toast(said, "", undefined, LONG); // no SCRAP_PUBLISH_SITE: no address to copy
  const link = url;
  toast(said, "Copy link", () => void copyText(link, "Link"), LONG);
}

/** Make private: at once, no question (scrap takes it off the site); the public pages that
 * linked to it published again, its link now its words; Undo publishes it again. */
export async function makePrivate(view: View) {
  const p = view.shown();
  let off: Page;
  try {
    off = await setPublic(p.id, false);
  } catch (err) {
    return toast(`Not made private: ${whyNot(err)}`, "", undefined, LONG);
  }
  view.show(off);
  const n = await relink(off);
  // The site could not be told yet: scrap's reconcile takes it off shortly
  const said =
    off.unpublish === "pending"
      ? `Private: comes off ${siteName(off)} shortly`
      : `Private: taken off ${siteName(off)}`;
  toast(`${said}${linkingSaid(n)}`, "Undo", () => void makePublic(view, true), LONG);
}

/** The published pages linking to this page (made private, or deleted) drawn and published
 * again, its link now its words: how many were. */
async function relink(p: Pick<Page, "slug" | "related">): Promise<number> {
  try {
    const r = await run();
    const others = await linking(p, r);
    if (!others.length) return 0;
    const n = (await again(others, r)).done;
    if (n) await rebuild().catch(() => {}); // scrap's reconcile builds them anyway
    return n;
  } catch {
    return 0; // the others wait for Refresh all
  }
}

/** A page deleted here (to the trash): the published pages that showed its title, as a link
 * or as words, published again without it. */
export const deleted = async (p: Pick<Page, "slug" | "related">) =>
  (await publishOn()) ? relink(p) : 0;

/** A public page saved here: published again. Offline, or the server not reached, it is
 * saved but not published, and the toast says so (publishes are never queued). One never
 * published waits for the owner's yes (Refresh all asks). */
export async function republish(view: View) {
  if (!view.shown().published_at) return;
  if (!navigator.onLine) return toast(OFFLINE, "", undefined, LONG);
  try {
    await publishShown(view, await run(), false);
  } catch (err) {
    if (unreached(err)) return toast(OFFLINE, "", undefined, LONG);
    if (codeOf(err) === "not_public") return; // made private meanwhile: nothing to publish
    toast(`Saved. Not published: ${whyNot(err)}`, "", undefined, LONG);
  }
}

/** A public page changed but no longer on the screen (ticked done, on to the next): published
 * again, drawn off the screen. */
export async function republishOff(slug: string) {
  if (!navigator.onLine) return toast(OFFLINE, "", undefined, LONG);
  const ac = new AbortController();
  try {
    await publishOne(offScreen(slug, ac.signal), await run(), false);
  } catch (err) {
    if (unreached(err)) return toast(OFFLINE, "", undefined, LONG);
    if (codeOf(err) !== "not_public")
      toast(`Saved. Not published: ${whyNot(err)}`, "", undefined, LONG);
  } finally {
    ac.abort();
  }
}

/** Refresh all: every public page drawn and published again (deferred), then the home page,
 * tag pages and search built once. Asks once first when some were never published. Null if
 * that was cancelled; else how many were refreshed, and those that failed. */
export async function refreshAll(progress: (i: number, n: number) => void) {
  const list = await publicPages();
  const fresh = list.filter((q) => !q.published_at);
  if (fresh.length && !(await ask(firstTime(fresh)))) return null;
  // (fresh: the owner has just said yes to those never published)
  const out = await again(list, runOf(list), (i) => progress(i + 1, list.length), true);
  if (out.done) await rebuild();
  return { ...out, of: list.length };
}

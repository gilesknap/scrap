// Public pages (#497), what the PWA does: Share's Make public… (after its warning) and Make
// private (at once, with Undo), a public page published again when it is saved here, the
// public pages that link to one drawn and published again when it is made public or private
// (links coming alive), and Settings' Refresh all. Each page is published from its own view,
// on the screen or drawn off it (page.ts, quiet), by publish.ts. A chunk of its own, loaded
// on the first use. docs/reference/public-site.md has the routes and the rules.
import type { Page, PublicPage } from "./api";
import { api } from "./api";
import { copyText } from "./clipboard";
import { KATEX } from "./katexopts";
import { page, pages, type View } from "./page";
import { publishing } from "./pagehead";
import { swapsOf } from "./pagehtml";
import {
  codeOf,
  publicPages,
  publishPage,
  rebuild,
  redraw,
  setPublic,
  siteName,
  unreached,
  whyNot,
} from "./publicapi";
import { ask, firstTime, warning } from "./publicask";
import { bareSlugs, hasMaths, publishHtml } from "./publish";
import { origins } from "./render";
import { toast } from "./ui";

export const OFFLINE =
  "Saved. Not published while offline: Refresh all public pages in Settings later.";
const LONG = 8000; // a toast with an action, or an error, stays this long

/** What one run of publishes knows: the public pages, and the titles of pages bare links name. */
interface Run {
  live: Set<string>;
  titles: Map<string, string>;
}
async function run(): Promise<Run> {
  const list = await publicPages();
  return {
    live: new Set(list.map((q) => q.slug)),
    titles: new Map(list.map((q) => [q.slug, q.title])),
  };
}

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

/** The page's public HTML from its view: the public pages known, the titles of private pages
 * its bare links name fetched. */
export async function htmlOf(d: Drawn, r: Run): Promise<string> {
  const swaps = await swapsOf(d.root);
  // A public page that links to itself is public: this one is
  r.live.add(d.page.slug);
  r.titles.set(d.page.slug, d.page.title);
  const named = bareSlugs(d.root, swaps).filter((s) => !r.titles.has(s));
  await Promise.all(
    named.map((s) =>
      api<Page>(`pages/${encodeURIComponent(s)}`).then(
        (q) => r.titles.set(s, q.title),
        () => {}, // gone: "a private page"
      ),
    ),
  );
  const date = new Date().toLocaleDateString(undefined, {
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
      titles: r.titles,
      origins: origins(),
      site: d.page.site ?? null,
      tex: hasMaths(d.root) ? await tex() : null,
      date,
    },
    swaps,
  );
}

/** Draw and publish a page; drawn again once if it changed since (a 409 stale, a 422
 * stale_tags). */
async function publishOne(draw: (again: boolean) => Promise<Drawn>, r: Run, defer: boolean) {
  for (let again = false; ; again = true) {
    const d = await draw(again);
    const html = await htmlOf(d, r);
    try {
      return { page: d.page, done: await publishPage(d.page.id, html, d.page.rev, defer) };
    } catch (err) {
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
async function publishShown(view: View, r: Run, defer: boolean) {
  const id = view.shown().id;
  publishing.add(id);
  view.show(view.shown());
  try {
    const { page, done } = await publishOne(onScreen(view), r, defer);
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

/** The public pages to publish again now that this one is public or private: those whose
 * published copy refers to it (scrap's list), and those that link to it as its card says
 * (Linked from), which are public. */
async function linking(p: Page, live: ReadonlySet<string>): Promise<PublicPage[]> {
  const listed = await publicPages(p.slug).catch(() => [] as PublicPage[]);
  const known = new Set(listed.map((q) => q.slug));
  const backlinks = (p.related ?? [])
    .filter((q) => q.via === "link" && live.has(q.slug) && !known.has(q.slug))
    .map((q) => ({ id: q.id, slug: q.slug, title: q.title, published_at: null }));
  return [...listed, ...backlinks].filter((q) => q.slug !== p.slug);
}

/** Publish each of these pages again, drawn off the screen, deferred: how many were. */
async function again(list: PublicPage[], r: Run, each?: (i: number) => void) {
  let done = 0;
  const failed: string[] = [];
  for (const [i, q] of list.entries()) {
    each?.(i);
    const ac = new AbortController();
    try {
      await publishOne(offScreen(q.slug, ac.signal), r, true);
      done++;
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
    const others = await linking(on, r.live);
    url = (await publishShown(view, r, others.length > 0)).url;
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
  let n = 0;
  try {
    const r = await run();
    const others = await linking(off, r.live);
    if (others.length) {
      n = (await again(others, r)).done;
      await rebuild().catch(() => {});
    }
  } catch {} // the page is private all the same: the others wait for Refresh all
  toast(
    `Private: taken off ${siteName(off)}${linkingSaid(n)}`,
    "Undo",
    () => void makePublic(view, true),
    LONG,
  );
}

/** A public page saved here: published again. Offline, or the server not reached, it is
 * saved but not published, and the toast says so (publishes are never queued). */
export async function republish(view: View) {
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
  const r: Run = {
    live: new Set(list.map((q) => q.slug)),
    titles: new Map(list.map((q) => [q.slug, q.title])),
  };
  const out = await again(list, r, (i) => progress(i + 1, list.length));
  if (out.done) await rebuild();
  return { ...out, of: list.length };
}

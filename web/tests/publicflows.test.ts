// What publicpages.ts does (#497), on a fake scrap: Make public (and its rollback when
// publishing is off), Make private (pending, Undo), a save published again (offline, never
// published), links coming alive and Refresh all, each passing by a page never published
// unless the owner has just said yes to it (S1).
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Page } from "../src/api";

const toasts: { message: string; action?: string; act?: () => void }[] = [];
let answer = true; // what the owner says to a question
const asked: string[] = [];

vi.mock("../src/ui", () => ({
  toast: (message: string, action?: string, act?: () => void) =>
    toasts.push({ message, action, act }),
  h: () => ({}),
}));
vi.mock("../src/publicask", () => ({
  ask: async (q: { title: string }) => {
    asked.push(q.title);
    return answer;
  },
  warning: () => ({ title: "Make this page public?" }),
  firstTime: () => ({ title: "Publish for the first time?" }),
}));
vi.mock("../src/clipboard", () => ({ copyText: vi.fn() }));
vi.mock("../src/pagehead", () => ({ publishing: new Set() }));
vi.mock("../src/pagehtml", () => ({ swapsOf: async () => new Map() }));
vi.mock("../src/render", () => ({ origins: () => [] }));
vi.mock("../src/publish", () => ({
  bareSlugs: () => [],
  codeText: (s: string) => s.replace("scrap.example", "a private link"),
  hasMaths: () => false,
  // a view's drawings: those its (fake) root lists
  drawingsOf: (root: { drawings?: unknown[] }) => root.drawings ?? [],
  // its diagrams (#525): those its root lists
  diagramsOf: (root: { diagrams?: unknown[] }) => root.diagrams ?? [],
  publishHtml: (
    _root: unknown,
    c: { title: string; drawn?: Set<string>; diagrams?: Map<string, { key: number }> },
  ) =>
    `<!DOCTYPE html>${c.title}${[...(c.drawn ?? [])].map((d) => ` "scrap-drawing:${d}"`).join("")}${[
      ...(c.diagrams?.values() ?? []),
    ]
      .map((k) => ` "scrap-diagram:${k.key}-light"`)
      .join("")}`,
}));
// Mermaid's chunk, loaded only for a page with diagrams (#525): a source "bad" is not drawn
const mermaids: string[] = [];
vi.mock("../src/mermaid", () => ({
  svgFor: async (text: string, theme: string) => {
    mermaids.push(theme);
    if (text === "bad") throw new Error("no diagram");
    return `<svg class="${theme}">${text}</svg>`;
  },
  wordsOf: (svg: string) => svg.replace(/<[^>]*>/g, ""),
}));
// Excalidraw's chunk, loaded only for a page with drawings (#520)
const boards: string[] = [];
vi.mock("../src/drawing", () => ({
  loadBoard: async () => {
    boards.push("loaded");
    return {
      publishSvg: async (...args: [{ elements: unknown[] }, ...unknown[]]) =>
        `<svg data-n="${args[0].elements.length}" data-args="${args.length}"></svg>`,
    };
  },
}));
// A page drawn off the screen: its root, and the page it shows
const roots = new WeakMap<object, Page>();
vi.mock("../src/page", () => ({
  pages: roots,
  page: async (slug: string) => {
    const root = {};
    roots.set(root, { ...pageOf(slug) });
    return root;
  },
}));

const pub = await import("../src/publicpages");

// ---- the fake scrap
interface Stored {
  page: Page;
  public: boolean;
  published_at: string | null;
}
const store = new Map<string, Stored>();
const linksTo = new Map<string, string[]>(); // slug -> the slugs of pages whose copy refers to it
let calls: { method: string; url: string; body?: Record<string, unknown> }[] = [];
let failPut: Record<string, [number, string]> = {}; // slug -> status, error
let pending = false; // a PATCH to private answers unpublish: pending
let unreachable = false;
let configured = true;

const pageOf = (slug: string): Page => {
  const s = store.get(slug);
  if (!s) throw new Error(`no ${slug}`);
  return {
    ...s.page,
    public: s.public,
    published_at: s.published_at,
    site: "https://pages.example",
  };
};
const add = (slug: string, o: Partial<Stored> = {}) =>
  store.set(slug, {
    page: {
      id: slug,
      slug,
      title: slug.toUpperCase(),
      rev: 1,
      tags: [],
      related: [],
    } as unknown as Page,
    public: false,
    published_at: null,
    ...o,
  });

const reply = (status: number, data: unknown) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => {
  boards.length = 0;
  mermaids.length = 0;
  toasts.length = 0;
  asked.length = 0;
  answer = true;
  store.clear();
  linksTo.clear();
  calls = [];
  failPut = {};
  pending = false;
  unreachable = false;
  configured = true;
  vi.stubGlobal("navigator", { onLine: true });
  vi.stubGlobal("dispatchEvent", () => true);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (unreachable) throw new TypeError("Failed to fetch");
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url, body });
      if (url === "/healthz") return reply(200, { publish: { enabled: configured } });
      const u = new URL(url, "http://x");
      if (/^\/api\/captures\/c1\/photos\/[0-9a-f]+\/drawing$/.test(u.pathname))
        return reply(200, { data: { format: "scene", elements: [{}, {}] } });
      if (u.pathname === "/api/public") {
        const to = u.searchParams.get("links_to");
        const list = [...store.values()]
          .filter((s) => s.public && (!to || (linksTo.get(to) ?? []).includes(s.page.slug)))
          .map((s) => ({
            id: s.page.id,
            slug: s.page.slug,
            title: s.page.title,
            published_at: s.published_at,
          }));
        return reply(200, list);
      }
      if (u.pathname === "/api/public/rebuild") return reply(200, { units: ["home"] });
      const m = /^\/api\/pages\/([^/]+)(\/published)?$/.exec(u.pathname);
      const s = m && store.get(decodeURIComponent(m[1]));
      if (!m || !s) return reply(404, { detail: "no" });
      if (m[2]) {
        if (!configured) return reply(503, { error: "not_configured", detail: "off" });
        const fail = failPut[s.page.slug];
        if (fail) return reply(fail[0], { error: fail[1], detail: fail[1] });
        if (!s.public) return reply(409, { error: "not_public", detail: "no" });
        if (!s.published_at && !body?.confirmed)
          return reply(409, { error: "unconfirmed", detail: "no" });
        s.published_at = "2026-11-01T12:00:00Z";
        return reply(200, {
          url: `https://pages.example/p/${s.page.slug}`,
          published_at: s.published_at,
          files: 0,
        });
      }
      if (method === "PATCH") {
        s.public = body.public;
        if (!s.public) s.published_at = null;
        return reply(200, {
          ...pageOf(s.page.slug),
          ...(!s.public && pending && { unpublish: "pending" }),
        });
      }
      return reply(200, pageOf(s.page.slug));
    }),
  );
});

/** The page on the screen: a view of it. */
function view(slug: string) {
  let shown = pageOf(slug);
  const show = (p: Page) => {
    shown = p;
  };
  return { root: {} as HTMLElement, shown: () => shown, show };
}
const puts = () =>
  calls
    .filter((c) => c.method === "PUT")
    .map((c) => ({
      slug: c.url.split("/")[3],
      defer: c.body?.defer,
      confirmed: !!c.body?.confirmed,
    }));

describe("a page with drawings (#520)", () => {
  it("draws each without its photo (#524), and sends them with the page; Excalidraw only then", async () => {
    add("a");
    const v = view("a");
    (v.root as unknown as { drawings: unknown[] }).drawings = [{ id: "7", cid: "c1", sha: "ab" }];
    await pub.makePublic(v);
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.body?.html).toBe('<!DOCTYPE html>A "scrap-drawing:7"');
    expect(put?.body?.drawings).toEqual([
      { key: "7", svg: '<svg data-n="2" data-args="1"></svg>' },
    ]);
    // the drawing replaces the photo, as in the app: its preview is not fetched for it
    expect(calls.some((c) => c.url.includes("/api/blobs/"))).toBe(false);
    expect(boards).toEqual(["loaded"]);
  });

  it("loads no Excalidraw and sends no drawings for a page without any", async () => {
    add("a");
    await pub.makePublic(view("a"));
    expect(calls.find((c) => c.method === "PUT")?.body?.drawings).toBeUndefined();
    expect(boards).toEqual([]);
  });
});

describe("a page with diagrams (#525)", () => {
  it("draws each light and dark and sends them; one it can't draw stays its source", async () => {
    add("a");
    const v = view("a");
    (v.root as unknown as { diagrams: unknown[] }).diagrams = ["one", "bad", "three scrap.example"];
    await pub.makePublic(v);
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.body?.html).toBe(
      '<!DOCTYPE html>A "scrap-diagram:1-light" "scrap-diagram:3-light"',
    );
    expect(put?.body?.diagrams).toEqual([
      { key: "1", light: '<svg class="light">one</svg>', dark: '<svg class="dark">one</svg>' },
      {
        key: "3",
        light: '<svg class="light">three a private link</svg>',
        dark: '<svg class="dark">three a private link</svg>',
      },
    ]);
  });

  it("sends no more than scrap's 20 files take, two each; the rest go out as their source", async () => {
    add("a");
    const v = view("a");
    const sources = Array.from({ length: 12 }, (_, i) => `d${i + 1}`);
    (v.root as unknown as { diagrams: unknown[] }).diagrams = sources;
    await pub.makePublic(v);
    const put = calls.find((c) => c.method === "PUT");
    const sent = ((put?.body?.diagrams ?? []) as { key: string }[]).map((d) => d.key);
    expect(sent).toEqual(sources.slice(0, 10).map((_, i) => String(i + 1)));
    expect(put?.body?.html).not.toContain("scrap-diagram:11-light");
    expect(put?.body?.html).toContain("scrap-diagram:10-light");
  });

  it("loads no Mermaid and sends no diagrams for a page without any", async () => {
    add("a");
    await pub.makePublic(view("a"));
    expect(calls.find((c) => c.method === "PUT")?.body?.diagrams).toBeUndefined();
    expect(mermaids).toEqual([]);
  });
});

describe("Make public", () => {
  it("asks, sets the flag, publishes confirmed, and says so with Copy link", async () => {
    add("a");
    const v = view("a");
    await pub.makePublic(v);
    expect(asked).toEqual(["Make this page public?"]);
    expect(puts()).toEqual([{ slug: "a", defer: false, confirmed: true }]);
    expect(v.shown().published_at).toBeTruthy();
    expect(toasts.at(-1)).toMatchObject({ message: "Page is public", action: "Copy link" });
  });

  it("does nothing when the warning is cancelled", async () => {
    add("a");
    answer = false;
    await pub.makePublic(view("a"));
    expect(calls).toEqual([]);
  });

  it("publishes the published pages linking to it, deferred, never one not published yet", async () => {
    add("a");
    add("b", { public: true, published_at: "t" });
    add("c", { public: true }); // public over MCP, never published
    linksTo.set("a", ["b", "c"]);
    await pub.makePublic(view("a"));
    expect(puts()).toEqual([
      { slug: "a", defer: true, confirmed: true },
      { slug: "b", defer: true, confirmed: false },
    ]);
    expect(calls.filter((c) => c.url.endsWith("/rebuild"))).toHaveLength(1);
    expect(store.get("c")?.published_at).toBeNull();
    expect(toasts.at(-1)?.message).toBe("Page is public · 1 page linking here updated");
  });

  it("puts the flag back when publishing is off on the server", async () => {
    add("a");
    configured = false;
    const v = view("a");
    await pub.makePublic(v);
    expect(calls.filter((c) => c.method === "PATCH").map((c) => c.body?.public)).toEqual([
      true,
      false,
    ]);
    expect(v.shown().public).toBe(false);
    expect(toasts.at(-1)?.message).toBe("Not made public: publishing is off on this server");
  });

  it("stays public, not published, when the site refuses it", async () => {
    add("a");
    failPut = { a: [502, "publish_failed"] };
    await pub.makePublic(view("a"));
    expect(store.get("a")?.public).toBe(true);
    expect(toasts.at(-1)?.message).toMatch(
      /^Public, but not published: the public site refused it/,
    );
  });
});

describe("Make private", () => {
  it("acts at once, publishes the linking pages again, and Undo publishes it silently", async () => {
    add("a", { public: true, published_at: "t" });
    add("b", { public: true, published_at: "t" });
    linksTo.set("a", ["b"]);
    const v = view("a");
    await pub.makePrivate(v);
    expect(asked).toEqual([]);
    expect(store.get("a")?.public).toBe(false);
    expect(puts()).toEqual([{ slug: "b", defer: true, confirmed: false }]);
    const t = toasts.at(-1);
    expect(t?.message).toBe("Private: taken off pages.example · 1 page linking here updated");
    expect(t?.action).toBe("Undo");
    calls = [];
    toasts.length = 0;
    t?.act?.();
    await vi.waitFor(() => expect(store.get("a")?.published_at).toBeTruthy());
    expect(asked).toEqual([]); // no warning again
    expect(puts()[0]).toEqual({ slug: "a", defer: true, confirmed: true });
    await vi.waitFor(() => expect(calls.some((c) => c.url.endsWith("/rebuild"))).toBe(true));
    expect(toasts).toEqual([]); // silent
  });

  it("says it comes off shortly when the site could not be told yet", async () => {
    add("a", { public: true, published_at: "t" });
    pending = true;
    await pub.makePrivate(view("a"));
    expect(toasts.at(-1)?.message).toBe("Private: comes off pages.example shortly");
  });
});

describe("a save published again", () => {
  it("publishes a published page, not confirmed", async () => {
    add("a", { public: true, published_at: "t" });
    await pub.republish(view("a"));
    expect(puts()).toEqual([{ slug: "a", defer: false, confirmed: false }]);
    expect(toasts).toEqual([]);
  });

  it("passes by a page never published (S1)", async () => {
    add("a", { public: true });
    await pub.republish(view("a"));
    expect(puts()).toEqual([]);
    expect(store.get("a")?.published_at).toBeNull();
  });

  it("says saved but not published when offline, or when scrap can't be reached", async () => {
    add("a", { public: true, published_at: "t" });
    vi.stubGlobal("navigator", { onLine: false });
    await pub.republish(view("a"));
    expect(toasts.at(-1)?.message).toBe(pub.OFFLINE);
    vi.stubGlobal("navigator", { onLine: true });
    unreachable = true;
    await pub.republish(view("a"));
    expect(toasts.at(-1)?.message).toBe(pub.OFFLINE);
  });

  it("passes by a page made private meanwhile, quietly", async () => {
    add("a", { public: true, published_at: "t" });
    const v = view("a");
    (store.get("a") as Stored).public = false;
    await pub.republish(v);
    expect(toasts).toEqual([]);
  });
});

describe("Refresh all", () => {
  it("asks before pages never published, and Cancel publishes nothing", async () => {
    add("a", { public: true, published_at: "t" });
    add("b", { public: true });
    answer = false;
    expect(await pub.refreshAll(() => {})).toBeNull();
    expect(asked).toEqual(["Publish for the first time?"]);
    expect(puts()).toEqual([]);
  });

  it("publishes every page, deferred, then builds once; a failure partway is listed", async () => {
    add("a", { public: true, published_at: "t" });
    add("b", { public: true });
    add("c", { public: true, published_at: "t" });
    failPut = { c: [422, "bad_html"] };
    const seen: string[] = [];
    const out = await pub.refreshAll((i, n) => seen.push(`${i}/${n}`));
    expect(seen).toEqual(["1/3", "2/3", "3/3"]);
    expect(out).toMatchObject({ done: 2, of: 3, failed: ["C (bad_html)"] });
    // confirmed only for b, the one never published (the owner's yes was to it)
    expect(puts().map((p) => [p.slug, p.defer, p.confirmed])).toEqual([
      ["a", true, false],
      ["b", true, true],
      ["c", true, false],
    ]);
    expect(store.get("b")?.published_at).toBeTruthy();
    expect(calls.filter((c) => c.url.endsWith("/rebuild"))).toHaveLength(1);
  });

  it("asks nothing when every page was published before", async () => {
    add("a", { public: true, published_at: "t" });
    await pub.refreshAll(() => {});
    expect(asked).toEqual([]);
  });
});

describe("a page deleted here", () => {
  it("publishes again the published pages that showed it", async () => {
    add("a");
    add("b", { public: true, published_at: "t" });
    linksTo.set("a", ["b"]);
    expect(await pub.deleted({ slug: "a", related: [] })).toBe(1);
    expect(puts()).toEqual([{ slug: "b", defer: true, confirmed: false }]);
  });

  it("does nothing where publishing is off", async () => {
    add("b", { public: true, published_at: "t" });
    linksTo.set("a", ["b"]);
    configured = false;
    expect(await pub.deleted({ slug: "a", related: [] })).toBe(0);
    expect(puts()).toEqual([]);
  });
});

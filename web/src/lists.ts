// The lists of pages (newest first, with anything still waiting to upload above them) that
// the search screen (an empty box) and the capture screen show.
import { api, previewUrl, type Summary } from "./api";
import { queue, view } from "./app";
import { tapBuild } from "./debug";
import { icon, kindIcon } from "./icons";
import { chipOf, dueOf } from "./status";
import { swipeRows, trail } from "./swipe";
import { blobImg, empty, h, problem, settle, whenShort } from "./ui";

function row(
  thumb: string | Blob | null,
  title: string,
  sub: string,
  extra: Node | string = "",
  href?: string,
  kind?: string,
  chip = typeof extra === "string" ? extra : "", // beside sub, when extra is a node
  todo: [string, string] | null = null, // a todo's priority and due date, and its class
) {
  const none = () => h("span", { className: "noimg" }, icon(kindIcon(kind)));
  let img: HTMLElement = none();
  if (thumb instanceof Blob) img = blobImg(thumb);
  else if (thumb) {
    const el = settle(h("img", { src: thumb, alt: "", loading: "lazy", decoding: "async" }));
    el.onerror = () => el.replaceWith(none()); // a file the server can't preview
    img = el;
  }
  const body = h(
    "span",
    {},
    h("strong", { dir: "auto" }, title),
    h(
      "span",
      { className: "sub" },
      h("small", {}, sub),
      chip && h("em", { className: chip }, chip),
      todo && h("small", { className: todo[1] }, todo[0]),
    ),
    typeof extra !== "string" && extra,
  );
  return h("li", {}, href ? h("a", { href }, img, body) : h("div", {}, img, body));
}

/** A page's row, however it was found: its thumbnail (else its kind's icon), title, when last
 * edited (a Later's medium after it: "Book") and its chip; a search's hit also has its
 * snippet. */
export const pageRow = (
  p: Pick<
    Summary,
    "slug" | "title" | "kind" | "fields" | "updated_at" | "thumb" | "due" | "priority" | "tasks"
  >,
  snippet?: Node,
) => {
  const li = row(
    p.thumb && previewUrl(p.thumb, 480),
    p.title,
    whenShort(p.updated_at),
    snippet ?? chipOf(p.kind, p.fields),
    `/p/${encodeURIComponent(p.slug)}`,
    p.kind,
    snippet && chipOf(p.kind, p.fields),
    dueOf(p),
  );
  const media = p.kind === "consume" ? String(p.fields.media_type ?? "") : "";
  if (media)
    li.querySelector(".sub > small")?.after(h("small", { className: `media ${media}` }, media));
  return li;
};

/** Captures still on the phone, oldest first. */
export async function pendingList(): Promise<Node> {
  const items = await queue.items();
  // The Retry and Discard buttons of a failed row: a chunk of its own, loaded when one shows
  const bar = items.some((i) => i.failed)
    ? (await import("./rowbar").catch(() => null))?.rowbar
    : undefined;
  return h(
    "ul",
    { className: "list pending" },
    ...items.map((i) => {
      const image = i.files.find((f) => f.blob.type.startsWith("image/"));
      const title = // files alone (a PDF, a .md, #380): not called a photo
        (i.page && `${image ? "Photo" : "File"} for ${i.to || "a page"}`) ||
        i.text?.split("\n")[0] ||
        i.url ||
        i.files[0]?.name ||
        "capture";
      const lost = i.error === "connection lost" && !navigator.onLine; // as now, not as it failed
      const why = lost ? "offline" : (i.error ?? (navigator.onLine ? "uploading" : "offline"));
      const state = i.failed ? `not saved: ${why}` : `waiting to upload (${why})`;
      const actions = i.failed && bar?.(i);
      const kind = i.kind ?? (!image && i.files[0] ? "file" : i.hint); // a file's icon
      const r = row(image?.blob ?? null, title, state, actions || "", undefined, kind);
      if (i.failed) r.className = "failed";
      return r;
    }),
  );
}

/** The latest pages from the server, or a note saying they need it. filter: an API query
 * (kind=todo); label: what a page opened from it says it is in; more: if given, a full list
 * ends in a Show more button that calls it. */
export async function pageList(
  limit: number,
  filter = "",
  label = "Latest",
  more?: () => void,
): Promise<Node> {
  try {
    if (!navigator.onLine) throw new TypeError("offline");
    const list = await api<Summary[]>(`pages?limit=${limit}&${filter}`, {
      signal: view.signal,
    });
    if (!list.length)
      return filter
        ? empty("note", "Nothing here.")
        : empty(
            "note",
            "Nothing captured yet.",
            h("small", {}, "Photos, notes and links you save show up here."),
          );
    const ul = h("ul", { className: "list" }, ...list.map((p) => pageRow(p)));
    swipeRows(list.map((p, i) => [ul.children[i], p]));
    trail(
      ul,
      label,
      list.map((p) => p.slug),
    );
    if (!more || list.length < limit) return ul;
    const button = h("button", { type: "button", className: "more", onclick: more }, "Show more");
    return h("div", {}, ul, button);
  } catch (e) {
    return problem(e);
  }
}

/** Which app build is running: the service worker's cache is named after it. */
export function build(): Node {
  const el = h("p", { className: "build", onclick: tapBuild });
  void self.caches
    ?.keys()
    .then((keys) => (el.textContent = keys.find((k) => k.startsWith("scrap-")) ?? ""));
  return el;
}

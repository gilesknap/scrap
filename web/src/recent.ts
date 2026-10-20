// Recent pages, newest first, with anything still waiting to upload above them.
import { api, previewUrl, type Summary } from "./api";
import { queue, view } from "./app";
import { tapBuild } from "./debug";
import { icon, kindIcon } from "./icons";
import { swipeRows, trail } from "./swipe";
import { blobImg, empty, h, problem, settle, whenShort } from "./ui";

const KIND: Record<string, string> = { todo: "todo", consume: "read later" };

function row(
  thumb: string | Blob | null,
  title: string,
  sub: string,
  extra: Node | string = "",
  href?: string,
  kind?: string,
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
      typeof extra === "string" && extra && h("em", {}, extra),
    ),
    typeof extra !== "string" && extra,
  );
  return h("li", {}, href ? h("a", { href }, img, body) : h("div", {}, img, body));
}

/** Captures still on the phone, oldest first. */
export async function pendingList(): Promise<Node> {
  const items = await queue.items();
  return h(
    "ul",
    { className: "list pending" },
    ...items.map((i) => {
      const image = i.files.find((f) => f.blob.type.startsWith("image/"));
      const title = i.text?.split("\n")[0] || i.url || i.files[0]?.name || "capture";
      const why = i.error ?? (navigator.onLine ? "uploading" : "offline");
      const state = i.failed ? `not saved: ${why}` : `waiting to upload (${why})`;
      // Each waits for an upload in progress (maybe in another tab), so say so.
      const act = (label: string, run: () => Promise<void>, sure = "") =>
        h(
          "button",
          {
            type: "button",
            className: label === "Discard" ? "danger" : "",
            onclick: (e: Event) => {
              if (sure && !confirm(sure)) return;
              const b = e.currentTarget as HTMLButtonElement;
              b.disabled = true;
              b.textContent = "Waiting for upload…";
              void run();
            },
          },
          label,
        );
      const tooBig = i.files.length > 1 && i.error?.startsWith("too large");
      const actions =
        i.failed &&
        h(
          "span",
          { className: "rowbar" },
          tooBig
            ? act("Split and retry", () => queue.splitRetry(i.id))
            : act("Retry", () => queue.retry(i.id)),
          act(
            "Discard",
            () => queue.discard(i.id),
            "Discard this capture? It never reached the server, so it will be gone.",
          ),
        );
      const r = row(image?.blob ?? null, title, state, actions || "", undefined, i.hint);
      if (i.failed) r.className = "failed";
      return r;
    }),
  );
}

/** The latest pages from the server, or a note saying they need it. */
/** label: what a page opened from it says it is in */
export async function pageList(limit: number, label = "Recent"): Promise<Node> {
  try {
    if (!navigator.onLine) throw new TypeError("offline");
    const list = await api<Summary[]>(`pages?limit=${limit}`);
    if (!list.length)
      return empty(
        "note",
        "Nothing captured yet.",
        h("small", {}, "Photos, notes and links you save show up here."),
      );
    const ul = h(
      "ul",
      { className: "list" },
      ...list.map((p) =>
        row(
          p.thumb && previewUrl(p.thumb, 480),
          p.title,
          whenShort(p.updated_at),
          KIND[p.kind],
          `/p/${encodeURIComponent(p.slug)}`,
          p.kind,
        ),
      ),
    );
    swipeRows(list.map((p, i) => [ul.children[i], p.slug, p.id]));
    return trail(
      ul,
      label,
      list.map((p) => p.slug),
    );
  } catch (e) {
    return problem(e);
  }
}

export async function recent(): Promise<Node> {
  const pending = h("div", {}, await pendingList());
  document.addEventListener(
    "queuechange",
    async () => pending.replaceChildren(await pendingList()),
    { signal: view.signal },
  );
  return h("section", {}, pending, await pageList(100), build());
}

/** Which app build is running: the service worker's cache is named after it. */
function build(): Node {
  const el = h("p", { className: "build", onclick: tapBuild });
  void self.caches
    ?.keys()
    .then((keys) => (el.textContent = keys.find((k) => k.startsWith("scrap-")) ?? ""));
  return el;
}

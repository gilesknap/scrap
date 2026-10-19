// Recent pages, newest first, with anything still waiting to upload above them.
import { api, blobUrl, type Summary } from "./api";
import { queue, view } from "./app";
import { h, when } from "./ui";

const KIND: Record<string, string> = { todo: "todo", consume: "read later" };

function row(thumb: string | null, title: string, sub: string, badge = "", href?: string) {
  const img = thumb
    ? h("img", { src: thumb, alt: "", loading: "lazy", decoding: "async" })
    : h("span", { className: "noimg" }, title.slice(0, 1).toUpperCase());
  const body = h(
    "span",
    {},
    h("strong", {}, title),
    h("small", {}, sub),
    badge && h("em", {}, badge),
  );
  return h("li", {}, href ? h("a", { href }, img, body) : h("div", {}, img, body));
}

/** Captures still on the phone, oldest first. */
export async function pendingList(): Promise<Node> {
  const items = await queue.items();
  return h(
    "ul",
    { className: "list" },
    ...items.map((i) => {
      const image = i.files.find((f) => f.blob.type.startsWith("image/"));
      const title = i.text?.split("\n")[0] || i.url || i.files[0]?.name || "capture";
      const why = i.error ?? (navigator.onLine ? "uploading" : "offline");
      const state = i.failed
        ? `not saved: ${why}, tap the badge to retry`
        : `waiting to upload (${why})`;
      return row(
        image ? URL.createObjectURL(image.blob) : null,
        title,
        state,
        i.failed ? "failed" : "",
      );
    }),
  );
}

/** The latest pages from the server, or a note saying they need it. */
export async function pageList(limit: number): Promise<Node> {
  try {
    if (!navigator.onLine) throw new Error("offline");
    const list = await api<Summary[]>(`pages?limit=${limit}`);
    if (!list.length) return h("p", { className: "empty" }, "Nothing captured yet.");
    return h(
      "ul",
      { className: "list" },
      ...list.map((p) =>
        row(
          p.thumb && blobUrl(p.thumb),
          p.title,
          when(p.updated_at),
          KIND[p.kind],
          `/p/${encodeURIComponent(p.slug)}`,
        ),
      ),
    );
  } catch {
    return h("p", { className: "empty" }, "Offline: recent pages need the server.");
  }
}

export async function recent(): Promise<Node> {
  const pending = h("div", {}, await pendingList());
  document.addEventListener(
    "queuechange",
    async () => pending.replaceChildren(await pendingList()),
    { signal: view.signal },
  );
  return h("section", {}, pending, await pageList(100));
}

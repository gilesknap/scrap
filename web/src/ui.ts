import { ApiError } from "./api";
import { rerender } from "./app";
import { type Icon, icon } from "./icons";
import { rendered, renderer } from "./md";

// DOM helpers: h() builds an element, toast() shows a message with an optional action.
type Kid = Node | string | null | undefined | false;

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props: Partial<HTMLElementTagNameMap[K]> & Record<string, unknown> = {},
  ...kids: Kid[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k.includes("-")) el.setAttribute(k, String(v));
    else (el as unknown as Record<string, unknown>)[k] = v;
  }
  el.append(...(kids.filter((k) => k || k === "") as (Node | string)[]));
  return el;
}

/** Put a toast just above what is under the thumb (the capture buttons, the page's tools, the
 * nav), so it covers neither the newest row nor a title; in the editor, under its top bar (the
 * CSS). placeToasts() places them again once a new view has drawn (main.ts), e.g. "Page
 * deleted" shown on the way back to a list. */
function place(el: HTMLElement) {
  const tops = [
    ...document.querySelectorAll(
      ".viewer .tools, body:not(.editing) :is(.actions, .page > .tools, nav)",
    ),
  ]
    .map((e) => e.getBoundingClientRect().top)
    .filter((t) => t > 0 && t <= innerHeight); // on screen
  el.style.top = tops.length ? "auto" : "";
  el.style.bottom = tops.length ? `${innerHeight - Math.min(...tops) + 8}px` : "";
}
export function placeToasts() {
  for (const el of document.querySelectorAll<HTMLElement>(".toast")) place(el);
}

/** Drop passing messages, e.g. on navigation; "keep" ones (an update offer) stay. */
export function clearToasts() {
  for (const old of document.querySelectorAll(".toast:not(.keep)")) old.remove();
}

export function toast(message: string, action?: string, onAction?: () => void, ms = 4000) {
  clearToasts();
  const el = h("div", { className: "toast", role: "status" }, h("span", { dir: "auto" }, message));
  if (action) {
    el.append(
      h("button", {
        type: "button",
        textContent: action,
        onclick: () => {
          el.remove();
          onAction?.();
        },
      }),
    );
  }
  place(el);
  document.body.append(el);
  if (ms) setTimeout(() => el.remove(), ms);
  else el.classList.add("keep"); // survives navigation
}

export const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

/** A date for a list row: no year if it is this year's. */
export function whenShort(iso: string) {
  const d = new Date(iso);
  const year = d.getFullYear() !== new Date().getFullYear() && "numeric";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    ...(year && { year }),
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Marks an image loaded (or failed) so its placeholder shimmer stops. */
export function settle<T extends HTMLImageElement>(img: T): T {
  const done = () => img.classList.add("loaded");
  img.addEventListener("load", done);
  img.addEventListener("error", done);
  return img;
}

/** Plain text with http(s) links made clickable; nothing is parsed as HTML. */
export function linkify(text: string): Node[] {
  return text
    .split(/(https?:\/\/[^\s<>"]+)/)
    .map((part, i) =>
      i % 2
        ? h("a", { href: part, target: "_blank", rel: "noopener noreferrer" }, part)
        : document.createTextNode(part),
    );
}

/** An empty or problem state: an icon, a line saying what is (not) here, and extras. */
export const empty = (name: Icon, line: string, ...more: Kid[]) =>
  h("div", { className: "empty" }, icon(name), h("p", {}, line), ...more);

/** Why a view could not load, in words, with a retry that renders the view again. */
export function problem(e: unknown): Node {
  if (e instanceof ApiError && e.status === 404) {
    const home = h("a", { href: "/", className: "button" }, "Back to capture");
    return empty("search", "Not found: it may have been deleted.", home);
  }
  const why =
    e instanceof ApiError
      ? e.message
      : navigator.onLine
        ? "Can't reach the server. Check your connection or VPN."
        : "Offline: this needs the server.";
  return empty("offline", why, h("button", { onclick: rerender }, icon("retry"), "Retry"));
}

/** An image of a Blob on the phone; its object URL is freed once shown. */
export function blobImg(blob: Blob, alt = ""): HTMLImageElement {
  const img = settle(h("img", { src: URL.createObjectURL(blob), alt }));
  img.onload = img.onerror = () => URL.revokeObjectURL(img.src);
  return img;
}

/** Ctrl/Cmd+Enter in a form submits it. */
export function saveKey(e: KeyboardEvent) {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    (e.currentTarget as HTMLFormElement).requestSubmit();
  }
}

// Share and Download are drawn here, in the app shell; what they do is in sharing.ts, a chunk
// loaded on the first tap.
const sharing = () => import("./sharing");
const later = (job: (m: typeof import("./sharing")) => unknown) =>
  void sharing().then(job, () => toast("Can't do that offline: reload scrap and try again"));

/** A Download link that fetches the file itself (sharing.ts), so it can say it is busy and
 * when the file is saved or why not. */
export function download(href: string, className = "button"): HTMLAnchorElement {
  const a = h("a", { href, className, download: "" }, icon("download"), "Download");
  a.onclick = (e) => {
    e.preventDefault();
    later((m) => m.download(a, href));
  };
  return a;
}

/** A page's own address, e.g. to share as a link. */
export const pageLink = (slug: string, origin = location.origin) =>
  `${origin}/p/${encodeURIComponent(slug)}`;

/** A Share button to send text, or a file from the server, to another app; none where
 * the phone can't share. Given the page's link, Share first asks which: **Link** (the
 * address, nothing fetched) or the content (`content`: its icon and word), then `more` (a
 * page's Download) if given. */
export function share(
  what: () => { title: string; text?: string; file?: string[] },
  link?: string,
  content: [Icon, string] = ["note", "Text"],
  more?: HTMLElement,
) {
  if (!navigator.share) return null;
  const b = h("button", { type: "button" }, icon("share"), "Share");
  // The first tap loads sharing.ts, which takes the button's taps from then on
  const first = (e: MouseEvent) => {
    b.onclick = null; // a second tap meanwhile: nothing twice
    void sharing().then(
      (m) => m.attach(b, { what, link, content, more })(e),
      () => {
        b.onclick = first;
        toast("Can't do that offline: reload scrap and try again");
      },
    );
  };
  b.onclick = first;
  return b;
}

/** Page text as Markdown (safe HTML from render.ts), or as typed with links made clickable:
 * also while the renderer is not loaded (load it first: renderer()). */
export function bodyView(text: string, raw: boolean): HTMLElement {
  const md = rendered();
  if (raw || !md) return h("div", { className: "body raw", dir: "auto" }, ...linkify(text));
  const el = h("div", { className: "body md", dir: "auto" });
  el.innerHTML = md.markdown(text);
  void md.diagrams(el);
  return el;
}

/** A Preview button that swaps a textarea for its text as formatted Markdown, and back. */
export function previewer(text: HTMLTextAreaElement) {
  const pane = h("div", { className: "preview", hidden: true });
  const button = h("button", { type: "button" }, "Preview");
  button.onclick = async () => {
    const on = pane.hidden;
    if (on) await renderer();
    pane.replaceChildren(bodyView(text.value, false));
    pane.hidden = !on;
    text.hidden = on;
    button.textContent = on ? "Edit" : "Preview";
    if (!on) text.focus();
  };
  return { button, pane };
}

import { ApiError } from "./api";
import { rerender } from "./app";
import { type Icon, icon } from "./icons";
import type { Titles } from "./linktext";
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
  // A computer: the foot of the window (css/desktop.css), its bars being at the top
  if (matchMedia(DESK).matches) return void Object.assign(el.style, { top: "", bottom: "" });
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
/** A computer, as css/desktop.css has it: a mouse and a wide window. */
const DESK = "(min-width: 900px) and (hover: hover) and (pointer: fine)";
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
function linkify(text: string): Node[] {
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
  return failed(why, h("button", { onclick: rerender }, icon("retry"), "Retry"));
}

/** A problem state (the server can't be reached): marked, so a quiet refresh can keep the old rows. */
const failed = (line: string, ...more: Kid[]) => {
  const el = empty("offline", line, ...more);
  el.classList.add("failed");
  return el;
};

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

/** A page's path in the app, for a link or go(). */
export const pageHref = (slug: string) => `/p/${encodeURIComponent(slug)}`;

/** A page's own address, e.g. to share as a link. */
export const pageLink = (slug: string, origin = location.origin) => `${origin}${pageHref(slug)}`;

/** Page text as Markdown (safe HTML from render.ts), or as typed with links made clickable:
 * also while the renderer is not loaded (load it first: renderer()). titles: of the pages it
 * links to, which a link with no label of its own shows. */
export function bodyView(text: string, raw: boolean, titles?: Titles): HTMLElement {
  const md = rendered();
  if (raw || !md) return h("div", { className: "body raw", dir: "auto" }, ...linkify(text));
  const el = h("div", { className: "body md", dir: "auto" });
  el.innerHTML = md.markdown(text, titles);
  void md.diagrams(el);
  void md.math(el);
  return el;
}

/** A Preview button that swaps a textarea for its text as formatted Markdown, and back. read
 * gives the text as Markdown (the editor's box shows embeds as tokens); titles, the titles of
 * the pages it links to. */
export function previewer(text: HTMLTextAreaElement, read = () => text.value, titles?: Titles) {
  const pane = h("div", { className: "preview", hidden: true });
  const button = h("button", { type: "button" }, "Preview");
  button.onclick = async () => {
    const on = pane.hidden;
    if (on) await renderer();
    pane.replaceChildren(bodyView(read(), false, titles));
    pane.hidden = !on;
    text.hidden = on;
    button.textContent = on ? "Edit" : "Preview";
    if (!on) text.focus();
  };
  return { button, pane };
}

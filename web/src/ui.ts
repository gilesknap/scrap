import { ApiError } from "./api";

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

/** Drop passing messages, e.g. on navigation; "keep" ones (an update offer) stay. */
export function clearToasts() {
  for (const old of document.querySelectorAll(".toast:not(.keep)")) old.remove();
}

export function toast(message: string, action?: string, onAction?: () => void, ms = 4000) {
  clearToasts();
  const el = h("div", { className: "toast", role: "status" }, message);
  if (action) {
    el.append(
      h("button", {
        textContent: action,
        onclick: () => {
          el.remove();
          onAction?.();
        },
      }),
    );
  }
  document.body.append(el);
  if (ms) setTimeout(() => el.remove(), ms);
  else el.classList.add("keep"); // survives navigation
}

export const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

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

/** Why a view could not load, in words, with a retry that renders the view again. */
export function problem(e: unknown): Node {
  if (e instanceof ApiError && e.status === 404) {
    const home = h("a", { href: "/" }, "Back to capture");
    return h(
      "div",
      { className: "empty" },
      h("p", {}, "Not found: it may have been deleted."),
      home,
    );
  }
  const why =
    e instanceof ApiError
      ? e.message
      : navigator.onLine
        ? "Can't reach the server. Check your connection or VPN."
        : "Offline: this needs the server.";
  const again = () => window.dispatchEvent(new PopStateEvent("popstate"));
  return h(
    "div",
    { className: "empty" },
    h("p", {}, why),
    h("button", { onclick: again }, "Retry"),
  );
}

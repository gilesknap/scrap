import { ApiError } from "./api";
import { rerender } from "./app";
import { type Icon, icon } from "./icons";
import { markdown } from "./md";

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

const mb = (n: number) =>
  n < 2 ** 20 ? `${Math.ceil(n / 1024)} kB` : `${(n / 2 ** 20).toFixed(1)} MB`;

/** The file name in a Content-Disposition header, if any. */
export function dispositionName(cd: string): string | undefined {
  const star = cd.match(/filename\*=UTF-8''([^;]+)/i);
  return star ? decodeURIComponent(star[1]) : cd.match(/filename="([^"]*)"/)?.[1];
}

/** Fetch a file from the server, named as given, else as the server names it. */
async function fetchFile(href: string, name?: string): Promise<File> {
  const r = await fetch(href).catch(() => {
    throw new Error("can't reach the server");
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `HTTP ${r.status}`);
  const blob = await r.blob();
  name ??= dispositionName(r.headers.get("Content-Disposition") ?? "") ?? "download";
  return new File([blob], name, { type: blob.type });
}

/** Run a job behind el, which says it is busy meanwhile and ignores taps; a failure says why. */
function busy(el: HTMLElement, what: string, job: () => Promise<void>) {
  return async (e: Event) => {
    e.preventDefault();
    if (el.getAttribute("aria-busy") === "true") return;
    const label = [...el.childNodes];
    el.setAttribute("aria-busy", "true");
    el.replaceChildren(...label.filter((n) => n.nodeType !== Node.TEXT_NODE), "Preparing…");
    try {
      await job();
    } catch (err) {
      if ((err as Error).name === "AbortError") return; // the share sheet was closed
      toast(`${what} failed: ${(err as Error).message}`, "", undefined, 8000);
    } finally {
      el.removeAttribute("aria-busy");
      el.replaceChildren(...label);
    }
  };
}

/** A Download link that fetches the file itself, so it can show it is busy and say when
 * the file is saved or why not (a plain download link gives no sign on Android). */
export function download(href: string, className = "button"): HTMLAnchorElement {
  const a = h("a", { href, className, download: "" }, icon("download"), "Download");
  a.onclick = busy(a, "Download", async () => {
    const file = await fetchFile(href);
    saveBlob(file, file.name);
  });
  return a;
}

/** Save a Blob made on the phone (or fetched) as a file, and say so. */
export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  h("a", { href: url, download: name }).click();
  setTimeout(() => URL.revokeObjectURL(url), 60_000); // the save may still be reading it
  toast(`Downloaded ${name} (${mb(blob.size)})`);
}

/** A page's own address, e.g. to share as a link. */
export const pageLink = (slug: string, origin = location.origin) =>
  `${origin}/p/${encodeURIComponent(slug)}`;

/** Where a menu of this width goes: just above its button, kept on the screen. */
export function menuSpot(button: DOMRect, width: number, screenW: number, screenH: number) {
  const gap = 8;
  const left = Math.min(button.left + (button.width - width) / 2, screenW - width - gap);
  return { left: Math.round(Math.max(left, gap)), bottom: Math.round(screenH - button.top + gap) };
}

/** A Share button to send text, or a file from the server, to another app; none where
 * the phone can't share. Given the page's link, Share first asks which: **Link** (the
 * address, nothing fetched) or the content (`content`: its icon and word). Each choice is a
 * tap of its own, so it calls the share sheet within that tap. */
export function share(
  what: () => { title: string; text?: string; file?: string[] },
  link?: string,
  content: [Icon, string] = ["note", "Text"],
) {
  if (!navigator.share) return null;
  const b = h("button", { type: "button" }, icon("share"), "Share");
  const send = (data: ShareData) =>
    navigator.share(data).catch((err: Error) => {
      if (err.name !== "AbortError") toast(`Share failed: ${err.message}`, "", undefined, 8000);
    });
  const shareContent = busy(b, "Share", async () => {
    const { title, text, file } = what();
    if (!file) return navigator.share({ title, text });
    const [href, name, type] = file;
    if (!canShareFile(name, type)) return toast("Sharing files is not supported here");
    const files = [await fetchFile(href, name)];
    try {
      await navigator.share({ title, files });
    } catch (err) {
      // A slow download outlasts the tap (Chrome allows ~5 s): share it on a fresh one.
      if ((err as Error).name !== "NotAllowedError") throw err;
      toast("Photo ready", "Share", () => void send({ title, files }), 30_000);
    }
  });
  const menu = h("div", { className: "share-menu", popover: "auto" });
  if (!link || !menu.showPopover) {
    b.onclick = shareContent; // nothing to choose, or no menu on this browser
    return b;
  }
  const pick = (glyph: Icon, label: string, go: (e: Event) => void) =>
    h(
      "button",
      {
        type: "button",
        onclick: (e: Event) => {
          menu.hidePopover();
          go(e);
        },
      },
      icon(glyph),
      label,
    );
  menu.append(
    pick("link", "Link", () => void send({ title: what().title, url: link })),
    pick(...content, shareContent),
  );
  b.setAttribute("aria-expanded", "false"); // a disclosure of two buttons, not a menu role
  const isOpen = () => menu.matches(":popover-open");
  menu.addEventListener("beforetoggle", (e) => {
    b.setAttribute("aria-expanded", String((e as ToggleEvent).newState === "open"));
  });
  menu.addEventListener("toggle", () => {
    if (!isOpen()) menu.remove();
  });
  // A tap on Share while the menu is open closes it, even where that tap's light dismiss
  // closes it first (a browser without a popover's source): so ask at the touch, not the click
  let wasOpen = false;
  b.onpointerdown = () => {
    wasOpen = isOpen();
  };
  b.onclick = (e) => {
    // Only a tap carries what its own touch saw (a key's click has detail 0), so a touch
    // dragged off the button can't leave a stale answer for the next key
    const open = (e.detail > 0 && wasOpen) || isOpen();
    wasOpen = false;
    if (b.getAttribute("aria-busy") === "true") return;
    if (open) {
      if (isOpen()) menu.hidePopover();
      return;
    }
    // Inside a modal dialog (the photo viewer), or assistive tech treats it as hidden
    (b.closest('[aria-modal="true"]') ?? document.body).append(menu);
    // The button as its source, so a tap on it toggles the menu rather than dismissing it
    (menu.showPopover as (o?: { source?: HTMLElement }) => void)({ source: b });
    const spot = menuSpot(b.getBoundingClientRect(), menu.offsetWidth, innerWidth, innerHeight);
    menu.style.left = `${spot.left}px`;
    menu.style.bottom = `${spot.bottom}px`;
  };
  return b;
}

/** Whether this phone can share a file like this, asked before downloading it. */
function canShareFile(name: string, type: string) {
  try {
    return !!navigator.canShare?.({ files: [new File([], name, { type })] });
  } catch {
    return false;
  }
}

/** Page text as Markdown (safe HTML from md.ts), or as typed with links made clickable. */
export function bodyView(text: string, raw: boolean): HTMLElement {
  if (raw) return h("div", { className: "body raw", dir: "auto" }, ...linkify(text));
  const el = h("div", { className: "body md", dir: "auto" });
  el.innerHTML = markdown(text);
  return el;
}

/** A Preview button that swaps a textarea for its text as formatted Markdown, and back. */
export function previewer(text: HTMLTextAreaElement) {
  const pane = h("div", { className: "preview", hidden: true });
  const button = h("button", { type: "button" }, "Preview");
  button.onclick = () => {
    const on = pane.hidden;
    pane.replaceChildren(bodyView(text.value, false));
    pane.hidden = !on;
    text.hidden = on;
    button.textContent = on ? "Edit" : "Preview";
    if (!on) text.focus();
  };
  return { button, pane };
}

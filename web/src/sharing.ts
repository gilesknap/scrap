// Sharing and downloading: what a Share or Download button does once tapped. A chunk of its
// own, loaded on the first tap (ui.ts draws the buttons), so the app shell carries only the
// buttons; the service worker keeps it for offline (vite.config.ts OFFLINE).
import type { Icon } from "./icons";
import { icon } from "./icons";
import { makeHtml } from "./pagehtml";
import { h, toast } from "./ui";

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
async function busy(el: HTMLElement, what: string, job: () => Promise<void>) {
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
}

/** A Download's tap: fetch the file itself, so it can show it is busy and say when the file
 * is saved or why not (a plain download link gives no sign on Android). */
export const download = (a: HTMLElement, href: string) =>
  busy(a, "Download", async () => {
    const file = await fetchFile(href);
    saveBlob(file, file.name);
  });

/** Save a Blob made on the phone (or fetched) as a file, and say so. */
export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  h("a", { href: url, download: name }).click();
  setTimeout(() => URL.revokeObjectURL(url), 60_000); // the save may still be reading it
  toast(`Downloaded ${name} (${mb(blob.size)})`);
}

/** Where a menu of this width goes: just above its button, kept on the screen. */
export function menuSpot(button: DOMRect, width: number, screenW: number, screenH: number) {
  const gap = 8;
  const left = Math.min(button.left + (button.width - width) / 2, screenW - width - gap);
  return { left: Math.round(Math.max(left, gap)), bottom: Math.round(screenH - button.top + gap) };
}

/** Whether a share failed because the tap's permission ran out (a slow download outlasts
 * it), not for a reason a fresh tap would not fix (a blocked file type, a permissions policy). */
export const tapExpired = (err: unknown) =>
  (err as Error).name === "NotAllowedError" && navigator.userActivation?.isActive === false;

/** Whether this phone can share a file like this, asked before downloading it. */
function canShareFile(name: string, type: string) {
  try {
    return !!navigator.canShare?.({ files: [new File([], name, { type })] });
  } catch {
    return false;
  }
}

const send = (data: ShareData) =>
  navigator.share(data).catch((err: Error) => {
    if (err.name !== "AbortError") toast(`Share failed: ${err.message}`, "", undefined, 8000);
  });

/** Share files at once; if the tap's permission ran out meanwhile (a slow download or export,
 * Chrome allows ~5 s), offer them on a fresh one. */
async function shareFiles(title: string, files: File[], ready: string) {
  try {
    await navigator.share({ title, files });
  } catch (err) {
    if (!tapExpired(err)) throw err;
    toast(ready, "Share", () => void send({ title, files }), 30_000);
  }
}

/** Share a file made on the phone (a drawing's PNG), checked shareable before it is made. */
export function shareMade(el: HTMLElement, title: string, name: string, make: () => Promise<Blob>) {
  const type = "image/png";
  return busy(el, "Share", async () => {
    if (!canShareFile(name, type)) return void toast("Sharing files is not supported here");
    const files = [new File([await make()], name, { type })];
    await shareFiles(title, files, "Drawing ready");
  });
}

/** Share a page's download (its Markdown, or a zip with its files) with the share sheet. The
 * photos in it are previews, which carry no EXIF or GPS. Where this phone can't share the
 * file, `saved` gets the plain download (the originals) instead. */
export async function sharePageFile(href: string, title: string, saved: (f: File) => void) {
  // Asked before the download, which is slow; the page's file is a zip, or Markdown if it has no files
  if (!canShareFile("page.zip", "application/zip")) return saved(await fetchFile(href));
  const file = await fetchFile(`${href}?photos=preview`);
  if (!canShareFile(file.name, file.type)) return saved(file); // Markdown, as a plain download has it
  try {
    await shareFiles(title, [file], "Page ready");
  } catch (err) {
    // Chrome refuses a zip with NotAllowedError although canShare said yes: save it instead
    if ((err as Error).name !== "NotAllowedError" || file.type !== "application/zip") throw err;
    saved(await fetchFile(href));
    toast("This phone can't share a zip; saved it instead");
  }
}

/** Share the page as it is shown, as one HTML file (pagehtml.ts): where this phone can't share
 * a file, `saved` gets it instead. */
export async function sharePageHtml(article: HTMLElement, title: string, saved: (f: File) => void) {
  if (!canShareFile("page.html", "text/html")) return saved(await makeHtml(article, title));
  const file = await makeHtml(article, title);
  await shareFiles(title, [file], "Page ready");
}

export interface Sharing {
  what: () => { title: string; text?: string; file?: string[] };
  link?: string; // the page's address: Share then asks Link or the content
  content: [Icon, string]; // the content's choice: its icon and word
  more?: HTMLElement[]; // last rows for the menu (a page's Download), closing it when tapped
}

/** Share's taps on button b: given a link, the first opens a menu of Link and the content
 * (and `more`); each choice is a tap of its own, so it calls the share sheet within that tap.
 * Without a link, or a popover, a tap shares the content at once. */
export function attach(b: HTMLButtonElement, s: Sharing) {
  const shareContent = () =>
    busy(b, "Share", async () => {
      const { title, text, file } = s.what();
      if (!file) return navigator.share({ title, text });
      const [href, name, type] = file;
      if (!canShareFile(name, type)) return toast("Sharing files is not supported here");
      const files = [await fetchFile(href, name)];
      await shareFiles(title, files, "Photo ready");
    });
  const menu = h("div", { className: "share-menu", popover: "auto" });
  if (!s.link || !menu.showPopover) {
    b.onclick = shareContent; // nothing to choose, or no menu on this browser
    return shareContent;
  }
  const pick = (glyph: Icon, label: string, go: () => void) =>
    h(
      "button",
      {
        type: "button",
        onclick: () => {
          menu.hidePopover();
          go();
        },
      },
      icon(glyph),
      label,
    );
  const link = s.link;
  menu.append(
    pick("link", "Link", () => void send({ title: s.what().title, url: link })),
    pick(...s.content, () => void shareContent()),
  );
  // The page's Download (an <a download>) is among `more`: Share can send what it saves
  const saved = s.more?.find((r) => r instanceof HTMLAnchorElement && r.hasAttribute("download"));
  const article = b.closest<HTMLElement>("article.page");
  const done = (f: File) => saveBlob(f, f.name);
  if (article && saved instanceof HTMLAnchorElement && "canShare" in navigator)
    menu.append(
      pick("note", "HTML", () => {
        void busy(b, "Share", () => sharePageHtml(article, s.what().title, done));
      }),
    );
  if (saved instanceof HTMLAnchorElement && "canShare" in navigator)
    menu.append(
      pick("file", "Zip", () => {
        void busy(b, "Share", () => sharePageFile(saved.href, s.what().title, done));
      }),
    );
  for (const row of s.more ?? []) {
    row.addEventListener("click", () => menu.hidePopover());
    menu.append(row);
  }
  b.setAttribute("aria-expanded", "false"); // a disclosure of its rows, not a menu role
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
  const tap = (e: MouseEvent) => {
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
    // The menu comes last in the page's tab order: put focus in it (Escape or a choice
    // returns it to Share, as a popover does)
    menu.querySelector("button")?.focus();
  };
  menu.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const rows = [...menu.querySelectorAll<HTMLElement>("button, a")];
    const at = rows.indexOf(document.activeElement as HTMLElement);
    rows[(at + (e.key === "ArrowDown" ? 1 : rows.length - 1)) % rows.length]?.focus();
    e.preventDefault();
  });
  b.onclick = tap;
  return tap;
}

// Copying from Share's menu where there is no share sheet (a computer): the page's link, its
// Markdown, or the page as formatted text for a paste into an email or a document. Part of
// the sharing chunk (sharing.ts), not the app shell.
import { toast } from "./ui";

/** Put text on the clipboard, and say what was copied. */
export async function copyText(text: string, what: string) {
  if (!navigator.clipboard?.writeText) throw new Error("this browser can't copy here");
  await navigator.clipboard.writeText(text);
  toast(`${what} copied`);
}

/** Put formatted text (html) and its plain text on the clipboard, so a paste into an email or
 * a document keeps the headings, lists and links, and a plain editor gets the text. The html
 * is made as a promise given to the clipboard within the tap (Safari and Firefox want the
 * write called in it, before the html is ready). Plain text only where the browser has no
 * ClipboardItem, or the write fails. */
export async function copyRich(html: () => Promise<string>, text: string) {
  if (typeof ClipboardItem === "undefined" || !navigator.clipboard?.write)
    return copyText(text, "Text");
  const blob = (s: string, type: string) => new Blob([s], { type });
  const made = html().then((s) => blob(s, "text/html"));
  // Marked handled: a browser that refuses the write never reads the promise, and its
  // rejection (offline) must not surface as unhandled; the write still sees it reject
  made.catch(() => {});
  const item = new ClipboardItem({
    "text/html": made,
    "text/plain": blob(text, "text/plain"),
  });
  try {
    await navigator.clipboard.write([item]);
  } catch {
    // A browser that takes a ClipboardItem but not a promise in it, or the html could not be
    // made (offline): the plain text still goes
    return copyText(text, "Text");
  }
  toast("Rich text copied");
}

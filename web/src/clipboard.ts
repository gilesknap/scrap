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
 * ClipboardItem. */
export async function copyRich(html: () => Promise<string>, text: string) {
  if (typeof ClipboardItem === "undefined" || !navigator.clipboard?.write)
    return copyText(text, "Text");
  const blob = (s: string, type: string) => new Blob([s], { type });
  const item = new ClipboardItem({
    "text/html": html().then((s) => blob(s, "text/html")),
    "text/plain": blob(text, "text/plain"),
  });
  await navigator.clipboard.write([item]);
  toast("Rich text copied");
}

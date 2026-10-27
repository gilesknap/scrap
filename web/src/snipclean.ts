// A search hit's snippet, tidied in place for its row (rows.ts, a chunk: kept out of the
// shell's snippet.ts): a web address said as words ("en.wikipedia.org · wiki / Integrated
// information theory", as a Later page's link card has it), its task boxes ("[x]", "[ ]", with any bullet before them) taken out,
// and its page's title cut from its start when the snippet only leads with it, so a row never
// says its title twice ("Release ibek 4.1" / "Release ibek 4.1 [x] Bump the schema…").
const BOX = /(^|\s)(?:[-*+] )?\[[ xX]\](?:\s+|$)/g;
const WORD = /[\p{L}\p{N}]+/gu;
const URLS = /https?:\/\/[^\s<>"]+/g;

/** A web address as a line to read: its site, then its path's words. */
const said = (href: string) => {
  try {
    const u = new URL(href);
    const path = decodeURIComponent(u.pathname)
      .replace(/\/+$/, "")
      .replace(/\.(html?|php|aspx?)$/i, "")
      .replace(/_+/g, " ")
      .split("/")
      .filter(Boolean)
      .join(" / ");
    return [u.hostname.replace(/^www\./, ""), path].filter(Boolean).join(" · ");
  } catch {
    return href; // cut short by the snippet: as it is (the row's CSS breaks it anywhere)
  }
};

const texts = (el: Element) => {
  const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const all: Text[] = [];
  for (let n = walk.nextNode(); n; n = walk.nextNode()) all.push(n as Text);
  return all;
};

/** A piece of snippet text with its addresses in words and no task boxes. */
export const clean = (text: string) =>
  text.replace(BOX, "$1").replace(URLS, (url) => {
    // Punctuation after an address belongs to the sentence ("(see https://a.com/x)."); a ")"
    // stays only when the address opened one itself (a Wikipedia title)
    let end = url.length;
    while (
      /[.,;:!?'\]]/.test(url[end - 1]) ||
      (url[end - 1] === ")" && !balanced(url.slice(0, end)))
    )
      end--;
    return said(url.slice(0, end)) + url.slice(end);
  });

const balanced = (u: string) => (u.match(/\(/g)?.length ?? 0) >= (u.match(/\)/g)?.length ?? 0);

/** How much of a snippet's start is only its title (whole words in order, punctuation
 * aside), when more follows; else 0 (a snippet that is only the title: echoes() takes it). */
export function leading(all: string, title: string): number {
  const words = title.toLowerCase().match(WORD);
  if (!words) return 0;
  const sep = "[^\\p{L}\\p{N}]";
  const lead = new RegExp(`^${sep}*${words.join(`${sep}+`)}(?![\\p{L}\\p{N}])${sep}*`, "iu");
  const m = lead.exec(all);
  return m && m[0].length < all.length ? m[0].length : 0;
}

/** Tidy a row's snippet: addresses in words, no task boxes, and no title leading it. */
export function tidy(snip: Element, title: string) {
  for (const t of texts(snip)) t.data = clean(t.data);
  let cut = leading(snip.textContent ?? "", title);
  if (!cut) return;
  for (const t of texts(snip)) {
    const k = Math.min(cut, t.data.length);
    t.data = t.data.slice(k);
    cut -= k;
    if (!cut) break;
  }
  for (const m of snip.querySelectorAll("mark")) if (!m.textContent) m.remove(); // cut away
}

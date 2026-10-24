export const MAX_PAGE = 1_000_000; // bytes of UTF-8: a page's text at most (the server's store.MAX_PAGE)

// What the server adds to a page's text for each photo: "\n\n![](/api/blobs/<sha256>/preview?size=2048)"
const EMBED_BYTES = 2 + "![](/api/blobs/".length + 64 + "/preview?size=2048)".length;

/** How many bytes the server may add for these files: an embed per image (an upper bound:
 * the same image twice gets one, and a file with no type may not be an image). */
export function embedBytes(files: { type: string }[]) {
  const maybe = (f: { type: string }) =>
    f.type.startsWith("image/") || f.type === "" || f.type === "application/octet-stream";
  return files.filter(maybe).length * EMBED_BYTES;
}

/** Why text can't be saved as a page's (over 1 MB), said before sending it; else null.
 * extra: bytes the server adds (see embedBytes). unchanged: the text is what the page
 * already has, so there is nothing to refuse (an imported page may be over the limit). */
export function tooLong(text: string, extra = 0, unchanged = false) {
  const n = new TextEncoder().encode(text).length + extra;
  return n > MAX_PAGE && !unchanged
    ? `Not saved: the text is ${n.toLocaleString("en-US")} bytes, and a page holds at most ${MAX_PAGE.toLocaleString("en-US")} (1 MB)`
    : null;
}

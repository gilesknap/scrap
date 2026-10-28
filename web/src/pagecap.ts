export const MAX_PAGE = 1_000_000; // bytes of UTF-8: a page's text at most (the server's store.MAX_PAGE)

// What the server adds to a page's text for each photo: "\n\n![](/api/blobs/<sha256>/preview?size=2048)"
const EMBED_BYTES = 2 + "![](/api/blobs/".length + 64 + "/preview?size=2048)".length;

/** How many bytes the server may add for these files: an embed per image, and a link per other
 * file, "[name](/api/blobs/<sha256>)", where the composer placed it (#403), once for each of its
 * tokens in text (as sent: ⟦image N⟧, ⟦file N⟧, N its place from 1), else once. An upper bound:
 * the same image twice gets one, a file with no type may not be an image, and a placed file's
 * link takes its token's place. */
export function embedBytes(files: { type: string; name?: string }[], text = "") {
  const maybe = (f: { type: string }) =>
    f.type.startsWith("image/") || f.type === "" || f.type === "application/octet-stream";
  const link = (f: { name?: string }) =>
    "[](/api/blobs/)".length + 64 + new TextEncoder().encode(f.name ?? "file").length;
  const times = (i: number) =>
    Math.max(1, text.match(new RegExp(`⟦(?:image|file) ${i + 1}⟧`, "g"))?.length ?? 0);
  return files.reduce((n, f, i) => n + times(i) * Math.max(maybe(f) ? EMBED_BYTES : 0, link(f)), 0);
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

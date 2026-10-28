// Embeds of scrap's own files in page text, an image's ![alt](/api/blobs/<sha>/preview?size=2048)
// or a file's [name](/api/blobs/<sha>), as the editor shows them: a short token each
// (⟦image 1⟧, ⟦file 1: name.pdf⟧), not three lines of hex a stray tap can damage. Pure
// functions of the text (no DOM): tokenise() when the editor opens, expand() whenever its
// text is read, which gives the text back byte for byte where no token was touched. A token
// deleted or mangled is no embed: what is left of it stays as typed. Part of the editor's chunk.

// An embed, as the server's backup.OWN_BLOB reads them
const EMBED =
  /(!?)\[([^[\]\n]*)\]\(\/api\/blobs\/([0-9a-f]{64})(?:\/preview\?size=\d+|\?download=1)?\)/g;
// A token, or what may be one: brackets no keyboard types by accident
export const TOKEN = /⟦[^⟦⟧\n]*⟧/g;

export interface Embed {
  token: string; // as the text box has it
  md: string; // the Markdown it stands for, exactly as it was
  sha: string;
  image: boolean; // else a file's link
  n: number; // its number among the images, or among the files
  label: string; // its alt text or file name, else "Image 1"
  blob?: Blob; // a file not yet on the server: the composer's (pending.ts), md its token
}

export const short = (s: string) => (s.length > 32 ? `${s.slice(0, 31)}…` : s);

/** body with each embed replaced by its token, and the embeds. */
export function tokenise(body: string): { text: string; embeds: Embed[] } {
  const embeds: Embed[] = [];
  const count = { image: 0, file: 0 };
  const text = body.replace(EMBED, (md: string, bang: string, alt: string, sha: string) => {
    const image = !!bang;
    const name = alt.trim();
    const shown = short(name.replace(/[⟦⟧]/g, "")); // a bracket would end the token
    let n: number;
    let token: string;
    do {
      n = image ? ++count.image : ++count.file;
      token = image ? `⟦image ${n}⟧` : `⟦file ${n}${shown ? `: ${shown}` : ""}⟧`;
    } while (body.includes(token)); // typed in the text already: it stays text
    const label = name || `${image ? "Image" : "File"} ${n}`;
    embeds.push({ token, md, sha, image, n, label });
    return token;
  });
  return { text, embeds };
}

/** text with each whole token of embeds put back as its Markdown; anything else as it is. */
export function expand(text: string, embeds: Embed[]): string {
  const md = new Map(embeds.map((e) => [e.token, e.md]));
  return text.replace(TOKEN, (t) => md.get(t) ?? t);
}

/** The tokens of embeds in text, in its order (a token pasted twice: twice), with where. */
export function found(text: string, embeds: Embed[]) {
  const by = new Map(embeds.map((e) => [e.token, e]));
  return [...text.matchAll(TOKEN)].flatMap((m) => {
    const embed = by.get(m[0]);
    return embed ? [{ embed, at: m.index }] : [];
  });
}

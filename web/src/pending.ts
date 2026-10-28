// The composer's photos and files (#403), as the page editor shows its embeds: a token in the
// text where each goes (⟦image 1⟧, ⟦file 1: minutes.pdf⟧) and a chip under it (editor.ts
// embedded()). The files stay on the phone until Save; the server puts each one's embed or link
// where its token is, since only then is its address known (a photo is made smaller when it is
// queued, which changes its SHA-256). Pure functions of the text, in the composer's chunk.
import { type Embed, found, short, TOKEN } from "./embeds";
import type { Change } from "./listedit";

/** A pending embed for a file: its token (as kept in a draft, else a new one numbered after
 * those in text or taken, images and files counted apart, as the editor counts them). */
export function pend(file: File, taken: Embed[], text: string, token?: string): Embed {
  const image = file.type.startsWith("image/");
  // A bracket would end the token, a line break or control character split it
  // biome-ignore lint/suspicious/noControlCharactersInRegex: taken out of a name, on purpose
  const name = short(file.name.replace(/[⟦⟧]/g, "").replace(/[\x00-\x1f]/g, " "));
  let n = Number(token?.match(/\d+/)?.[0]);
  if (!token) {
    n = 0;
    do {
      n++;
      token = image ? `⟦image ${n}⟧` : `⟦file ${n}: ${name}⟧`;
    } while (
      text.includes(token) ||
      taken.some((e) => e.token === token || (e.image === image && e.n === n))
    );
  }
  return {
    token,
    md: token,
    sha: "",
    image,
    n,
    label: image ? `Image ${n}` : file.name,
    blob: file,
  };
}

/** Tokens put in text in place of from..to (the caret), each a paragraph of its own (an image
 * alone in one is a figure on the page), the caret after them, ready for the next line. */
export function placeAt(text: string, from: number, to: number, tokens: string[]): Change {
  const before = text.slice(0, from);
  const after = text.slice(to);
  const lead = !before || before.endsWith("\n\n") ? "" : before.endsWith("\n") ? "\n" : "\n\n";
  const trail = after.startsWith("\n\n") ? "" : after.startsWith("\n") ? "\n" : "\n\n";
  const insert = lead + tokens.join("\n\n") + trail;
  const at = from + insert.length;
  return { from, to, insert, start: at, end: at };
}

/** The pending files whose tokens are in text, in the order of their first token. */
export function placed(text: string, pending: Embed[]): Embed[] {
  const out = new Set<Embed>();
  for (const { embed } of found(text, pending)) out.add(embed);
  return [...out];
}

// What the server reads as a token placing a file (store UPLOAD_TOKEN)
const SERVER = /^⟦(?:image|file) [1-9]\d{0,3}(?::[^⟦⟧\n]*)?⟧$/;

/** What Save sends: the files placed in text, in the order of their first token, and text with
 * each of their tokens as the server reads it, ⟦image N⟧ or ⟦file N⟧, N the file's place among
 * those sent (from 1). A file whose token was deleted is not sent. With files sent, text that
 * would read as such a token but is none of them (one pasted from another page's Edit) has
 * plain brackets instead, [image 1], so the server cannot put a file there; other text stays as
 * it is. */
export function wire(text: string, pending: Embed[]): { text: string; files: File[] } {
  const sent = placed(text, pending);
  const out = text.replace(TOKEN, (t) => {
    const i = sent.findIndex((e) => e.token === t);
    if (i >= 0) return `⟦${sent[i].image ? "image" : "file"} ${i + 1}⟧`;
    return sent.length && SERVER.test(t) ? `[${t.slice(1, -1)}]` : t;
  });
  return { text: out, files: sent.map((e) => e.blob as File) };
}

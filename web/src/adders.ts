// Camera, Gallery and File under the editor's text, the composer's and a page's Edit alike
// (#403): each file picked is a token where the caret is (⟦image 1⟧, ⟦file 1: minutes.pdf⟧),
// a paragraph of its own, with a chip under the fields (editor.ts embedded()). The files stay
// on the phone until Save, which sends those still in the text (pending.ts wire()). Part of
// the editor's chunk.
import { FILES, picker } from "./capture";
import type { embedded } from "./editor";
import { offTokens, pend, placeAt } from "./pending";
import { h } from "./ui";

type Embeds = ReturnType<typeof embedded>;

/** The row of three, and add(): files put in text at..to (the caret, else where asked). */
export function adders(text: HTMLTextAreaElement, em: Embeds) {
  const add = (more: File[], at = text.selectionStart, to = text.selectionEnd) => {
    const tokens = more.map((f) => {
      const e = pend(f, em.list(), text.value);
      em.add(e);
      return e.token;
    });
    const c = placeAt(text.value, ...offTokens(text.value, at, to), tokens);
    text.setRangeText(c.insert, c.from, c.to);
    text.setSelectionRange(c.start, c.end);
    text.dispatchEvent(new Event("input", { bubbles: true })); // its chips, and the draft kept
  };
  const bar = h(
    "div",
    { className: "bar", role: "group", "aria-label": "Add photo" },
    picker("Camera", true, add, "add"),
    picker("Gallery", false, add, "add"),
    picker("File", false, add, "add", FILES),
  );
  return { bar, add };
}

/** A draft's pending files back in the editor: each with its token, if the text still has
 * it; the rest (an older build's draft kept no tokens) for the caller to place. */
export function restore(em: Embeds, text: string, files: File[] = [], tokens: string[] = []) {
  const lost: File[] = [];
  files.forEach((f, i) => {
    const token = tokens[i];
    if (token && text.includes(token)) em.add(pend(f, [], "", token));
    else lost.push(f);
  });
  return lost;
}

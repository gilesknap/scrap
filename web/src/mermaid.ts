// Mermaid diagrams in page text (a chunk of its own, loaded only for a page with a ```mermaid
// block, and not kept offline: it is big). Strict: no HTML labels, no click handlers, its
// SVG sanitised. Bundled here, not from a CDN.
import mermaid from "mermaid";

let drawn = 0; // each diagram's id is new
let ready = false;

/** Replace each code block (a <code> in its <pre>) with its diagram, if it is one. */
export async function draw(blocks: HTMLElement[]) {
  if (!ready) {
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: dark ? "dark" : "neutral",
      fontFamily: "inherit",
    });
    ready = true;
  }
  for (const code of blocks) {
    const text = code.textContent ?? "";
    try {
      if (!(await mermaid.parse(text, { suppressErrors: true }))) continue; // stays as code
      const { svg } = await mermaid.render(`diagram-${++drawn}`, text);
      const box = document.createElement("div");
      box.className = "diagram";
      box.setAttribute("role", "img");
      box.innerHTML = svg;
      code.parentElement?.replaceWith(box);
    } catch {
      // stays as code
    }
  }
}

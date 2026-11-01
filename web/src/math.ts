// Maths in page text, drawn by KaTeX (a chunk of its own, loaded only for a page with maths,
// and kept offline: OFFLINE in vite.config.ts). Bundled with its CSS and fonts, not from a CDN.
// No \href, \url or \htmlClass (trust: false). A formula it can't draw stays as its TeX.
import katex from "katex";
import "katex/dist/katex.min.css";
import { KATEX } from "./katexopts";

/** Draw each maths element (render.ts math(): a .math span or div, or a ```math block's
 * <code>), keeping its TeX in data-tex for Share's file (pagehtml.ts). */
export function draw(found: HTMLElement[]) {
  for (const el of found) {
    const code = el.matches("code");
    const tex = el.textContent ?? "";
    const box = code ? document.createElement("div") : el;
    const display = code || box.classList.contains("display");
    try {
      // Drawn apart first, so a mistake leaves the TeX as it was
      const out = document.createElement(box.tagName);
      katex.render(tex.trim(), out, { ...KATEX, displayMode: display });
      box.replaceChildren(...out.childNodes);
    } catch (e) {
      el.classList.add("math-error");
      el.title = e instanceof Error ? e.message : String(e);
      continue;
    }
    box.dataset.tex = tex.trim();
    if (code) {
      box.className = "math display";
      const pre = el.parentElement;
      const at = el.getAttribute("data-at");
      if (at) box.setAttribute("data-at", at);
      pre?.replaceWith(box);
    }
  }
}

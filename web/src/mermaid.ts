// Mermaid diagrams in page text (a chunk of its own, loaded only for a page with a ```mermaid
// block, and not kept offline: it is big). Strict: no HTML labels, no click handlers, its
// SVG sanitised. Bundled here, not from a CDN.
import mermaid from "mermaid";
import { currentApp } from "./theme";

let drawn = 0; // each diagram's id is new
/** tokens.css's --font: a public page's diagram is an <img>, which inherits no font. */
const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

// One diagram at a time: mermaid's configuration is global, and the app's diagrams and a
// public page's (svgFor) are drawn with different ones
let queue: Promise<unknown> = Promise.resolve();
function serial<T>(work: () => Promise<T>): Promise<T> {
  const next = queue.then(work, work);
  queue = next.catch(() => {});
  return next;
}

const configure = (dark: boolean, extra: object = {}) =>
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    theme: dark ? "dark" : "neutral",
    fontFamily: "inherit",
    ...extra,
  });

/** Replace each code block (a <code> in its <pre>) with its diagram, if it is one. */
export async function draw(blocks: HTMLElement[]) {
  for (const code of blocks) {
    const text = code.textContent ?? "";
    try {
      const svg = await serial(async () => {
        // Each time: the app theme may have been changed since (earlier diagrams stay as drawn)
        configure(currentApp() === "dark");
        if (!(await mermaid.parse(text, { suppressErrors: true }))) return null; // stays as code
        return (await mermaid.render(`diagram-${++drawn}`, text)).svg;
      });
      if (svg === null) continue;
      const box = document.createElement("div");
      box.className = "diagram";
      box.dataset.source = text; // a public page publishes it from its source (publicpages.ts)
      box.setAttribute("role", "img");
      box.innerHTML = svg;
      code.parentElement?.replaceWith(box);
    } catch {
      // stays as code
    }
  }
}

/** A diagram as a public page shows it (#525): an SVG for an <img>, in the light or the dark
 * theme, drawn as draw() draws it but with SVG labels (no foreignObject, which scrap's
 * sanitiser drops), the font named, and its own size from its viewBox (an <img> of a
 * width="100%" SVG has none). Throws if it cannot be drawn so. */
export function svgFor(text: string, theme: "light" | "dark"): Promise<string> {
  return serial(async () => {
    configure(theme === "dark", { fontFamily: FONT, htmlLabels: false });
    await mermaid.parse(text); // throws, saying why
    // (the same id each time, one diagram at a time: the same diagram is the same file)
    const { svg } = await mermaid.render(`public-diagram-${theme}`, text);
    const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
    const root = doc.documentElement;
    if (root.nodeName !== "svg" || doc.getElementsByTagName("parsererror").length)
      throw new Error("not an SVG");
    if (root.getElementsByTagName("foreignObject").length) throw new Error("it has HTML labels");
    const box = (root.getAttribute("viewBox") ?? "")
      .trim()
      .split(/[\s,]+/)
      .map(Number);
    if (box.length !== 4 || !box.every(Number.isFinite) || box[2] <= 0 || box[3] <= 0)
      throw new Error("it has no size");
    root.setAttribute("width", String(Math.ceil(box[2])));
    root.setAttribute("height", String(Math.ceil(box[3])));
    root.removeAttribute("style");
    return new XMLSerializer().serializeToString(root);
  });
}

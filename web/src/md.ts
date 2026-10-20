// Page text: the Markdown renderer (render.ts, a chunk of its own, loaded when a page is
// shown and kept for offline use: not part of the app shell), and the text Share sends.
type Renderer = typeof import("./render");
let loaded: Renderer | null = null;
let loading: Promise<Renderer | null> | null = null;

/** The renderer, loaded once (null if it can't be, offline before it was kept: try again). */
export function renderer(): Promise<Renderer | null> {
  loading ??= import("./render")
    .then((m) => (loaded = m))
    .catch(() => {
      loading = null;
      return null;
    });
  return loading;
}

/** The renderer if it is loaded already. */
export const rendered = () => loaded;

const EMBEDS = /^\s*(!\[[^\]\n]*\]\(\/api\/blobs\/[^)\s]+\)\s*)+$/;

/** Text for other apps (Share): without the lines that only embed this server's images, nor
 * the blank line each leaves; code and everything else as typed. */
export function unembedded(text: string): string {
  const out: string[] = [];
  let fence: RegExp | null = null; // what closes the open code fence
  let gap = false; // a line was dropped since the last line kept
  for (const line of text.replace(/\r\n?/g, "\n").split("\n")) {
    const open = line.match(/^ {0,3}(`{3,}|~{3,})/)?.[1];
    if (fence) {
      if (fence.test(line)) fence = null;
    } else if (open) fence = new RegExp(`^ {0,3}${open[0]}{${open.length},}\\s*$`);
    else if (EMBEDS.test(line)) {
      gap = true;
      continue;
    }
    if (gap && !line.trim() && !out.at(-1)?.trim()) continue; // the blank line it left
    gap = false;
    out.push(line);
  }
  while (gap && out.length && !out.at(-1)?.trim()) out.pop(); // a gap left at the end
  return out.join("\n");
}

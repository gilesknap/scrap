// Page text: the Markdown renderer (render.ts, a chunk of its own, loaded when a page is
// shown and kept for offline use: not part of the app shell). The text Share sends is sharetext.ts.
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

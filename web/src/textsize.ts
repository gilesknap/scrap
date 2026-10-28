// Text size (Settings, kept on this device): the root font size that every rem follows.
// Phone (the default) leaves it to css/base.css: 17 px times the phone's font size (Android,
// through text-scale) or an iPhone's text size, never under 17 px (main.ts). A percentage sets
// scrap's own size instead, 17 px times it, whatever the phone says, marked data-text so
// main.ts leaves it. theme-init.js does the same before the first paint; this is Settings'.
import { kept } from "./api";

export const TEXT_KEY = "scrap.text_size";

/** The chosen size as a factor of 17 px, or null: the phone's. */
export const textSize = () => {
  const n = Number(kept(TEXT_KEY));
  return n >= 0.8 && n <= 1.3 ? n : null;
};

/** Keep the choice (null: the phone's) and show it at once. */
export function setTextSize(n: number | null) {
  kept(TEXT_KEY, n ? String(n) : null);
  const html = document.documentElement;
  html.style.fontSize = n ? `${17 * n}px` : "";
  if (n) html.dataset.text = String(n);
  else delete html.dataset.text;
  if (!n && parseFloat(getComputedStyle(html).fontSize) < 17) html.style.fontSize = "17px";
}

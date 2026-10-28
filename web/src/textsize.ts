// Text size (Settings, kept on this device): the root font size that every rem follows.
// Phone (the default) leaves it to css/base.css: 17 px times the phone's font size (Android,
// through text-scale) or an iPhone's text size, never under 17 px (main.ts). A percentage sets
// scrap's own size instead, 17 px times it, whatever the phone says, marked data-text so
// main.ts leaves it. theme-init.js does the same before the first paint; this is Settings'.
import { kept } from "./api";

export const TEXT_KEY = "scrap.text_size";

/** The sizes Settings offers, as kept (a string, so "1e0" or "0x1" are not "1") and as shown.
 * public/theme-init.js has the same list of values: change both. The 17 px is css/base.css's
 * and main.ts's floor() as well. */
export const SIZES: [string, string][] = [
  ["0.8", "80%"],
  ["0.9", "90%"],
  ["1", "100%"],
  ["1.15", "115%"],
  ["1.3", "130%"],
];

/** The chosen size as a factor of 17 px, or null: the phone's (nothing, or anything else). */
export const textSize = () => {
  const v = kept(TEXT_KEY);
  return SIZES.some(([k]) => k === v) ? Number(v) : null;
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

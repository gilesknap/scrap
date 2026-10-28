// Text size (Settings, kept on this device): the root font size that every rem follows. 100%,
// the default, is scrap's 17 px, sized as a web page is (the browser's zoom applies to it). A
// percentage is 17 px times it. Phone follows the phone's font size instead (css/base.css:
// Android's through text-scale, an iPhone's text size), never under 17 px. main.ts applies the
// kept choice at the start and when the app comes back, theme-init.js before the first paint;
// this is Settings', at once.
import { kept } from "./api";

export const TEXT_KEY = "scrap.text_size";

/** What Settings offers, as kept and as shown. "1" (100%) is kept as nothing: the default. */
export const SIZES: [string, string][] = [
  ["phone", "Phone"],
  ["0.8", "80%"],
  ["0.9", "90%"],
  ["1", "100%"],
  ["1.15", "115%"],
  ["1.3", "130%"],
];

/** The choice: one of SIZES' keys ("1" if nothing or anything else is kept). */
export const textSize = () => {
  const v = kept(TEXT_KEY);
  return SIZES.some(([k]) => k === v) ? (v as string) : "1";
};

/** Keep the choice and show it at once, as main.ts's floor() does. */
export function setTextSize(v: string) {
  kept(TEXT_KEY, v === "1" ? null : v);
  const html = document.documentElement;
  const n = Number(v);
  html.dataset.text = v === "1" ? "" : v;
  html.style.fontSize = n >= 0.8 && n <= 1.3 && v !== "1" ? `${17 * n}px` : "";
  if (v === "phone" && parseFloat(getComputedStyle(html).fontSize) < 17)
    html.style.fontSize = "17px";
}

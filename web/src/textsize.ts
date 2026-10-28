// Text size (Settings, kept on this device): the root font size that every rem follows. An
// installed app on Android is not given the phone's font size, so it is chosen here;
// theme-init.js sets it before the first paint. Default: 17 px, or an iPhone's text size
// (css/base.css), never under 17 px.
import { kept } from "./api";

export const TEXT_KEY = "scrap.text_size";

/** The chosen size as a factor of 17 px: 1 (the default), or up to 1.5. */
export const textSize = () => {
  const n = Number(kept(TEXT_KEY));
  return n > 1 && n <= 1.5 ? n : 1;
};

/** Set the root font size: the chosen size, else the default (measured again when the app
 * comes back: an iPhone's setting may have changed meanwhile). */
export function applyText() {
  const root = document.documentElement.style;
  const n = textSize();
  root.fontSize = n > 1 ? `${17 * n}px` : "";
  if (parseFloat(getComputedStyle(document.documentElement).fontSize) < 17) root.fontSize = "17px";
}

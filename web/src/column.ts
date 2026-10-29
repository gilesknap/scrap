// Maximum column width (Settings, kept on this device): the most css/todos.css's centred
// column grows to on a wide window (a computer); a narrower window still shrinks it, with the
// usual gutter, so nothing scrolls sideways. 800 px, the default, is tokens.css's --column, kept
// as nothing. theme-init.js applies the kept choice before the first paint, main.ts again at
// the start and when the app comes back; this is Settings', at once.
import { kept } from "./api";

export const COLUMN_KEY = "scrap.column";

/** What Settings offers, as kept and as shown. "800" (the default) is kept as nothing. */
export const COLUMNS: [string, string][] = [
  ["720", "Narrow (720px)"],
  ["800", "Medium (800px)"],
  ["880", "Wide (880px)"],
  ["960", "Wider (960px)"],
];

/** The choice: one of COLUMNS' keys ("800" if nothing or anything else is kept). */
export const columnWidth = () => {
  const v = kept(COLUMN_KEY);
  return COLUMNS.some(([k]) => k === v) ? (v as string) : "800";
};

/** Keep the choice and show it at once, as main.ts's columnFloor() does. */
export function setColumnWidth(v: string) {
  kept(COLUMN_KEY, v === "800" ? null : v);
  document.documentElement.style.setProperty("--column", v === "800" ? "" : `${v}px`);
}

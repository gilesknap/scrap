// The app's and the drawings' colour themes: what the user chose (Settings, kept on this
// device) and what that comes to, here and nowhere else. The app theme is the data-theme
// attribute on <html>, which tokens.css reads; "system" leaves it off and follows the OS.
// Changing it is settings.ts (a lazy chunk).
import { kept } from "./api";

export type Theme = "light" | "dark";
export type AppPref = "system" | Theme;
export type DrawPref = Theme | "app";

export const APP_KEY = "scrap.theme";
export const DRAW_KEY = "scrap.drawings_theme";

export const appPref = (raw: string | null): AppPref =>
  raw === "light" || raw === "dark" ? raw : "system";
export const drawPref = (raw: string | null): DrawPref =>
  raw === "dark" || raw === "app" ? raw : "light";

/** The app's theme: the choice, or the OS's for "system". */
export const appTheme = (pref: AppPref, systemDark: boolean): Theme =>
  pref === "system" ? (systemDark ? "dark" : "light") : pref;

/** The drawings' theme: the choice, or the app's for "app". */
export const drawingTheme = (pref: DrawPref, app: Theme): Theme => (pref === "app" ? app : pref);

const system = () => matchMedia("(prefers-color-scheme: dark)");
// Held here as well: with storage refused (a private tab) the choice still lasts the session
export const held: { app: AppPref | null; draw: DrawPref | null } = { app: null, draw: null };
export const getAppPref = () => (held.app ??= appPref(kept(APP_KEY)));
export const getDrawPref = () => (held.draw ??= drawPref(kept(DRAW_KEY)));
export const currentApp = () => appTheme(getAppPref(), system().matches);
export const currentDrawings = () => drawingTheme(getDrawPref(), currentApp());

const listeners = new Set<() => void>();
/** Tell the listeners (a setting changed, or the OS's). */
export const changed = () => {
  for (const fn of listeners) fn();
};

/** Be told when the effective app or drawings theme may have changed. Returns the stop. */
export function onTheme(fn: () => void): () => void {
  if (!listeners.size) system().addEventListener("change", changed); // cheap if nothing follows
  listeners.add(fn);
  return () => void listeners.delete(fn);
}

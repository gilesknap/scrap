// The app's and the drawings' colour themes: what the user chose (Settings, kept on this
// device) and what that comes to, here and nowhere else. The app theme is the data-theme
// attribute on <html>, which tokens.css reads; "system" leaves it off and follows the OS.
import { kept } from "./api";

export type Theme = "light" | "dark";
export type AppPref = "system" | Theme;
export type DrawPref = Theme | "app";

export const APP_KEY = "scrap.theme";
export const DRAW_KEY = "scrap.drawings_theme";
// theme-color per theme: the page background of each (tokens.css --bg)
const CHROME: Record<Theme, string> = { light: "#f6f3ec", dark: "#161411" };

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
const listeners = new Set<() => void>();

export const getAppPref = () => appPref(kept(APP_KEY));
export const getDrawPref = () => drawPref(kept(DRAW_KEY));
export const currentApp = () => appTheme(getAppPref(), system().matches);
export const currentDrawings = () => drawingTheme(getDrawPref(), currentApp());

/** Show the app theme: the attribute, the form-control scheme and the browser's bar colour. */
export function applyTheme() {
  const pref = getAppPref();
  const root = document.documentElement;
  if (pref === "system") root.removeAttribute("data-theme");
  else root.dataset.theme = pref;
  const metas = document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]');
  const colours = [CHROME.light, CHROME.dark];
  metas.forEach((m, i) => {
    m.content = pref === "system" ? colours[i] : CHROME[pref];
  });
}

/** Be told when the effective app or drawings theme may have changed. Returns the stop. */
export function onTheme(fn: () => void): () => void {
  listeners.add(fn);
  return () => void listeners.delete(fn);
}

export function setAppPref(pref: AppPref) {
  kept(APP_KEY, pref === "system" ? null : pref);
  applyTheme();
  for (const fn of [...listeners]) fn();
}

export function setDrawPref(pref: DrawPref) {
  kept(DRAW_KEY, pref === "light" ? null : pref);
  for (const fn of [...listeners]) fn();
}

/** Apply the stored theme and follow the OS while it decides. */
export function startTheme() {
  applyTheme();
  system().addEventListener("change", () => {
    if (getAppPref() === "system" || getDrawPref() === "app") for (const fn of [...listeners]) fn();
  });
}

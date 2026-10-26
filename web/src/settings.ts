// Settings: a sheet from the top bar's cog, over the app like the editor. What it holds is
// kept on this device and applied at once (theme.ts); and Store health and Trash, screens of
// their own (health.ts, trash.ts), which the sheet closes to open.
import { kept } from "./api";
import { go } from "./app";
import {
  APP_KEY,
  type AppPref,
  appPref,
  changed,
  DRAW_KEY,
  type DrawPref,
  drawPref,
  getAppPref,
  getDrawPref,
  held,
  type Theme,
} from "./theme";
import { h } from "./ui";

// theme-color per theme: the page background of each (tokens.css --bg)
const CHROME: Record<Theme, string> = { light: "#f6f3ec", dark: "#161411" };

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

export function setAppPref(pref: AppPref) {
  held.app = pref;
  kept(APP_KEY, pref === "system" ? null : pref);
  applyTheme();
  changed();
}

export function setDrawPref(pref: DrawPref) {
  held.draw = pref;
  kept(DRAW_KEY, pref === "light" ? null : pref);
  changed();
}

/** A segmented radio group (the kind row's look) calling set with the chosen value. */
function choice(
  name: string,
  label: string,
  now: string,
  options: [value: string, label: string][],
  set: (value: string) => void,
) {
  return h(
    "div",
    {
      className: "chips",
      role: "radiogroup",
      "aria-label": label,
      onchange: (e: Event) => set((e.target as HTMLInputElement).value),
    },
    ...options.map(([value, text]) =>
      h("label", {}, h("input", { type: "radio", name, value, checked: value === now }), text),
    ),
  );
}

let open = false;

export function settings() {
  if (open) return;
  open = true;
  const opener = document.activeElement as HTMLElement | null;
  const behind = [...document.querySelectorAll<HTMLElement>("body > :is(header, main, nav)")];
  const done = h("button", { type: "button", className: "primary" }, "Done");
  let then = ""; // where to go once the sheet has closed
  // Store health and Trash are screens: the sheet closes (its history entry popped), then
  // the one chosen opens
  const screen = (path: string, name: string) => {
    const link = h("a", { href: path, className: "button" }, name);
    link.onclick = (e) => {
      if (e.button || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return; // a new tab
      e.preventDefault();
      then = path;
      history.back();
    };
    return link;
  };
  const form = h(
    "div",
    {
      className: "editor settings",
      role: "dialog",
      "aria-modal": "true",
      "aria-label": "Settings",
    },
    h("div", { className: "bar" }, h("h2", {}, "Settings"), done),
    h(
      "div",
      { className: "fields" },
      h("h3", { className: "label" }, "App theme"),
      choice(
        "theme",
        "App theme",
        getAppPref(),
        [
          ["system", "System"],
          ["light", "Light"],
          ["dark", "Dark"],
        ],
        (v) => setAppPref(appPref(v)),
      ),
      h("p", { className: "hint" }, "System follows the phone's light or dark setting."),
      h("h3", { className: "label" }, "Drawings theme"),
      choice(
        "drawings",
        "Drawings theme",
        getDrawPref(),
        [
          ["light", "Light"],
          ["dark", "Dark"],
          ["app", "Same as app"],
        ],
        (v) => setDrawPref(drawPref(v) as DrawPref),
      ),
      h(
        "p",
        { className: "hint" },
        "Light suits drawings that sit beside a photo of a whiteboard or paper.",
      ),
      h("h3", { className: "label" }, "Store"),
      screen("/health", "Store health"),
      h(
        "p",
        { className: "hint" },
        "Pages with no links or tags, stale todos, duplicates, dangling links and outdated write-ups.",
      ),
      screen("/trash", "Trash"),
      h("p", { className: "hint" }, "Deleted pages, when each goes for good, and Restore."),
    ),
  );
  const keys = (e: KeyboardEvent) => {
    if (e.key === "Escape") return void history.back();
    if (e.key !== "Tab") return;
    const stops = [...form.querySelectorAll<HTMLElement>("input:checked, button, a[href]")];
    const at = stops.indexOf(document.activeElement as HTMLElement);
    const next = e.shiftKey ? at <= 0 : at === stops.length - 1;
    if (next) {
      e.preventDefault();
      stops[e.shiftKey ? stops.length - 1 : 0].focus();
    }
  };
  const onpop = (e: PopStateEvent) => {
    e.stopImmediatePropagation();
    removeEventListener("popstate", onpop, true);
    removeEventListener("keydown", keys);
    form.remove();
    for (const el of behind) el.inert = false;
    open = false;
    if (then) go(then);
    else opener?.focus({ preventScroll: true });
  };
  done.onclick = () => history.back();
  for (const el of behind) el.inert = true;
  document.body.append(form);
  history.pushState({ settings: true }, "");
  addEventListener("popstate", onpop, true);
  addEventListener("keydown", keys);
  form.querySelector<HTMLElement>("input:checked")?.focus();
}

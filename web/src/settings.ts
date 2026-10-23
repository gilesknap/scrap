// Settings: a sheet from the top bar's cog, over the app like the editor. What it holds is
// kept on this device and applied at once (theme.ts).
import {
  appPref,
  type DrawPref,
  drawPref,
  getAppPref,
  getDrawPref,
  setAppPref,
  setDrawPref,
} from "./theme";
import { h } from "./ui";

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
    ),
  );
  const keys = (e: KeyboardEvent) => {
    if (e.key === "Escape") return void history.back();
    if (e.key !== "Tab") return;
    const stops = [...form.querySelectorAll<HTMLElement>("input:checked, button")];
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
    opener?.focus({ preventScroll: true });
  };
  done.onclick = () => history.back();
  for (const el of behind) el.inert = true;
  document.body.append(form);
  history.pushState({ settings: true }, "");
  addEventListener("popstate", onpop, true);
  addEventListener("keydown", keys);
  form.querySelector<HTMLElement>("input:checked")?.focus();
}

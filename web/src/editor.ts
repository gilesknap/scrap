// The full-screen editor shared by the composer and page Edit. It is a fixed layer sized to the
// visual viewport, which is the part of the screen left above the on-screen keyboard. Cancel,
// Preview and Save sit in its top row, and the text box fills the rest and scrolls inside
// itself. Nothing depends on the page scrolling or on sticky positioning, so it works whether
// the browser resizes the page for the keyboard or only pans it.
import { h, previewer, saveKey } from "./ui";

// --vv-top and --vv-h follow the visual viewport, at most once a frame.
const vv = window.visualViewport;
let queued = false;
function track() {
  queued = false;
  if (!vv) return;
  const root = document.documentElement.style;
  root.setProperty("--vv-top", `${vv.offsetTop}px`);
  root.setProperty("--vv-h", `${vv.height}px`);
}
const later = () => {
  if (!queued) queued = !!requestAnimationFrame(track);
};
vv?.addEventListener("resize", later);
vv?.addEventListener("scroll", later);

export interface Editor {
  form: HTMLFormElement;
  save: HTMLButtonElement;
  close: () => void;
}

export function editor(o: {
  text: HTMLTextAreaElement;
  before?: Node[];
  after?: Node[];
  onsave: () => void;
  oncancel?: () => void;
}): Editor {
  const preview = previewer(o.text);
  const save = h("button", { type: "submit", className: "primary" }, "Save");
  const behind = [...document.querySelectorAll<HTMLElement>("body > :is(header, main, nav)")];
  const opener = document.activeElement as HTMLElement | null;
  const close = () => {
    form.remove();
    for (const el of behind) el.inert = false;
    document.body.classList.remove("editing");
    removeEventListener("popstate", close);
    opener?.focus({ preventScroll: true });
  };
  const cancel = () => {
    close();
    o.oncancel?.();
  };
  const form = h(
    "form",
    {
      className: "editor",
      onkeydown: saveKey,
      onsubmit: (e: Event) => {
        e.preventDefault();
        o.onsave();
      },
    },
    h(
      "div",
      { className: "bar" },
      h("button", { type: "button", onclick: cancel }, "Cancel"),
      preview.button,
      save,
    ),
    h(
      "div",
      { className: "fields" },
      ...(o.before ?? []),
      o.text,
      preview.pane,
      ...(o.after ?? []),
    ),
  );
  track(); // right for the first frame
  for (const el of behind) el.inert = true;
  document.body.classList.add("editing");
  document.body.append(form);
  addEventListener("popstate", close); // the view is changing under it
  return { form, save, close };
}

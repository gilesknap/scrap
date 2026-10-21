// The full-screen editor shared by the composer and page Edit. It is a fixed layer sized to the
// visual viewport, which is the part of the screen left above the on-screen keyboard. Cancel,
// Preview and Save sit in its top row, and the text box fills the rest and scrolls inside
// itself. Nothing depends on the page scrolling or on sticky positioning, so it works whether
// the browser resizes the page for the keyboard or only pans it.
//
// Nothing typed is lost: it has a history entry, so the phone's Back closes the editor (not
// the app), and its fields are kept as a draft in IndexedDB as they change, so a Back, a
// reload or a killed app brings them back the next time it opens.
//
// It is a chunk of its own, with the composer (composer.ts): the service worker keeps it for
// offline use, but screens that never edit don't load it.
import { drafts } from "./db";
import { icon } from "./icons";
import { KINDS } from "./kinds";
import { h, previewer, saveKey, toast } from "./ui";

export { suggested, toSend } from "./kinds";
export { same, tagField } from "./tagedit";
export { todoField, todoStart } from "./todoedit";
export { confirmRemoval } from "./unembed";

const MAX_PAGE = 1_000_000; // bytes of UTF-8: a page's text at most (the server's store.MAX_PAGE)

/** Why text can't be saved as a page's (over 1 MB), said before sending it; else null. */
export function tooLong(text: string) {
  const n = new TextEncoder().encode(text).length;
  return n > MAX_PAGE
    ? `Not saved: the text is ${(n / 1e6).toFixed(2)} MB, and a page holds at most 1 MB`
    : null;
}

/** The kind control: a segmented radio group. suggest() picks a kind until the user picks
 * one (picked: they did, e.g. in a restored draft). */
export function kindPicker(initial: string, picked = false) {
  const set = (kind: string) => {
    for (const r of el.querySelectorAll("input")) r.checked = r.value === kind;
  };
  const el = h(
    "div",
    {
      className: "chips kinds",
      role: "radiogroup",
      "aria-label": "Kind",
      onchange: () => (picked = true),
    },
    ...KINDS.map(([value, label, name, glyph]) =>
      h(
        "label",
        { title: name },
        h("input", {
          type: "radio",
          name: "kind",
          value,
          checked: value === initial,
          "aria-label": name,
        }),
        icon(glyph),
        label,
      ),
    ),
  );
  return {
    el,
    value: () => el.querySelector<HTMLInputElement>("input:checked")?.value ?? initial,
    picked: () => picked,
    suggest: (kind: string) => picked || set(kind),
    reset: (kind: string) => {
      picked = false;
      set(kind);
    },
  };
}

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
  /** Keep the draft now (after a change that fires no input event, e.g. a photo). */
  keep: () => void;
  /** Saved (or discarded): drop the draft and close. */
  done: () => Promise<void>;
}

export function editor(o: {
  text: HTMLTextAreaElement;
  before?: Node[];
  after?: Node[];
  key: string; // what this is a draft of
  draft: () => object; // the fields, to keep
  dirty: () => boolean; // changed since opened
  restored: boolean; // the fields came from a draft
  ondiscard: () => void; // put the fields back as they were
  onsave: () => void;
}): Editor {
  o.text.dir = "auto"; // right-to-left text lays out as such
  const preview = previewer(o.text);
  const save = h("button", { type: "submit", className: "primary" }, "Save");
  const behind = [...document.querySelectorAll<HTMLElement>("body > :is(header, main, nav)")];
  const opener = document.activeElement as HTMLElement | null;
  let timer = 0;
  let finished = false; // saved or discarded: no more drafts
  const drop = () => drafts.del(o.key).catch(() => {});
  const keep = () => {
    clearTimeout(timer);
    if (finished) return;
    if (!o.dirty()) return void drop();
    // Storage full or refused: the editor itself still has it all
    drafts.put(o.key, { ...o.draft(), at: Date.now() }).catch(() => {});
  };

  let closing: (() => void) | null = null;
  const teardown = () => {
    removeEventListener("popstate", onpop, true);
    form.remove();
    for (const el of behind) el.inert = false;
    document.body.classList.remove("editing");
    opener?.focus({ preventScroll: true });
    closing?.();
  };
  // Closing pops the editor's history entry. The phone's Back pops it too: that keeps the
  // draft, and the page under the editor stays as it is.
  const onpop = (e: PopStateEvent) => {
    e.stopImmediatePropagation();
    const kept = !closing && o.dirty();
    if (!closing) keep();
    teardown();
    if (kept) toast("Kept as a draft: open it again to carry on"); // placed for the page under it
  };
  const done = () =>
    new Promise<void>((ok) => {
      finished = true;
      clearTimeout(timer);
      closing = ok;
      void drop();
      history.back();
      setTimeout(() => form.isConnected && teardown(), 1000); // in case no popstate comes
    });
  const cancel = () => {
    if (!o.dirty() || confirm("Discard your changes?")) void done();
  };

  const hint = o.restored
    ? h(
        "p",
        { className: "restored" },
        "Restored your unsaved draft. ",
        h(
          "button",
          {
            type: "button",
            className: "link",
            onclick: () => {
              void drop();
              o.ondiscard();
              hint?.remove();
            },
          },
          "Discard it",
        ),
      )
    : null;
  const form = h(
    "form",
    {
      className: "editor",
      onkeydown: saveKey,
      oninput: () => {
        clearTimeout(timer);
        timer = window.setTimeout(keep, 400);
      },
      onsubmit: (e: Event) => {
        e.preventDefault();
        o.onsave();
      },
    },
    h(
      "div",
      { className: "bar" },
      h("button", { type: "button", className: "ghost", onclick: cancel }, "Cancel"),
      preview.button,
      save,
    ),
    h(
      "div",
      { className: "fields" },
      hint,
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
  history.pushState({ editor: true }, "");
  addEventListener("popstate", onpop, true);
  keep(); // e.g. photos just picked
  return { form, save, keep, done };
}

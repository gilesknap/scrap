// The full-screen editor shared by the composer and page Edit. It is a fixed layer sized to the
// visual viewport, which is the part of the screen left above the on-screen keyboard. Cancel,
// Preview and Save sit in its top row, and the text box fills the rest and scrolls inside
// itself. Nothing depends on the page scrolling or on sticky positioning, so it works whether
// the browser resizes the page for the keyboard or only pans it.
//
// Nothing typed is lost: it has a history entry, so the phone's Back closes the editor (not
// the app), and its fields are kept as a draft in IndexedDB as they change, so a Back, a
// reload or a killed app brings them back the next time it opens.
import { drafts } from "./db";
import { h, previewer, saveKey, toast } from "./ui";

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
    if (!closing) {
      keep();
      if (o.dirty()) toast("Kept as a draft: open it again to carry on");
    }
    teardown();
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
      h("button", { type: "button", onclick: cancel }, "Cancel"),
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

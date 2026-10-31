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
import { previewUrl } from "./api";
import { drafts } from "./db";
import { type Embed, expand, found, tokenise } from "./embeds";
import { type Icon, icon } from "./icons";
import { KINDS } from "./kinds";
import {
  bullet,
  type Change,
  checkbox,
  edit,
  inCode,
  indent,
  lists,
  numbered,
  outdent,
} from "./listedit";
import { NOT_KEPT, stash } from "./stash";
import { blobImg, h, previewer, saveKey, toast } from "./ui";

export { suggested, tidy, toSend } from "./kinds";
export { mergeTags, same, tagField } from "./tagedit";
export { todoField, todoStart } from "./todoedit";
export { confirmRemoval } from "./unembed";

/** A rarely changed part of the editor (tags, a todo's dates) folded into one line that
 * says what it holds ("Tags 3 · #work #garden…"); tapped, it opens in place, tapped again it
 * folds. The text stays the screen's hero. A native <details>, so it is a button to
 * assistive tech and the keyboard; what it says follows every change made inside it. */
export function fold(name: string, body: HTMLElement, says: () => string, glyph: Icon) {
  const what = h("span", { className: "says", dir: "auto" });
  const refresh = () => {
    what.textContent = says();
  };
  const el = h(
    "details",
    { className: "fold" },
    h("summary", {}, icon(glyph), h("b", {}, name), what),
    body,
  );
  for (const type of ["input", "change", "click"]) body.addEventListener(type, refresh);
  // Opened, nothing takes focus: no keyboard until a field is tapped (the chips come first)
  el.addEventListener("toggle", refresh);
  refresh();
  return { el, refresh };
}

/** What a tags fold says: how many, then them ("3 · #a #b #c"), or that there are none. */
export const tagsSay = (tags: string[]) =>
  tags.length ? `${tags.length} · ${tags.map((t) => `#${t}`).join(" ")}` : "none";

/** What a todo's fold (Due) says: "24 Oct · high", or none. */
export function todoSays(v: { due: string | null; priority: string | null }) {
  const day =
    v.due &&
    new Date(`${v.due}T12:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  return [day, v.priority].filter(Boolean).join(" · ") || "none";
}

/** The editor keys' icons, drawn here (not in the shell's icons): a task's empty box, a
 * bulleted and a numbered list, and lines moved in and out. */
const KEY_ICONS = {
  task: '<rect x="4.5" y="4.5" width="15" height="15" rx="3"/>',
  bullet:
    '<circle cx="5" cy="6.5" r="1.2"/><circle cx="5" cy="12" r="1.2"/><circle cx="5" cy="17.5" r="1.2"/><path d="M9.5 6.5h10m-10 5.5h10m-10 5.5h10"/>',
  numbered: '<path d="M4 4.5h1.5V9M4 9h3M4 14.5h3l-3 4h3M10.5 6.5h9m-9 5.5h9m-9 5.5h9"/>',
  indent: '<path d="M4 5h16M11 10h9m-9 4h9M4 19h16M4 9.5l3 2.5-3 2.5"/>',
  outdent: '<path d="M4 5h16M11 10h9m-9 4h9M4 19h16M7 9.5 4 12l3 2.5"/>',
};
const keyIcon = (name: keyof typeof KEY_ICONS) => {
  const t = document.createElement("template");
  t.innerHTML = `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${KEY_ICONS[name]}</svg>`;
  return t.content.firstChild as SVGSVGElement;
};

/** The editor's keys, above the keyboard: [icon, label, aria-label, the change, whether it
 * applies in a code block (only Indent and Outdent: spaces)]. */
type Key = [
  keyof typeof KEY_ICONS,
  string,
  string,
  (text: string, start: number, end: number) => Change,
  boolean,
];
const KEYS: Key[] = [
  ["task", "Task", "Task: make the line a task", checkbox, false],
  ["bullet", "Bullet", "Bullet: make the line a bullet", bullet, false],
  ["numbered", "Number", "Number: make the line a numbered item", numbered, false],
  ["indent", "Indent", "Indent the line", indent, true],
  ["outdent", "Outdent", "Outdent the line", outdent, true],
];

/** The text box's embeds of stored files as tokens (embeds.ts), with a chip each in a row
 * (chips: the editor's foot, under its fields): a thumbnail and its name; tapped, its token is
 * selected (to cut and paste elsewhere), and its ✕ takes the token out. value() is the text as Markdown, the embeds put back: read the
 * text through it, never text.value. add(): one more, a file still on the phone (the
 * composer's, pending.ts), its thumbnail its own bytes; list(): them all. */
export function embedded(text: HTMLTextAreaElement) {
  // Each chip's thumbnail made once (a phone's photo is big to draw on every keystroke). A
  // preview that won't come (not a photo the server can draw, offline): the file icon
  const thumbs = new Map<Embed, Element>();
  const make = (e: Embed, keep: boolean) => {
    const img = e.blob ? blobImg(e.blob) : h("img", { src: previewUrl(e.sha, 480), alt: "" });
    img.onerror = () => {
      if (e.blob) URL.revokeObjectURL(img.src); // as blobImg's own, which this replaces
      const file = icon("file");
      if (keep) thumbs.set(e, file); // the icon from now on, not the broken image again
      img.replaceWith(file);
    };
    return img;
  };
  // drawn: those with a chip already in this pass; a token twice gets a second picture (one
  // element can't be in two chips), or a copy of its icon
  const thumb = (e: Embed, drawn: Set<Embed>) => {
    let el = thumbs.get(e);
    if (drawn.has(e))
      return el && !(el instanceof HTMLImageElement) ? el.cloneNode(true) : make(e, false);
    drawn.add(e);
    if (!el) {
      el = make(e, true);
      thumbs.set(e, el);
    }
    return el;
  };
  let embeds: Embed[] = [];
  // A tap keeps the keyboard as it is, as the editor's keys do
  const chips = h("div", { className: "embeds", onpointerdown: (e: Event) => e.preventDefault() });
  const show = () => {
    const drawn = new Set<Embed>();
    chips.replaceChildren(
      ...found(text.value, embeds).map(({ embed: e, at }) => {
        const what = `${e.image ? "image" : "file"} ${e.n}`;
        const span = { from: at, to: at + e.token.length };
        const pick = () => {
          text.focus();
          text.setSelectionRange(span.from, span.to);
        };
        const remove = () => {
          // A token on a line of its own takes its line with it
          const v = text.value;
          let { from, to } = span;
          if ((from === 0 || v[from - 1] === "\n") && (to === v.length || v[to] === "\n")) {
            if (to < v.length) to++;
            else if (from > 0) from--;
          }
          text.focus();
          edit(text, { from, to, insert: "", start: from, end: from });
        };
        return h(
          "span",
          { className: "embed" },
          h(
            "button",
            { type: "button", className: "pick", title: e.token, onclick: pick },
            e.image ? thumb(e, drawn) : icon("file"),
            h("span", { dir: "auto" }, e.label),
          ),
          h(
            "button",
            { type: "button", className: "ghost", "aria-label": `Remove ${what}`, onclick: remove },
            icon("close"),
          ),
        );
      }),
    );
  };
  const set = (body: string) => {
    ({ text: text.value, embeds } = tokenise(body));
    show();
  };
  text.addEventListener("input", show);
  set(text.value);
  return {
    chips,
    value: () => expand(text.value, embeds),
    set,
    add: (e: Embed) => embeds.push(e),
    list: () => embeds,
    show,
  };
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
  read?: () => string; // the text as Markdown (embedded()'s value), if not the box's own
  before?: Node[];
  after?: Node[];
  foot?: Node; // under the fields, above the keys: always in sight, however long the text
  key: string; // what this is a draft of
  draft: () => object; // the fields, to keep
  dirty: () => boolean; // changed since opened
  restored: boolean; // the fields came from a draft
  left?: () => void; // left by Back with changes (kept as the draft): say so, if not as here
  ondiscard: () => void; // put the fields back as they were
  onsave: () => void;
  onclose?: (left: boolean) => void; // closed, however (Back, Save, Cancel); left: left() is next
}): Editor {
  o.text.dir = "auto"; // right-to-left text lays out as such
  lists(o.text); // Enter continues a list (listedit.ts)
  const preview = previewer(o.text, o.read);
  // Just above the keyboard (the layer is the visual viewport's height): the keys that make
  // the line (or the lines selected) a task, a bullet or a numbered item, or indent or outdent
  // it. In a code block the list keys do nothing. A tap keeps the keyboard up.
  const keys = h(
    "div",
    { className: "keys", onpointerdown: (e: Event) => e.preventDefault() },
    ...KEYS.map(([glyph, label, name, change, code]) =>
      h(
        "button",
        {
          type: "button",
          className: "ghost",
          "aria-label": name,
          onclick: () => {
            const t = o.text;
            t.focus();
            if (!code && inCode(t.value, t.selectionStart)) return;
            edit(t, change(t.value, t.selectionStart, t.selectionEnd));
          },
        },
        keyIcon(glyph),
        h("span", {}, label),
      ),
    ),
  );
  const save = h("button", { type: "submit", className: "primary" }, "Save");
  const behind = [...document.querySelectorAll<HTMLElement>("body > :is(header, main, nav)")];
  const opener = document.activeElement as HTMLElement | null;
  let timer = 0;
  let finished = false; // saved or discarded: no more drafts
  const drop = () => drafts.del(o.key).catch(() => {});
  let warned = false; // the last save was refused and said so: not again until one works
  /** Keep the draft now; whether it is safe (kept, or nothing to keep). Storage that is full
   * or refuses it is said once, not on every keystroke: the editor itself still has it all. */
  const keep = async (): Promise<boolean> => {
    clearTimeout(timer);
    if (finished) return true;
    if (!o.dirty()) {
      drop();
      return true;
    }
    const ok = await stash(o.key, { ...o.draft(), at: Date.now() });
    if (ok) warned = false;
    else if (!warned) {
      warned = true;
      toast(NOT_KEPT, "", undefined, 10000);
    }
    return ok;
  };

  // Hidden or closed by the system: the last moments of typing are kept now, not after the
  // 0.4 s pause (the app may be killed before it)
  const flush = () => void keep();
  const onhide = () => document.visibilityState === "hidden" && flush();

  let closing: (() => void) | null = null;
  const teardown = (left = false) => {
    removeEventListener("popstate", onpop, true);
    removeEventListener("pagehide", flush);
    document.removeEventListener("visibilitychange", onhide);
    form.remove();
    for (const el of behind) el.inert = false;
    document.body.classList.remove("editing");
    opener?.focus({ preventScroll: true });
    // Its draft may have changed (kept, dropped): e.g. Capture's draft row draws it again
    document.dispatchEvent(new Event("draftchange"));
    closing?.();
    o.onclose?.(left);
  };
  // Closing pops the editor's history entry. The phone's Back pops it too: that keeps the
  // draft, and the page under the editor stays as it is.
  // If storage refuses the draft, Back must not discard it silently: the editor stays open
  // (its history entry put back) with the refusal said; Cancel is the way to discard.
  const onpop = async (e: PopStateEvent) => {
    e.stopImmediatePropagation();
    const kept = !closing && o.dirty();
    if (kept) {
      warned = false; // say it again for this Back, though a typing save said it
      if (!(await keep())) return void history.pushState({ editor: true }, "");
    } else if (!closing) void keep();
    teardown(kept);
    if (kept) (o.left ?? (() => toast("Kept as a draft")))(); // placed for the page under it
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
        timer = window.setTimeout(() => void keep(), 400);
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
    o.foot ?? "",
    keys,
  );
  track(); // right for the first frame
  for (const el of behind) el.inert = true;
  document.body.classList.add("editing");
  document.body.append(form);
  history.pushState({ editor: true }, "");
  addEventListener("popstate", onpop, true);
  addEventListener("pagehide", flush);
  document.addEventListener("visibilitychange", onhide);
  void keep(); // e.g. photos just picked
  return { form, save, keep: () => void keep(), done };
}

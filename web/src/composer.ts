// The composer: a new capture's text, photos, kind and tags, in the editor. A chunk of its own with
// the editor (loaded when it opens; the service worker keeps it for offline use).
import { uploadLimit } from "./api";
import { queue } from "./app";
import { picker } from "./capture";
import { drafts } from "./db";
import { editor, kindPicker, suggested, tagField, toSend } from "./editor";
import { icon } from "./icons";
import { type Capture, split } from "./queue";
import { blobImg, clearToasts, h, toast } from "./ui";

const DRAFT = "new"; // the composer's draft
interface Draft {
  text: string;
  kind?: string;
  picked?: boolean; // the user chose the kind
  hint?: string; // the kind, in drafts of older builds ("": Note)
  tags?: string[];
  files: File[]; // IndexedDB keeps them, so photos survive a killed app too
}

/** as: a kind chosen before it opens (the Todos screen's New todo), over a draft's. */
export async function compose(picked: File[], as?: string) {
  // An unsaved draft comes back, with any photos just picked added to it.
  const kept = await drafts.get<Draft>(DRAFT).catch(() => undefined);
  const files = [...(kept?.files ?? []), ...picked];
  const text = h("textarea", { rows: 5, value: kept?.text ?? "" });
  // The kind: Note unless chosen (a bare URL suggests Read). Photos have none: ingest
  // decides, and the page's editor can change it.
  const kind = kindPicker(
    as ?? kept?.kind ?? (kept?.hint || "note"),
    !!as || (kept?.picked ?? !!kept?.hint),
  );
  text.addEventListener("input", () => kind.suggest(suggested(text.value)));
  // Its tags, as the page's editor has them; photos too (Claude then adds none of its own)
  const tags = tagField(kept?.tags ?? [], () => ed.keep());
  const thumbs = h("div", { className: "thumbs" });
  // One capture, many photos: add from the camera (one at a time) or the gallery.
  const add = (more: File[]) => {
    files.push(...more);
    showThumbs();
    ed.keep();
  };
  const showThumbs = () => {
    kind.el.hidden = files.length > 0;
    text.placeholder = files.length ? "Caption (optional)" : "Note or link";
    thumbs.replaceChildren(
      ...files.map((f, i) =>
        h(
          "span",
          { className: "thumb" },
          blobImg(f, f.name),
          h(
            "button",
            {
              type: "button",
              "aria-label": `Remove photo ${i + 1}`,
              onclick: () => {
                files.splice(i, 1);
                showThumbs();
                ed.keep();
              },
            },
            icon("close"),
          ),
        ),
      ),
    );
  };
  const adders = h(
    "div",
    { className: "bar" },
    picker("Camera", true, add, "add"),
    picker("Gallery", false, add, "add"),
  );
  showThumbs();
  const ed = editor({
    text,
    before: [kind.el],
    after: [tags.el, thumbs, adders],
    key: DRAFT,
    draft: (): Draft => ({
      text: text.value,
      kind: kind.value(),
      picked: kind.picked(),
      tags: tags.value(),
      files,
    }),
    dirty: () => !!text.value.trim() || files.length > 0 || tags.value().length > 0,
    restored: !!kept,
    ondiscard: () => {
      text.value = "";
      files.length = 0;
      kind.reset("note");
      tags.reset([]);
      showThumbs();
    },
    onsave: () => void store(false),
  });
  const { save } = ed;
  const close = async () => {
    clearToasts(); // e.g. a "Save separately" offer for this composer
    await ed.done();
  };
  const mb = (n: number) => `${(n / 2 ** 20).toFixed(1)} MB`;
  const store = async (separately: boolean) => {
    const body = text.value.trim();
    if (!body && !files.length) return text.focus();
    const tagged = tags.value();
    const capture: Capture = {
      text: body || undefined,
      kind: files.length ? undefined : toSend(kind.value(), kind.picked(), "note"),
      tags: tagged.length ? tagged : undefined,
      source: "pwa",
      files: files.map((f) => ({ name: f.name, blob: f })),
    };
    // Check the server's limit now: a capture it refuses could only be split or discarded.
    const size = files.reduce((n, f) => n + f.size, 0);
    const max = uploadLimit();
    if (max && size > max - 64 * 1024 && !separately) {
      const over = `${mb(size)} of photos is over the server's ${mb(max)} limit.`;
      if (files.length < 2)
        return toast(`${over} Remove it to save the text.`, "", undefined, 10000);
      return toast(`${over} Remove some, or`, "Save separately", () => void store(true), 15000);
    }
    save.disabled = true;
    try {
      await queue.addAll(separately ? split(capture) : [capture]);
    } catch (err) {
      save.disabled = false; // keep everything in the composer to try again
      return toast(
        `Not saved: the phone refused to store it (${(err as Error).name}). Free some space and try again.`,
        "",
        undefined,
        10000,
      );
    }
    await close();
    toast(navigator.onLine ? "Saved" : "Saved on the phone: uploads when online");
  };
  if (!files.length) text.focus();
}

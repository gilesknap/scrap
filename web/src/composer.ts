// The composer: a new capture's text, photos and kind, in the editor. A chunk of its own with
// the editor (loaded when it opens; the service worker keeps it for offline use).
import { uploadLimit } from "./api";
import { queue } from "./app";
import { picker } from "./capture";
import { drafts } from "./db";
import { BARE_URL, editor, kindPicker } from "./editor";
import { icon } from "./icons";
import { type Capture, type Kind, split } from "./queue";
import { blobImg, clearToasts, h, toast } from "./ui";

const DRAFT = "new"; // the composer's draft
interface Draft {
  text: string;
  kind?: string;
  hint?: string; // the kind, in drafts of older builds
  files: File[]; // IndexedDB keeps them, so photos survive a killed app too
}

export async function compose(picked: File[]) {
  // An unsaved draft comes back, with any photos just picked added to it.
  const kept = await drafts.get<Draft>(DRAFT).catch(() => undefined);
  const files = [...(kept?.files ?? []), ...picked];
  const text = h("textarea", { rows: 5, value: kept?.text ?? "" });
  // The kind: Note unless chosen (a bare URL suggests Read). Photos have none: ingest
  // decides, and the page's editor can change it.
  const kind = kindPicker(kept?.kind ?? kept?.hint ?? "note", !!kept);
  text.addEventListener("input", () =>
    kind.suggest(BARE_URL.test(text.value.trim()) ? "consume" : "note"),
  );
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
    after: [thumbs, adders],
    key: DRAFT,
    draft: (): Draft => ({ text: text.value, kind: kind.value(), files }),
    dirty: () => !!text.value.trim() || files.length > 0,
    restored: !!kept,
    ondiscard: () => {
      text.value = "";
      files.length = 0;
      kind.reset("note");
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
    const capture: Capture = {
      text: body || undefined,
      kind: files.length || kind.value() === "note" ? undefined : (kind.value() as Kind),
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

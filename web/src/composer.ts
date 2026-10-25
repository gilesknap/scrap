// The composer: a new capture's text, photos, kind and tags, in the editor. A chunk of its own with
// the editor (loaded when it opens; the service worker keeps it for offline use).
import { overLimit, uploadLimit } from "./api";
import { queue } from "./app";
import { picker } from "./capture";
import { drafts } from "./db";
import {
  editor,
  fold,
  kindPicker,
  suggested,
  tagField,
  tagsSay,
  tidy,
  todoField,
  todoSays,
  toSend,
} from "./editor";
import { DRAFT, FRESH, promote, recover } from "./fresh";
import { icon } from "./icons";
import { embedBytes, tooLong } from "./pagecap";
import { type Capture, split } from "./queue";
import { tagProblem } from "./tagedit";
import { blobImg, clearToasts, h, toast } from "./ui";

export interface Draft {
  text: string;
  kind?: string;
  picked?: boolean; // the user chose the kind
  hint?: string; // the kind, in drafts of older builds ("": Note)
  tags?: string[];
  todo?: { due: string | null; priority: string | null }; // while the kind is Todo
  files: File[]; // IndexedDB keeps them, so photos survive a killed app too
}

/** What the text box asks for, by kind. */
const ASK: Record<string, string> = { todo: "What needs doing?", consume: "Link or title" };

/** as: a kind chosen before it opens (the Todos screen's New todo). resume: open the kept
 * draft (Capture's draft row); otherwise a fresh capture (the tiles, New todo). */
export async function compose(picked: File[], as?: string, resume = false) {
  // A fresh capture left behind by a killed app first becomes the kept draft (fresh.ts)
  await recover();
  // The kept draft comes back only when asked for: a tile always starts afresh.
  const stored = await drafts.get<Draft>(DRAFT).catch(() => undefined);
  const kept = resume ? stored : undefined;
  // A fresh one beside a kept draft is saved under a key of its own, and takes the kept one's
  // place only if left by Back with something in it (Undo puts the older one back)
  const hold = !resume && !!stored;
  const files = [...(kept?.files ?? []), ...picked];
  const text = h("textarea", { rows: 5, value: kept?.text ?? "" });
  // The kind: Note unless chosen (a bare URL suggests Later). Photos have none: ingest
  // decides, and the page's editor can change it.
  const kind = kindPicker(
    as ?? kept?.kind ?? (kept?.hint || "note"),
    !!as || (kept?.picked ?? !!kept?.hint),
  );
  text.addEventListener("input", () => {
    kind.suggest(suggested(text.value));
    showTodo(); // a suggested kind (a link: Later) asks for it in its own words
  });
  // Its tags, as the page's editor has them; photos too (Claude's join them on its first reading)
  const tags = tagField(kept?.tags ?? [], () => ed.keep());
  // A todo's due date (Today, Tomorrow, Next week or a date) and priority, as on its page:
  // shown while the kind is Todo (photos have no kind here, so none with them)
  const todo = todoField(kept?.todo?.due ?? null, kept?.todo?.priority ?? null);
  // Folded into a line each, under the text: the text stays the hero
  const tagLine = fold("Tags", tags.el, () => tagsSay(tags.value()), "tag");
  const todoLine = fold("Due", todo.el, () => todoSays(todo.value()), "due");
  const showTodo = () => {
    todoLine.el.hidden = kind.value() !== "todo" || files.length > 0;
    text.placeholder = files.length ? "Caption (optional)" : (ASK[kind.value()] ?? "Note or link");
  };
  kind.el.addEventListener("change", showTodo);
  const todoNow = () => (todoLine.el.hidden ? null : todo.value());
  const dated = () => !!todoNow()?.due || !!todoNow()?.priority;
  const thumbs = h("div", { className: "thumbs" });
  // One capture, many photos: add from the camera (one at a time) or the gallery.
  const add = (more: File[]) => {
    files.push(...more);
    showThumbs();
    ed.keep();
  };
  const showThumbs = () => {
    kind.el.hidden = files.length > 0;
    showTodo();
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
    // As in a page's editor: the kind, then its due date and tags, each folded to a line, then
    // the text; the photos and more under it
    before: [kind.el, todoLine.el, tagLine.el],
    after: [thumbs, adders],
    key: hold ? FRESH : DRAFT,
    draft: (): Draft => ({
      text: text.value,
      kind: kind.value(),
      picked: kind.picked(),
      tags: tags.value(),
      ...(dated() && { todo: todo.value() }),
      files,
    }),
    dirty: () => !!text.value.trim() || files.length > 0 || tags.value().length > 0 || dated(),
    restored: !!kept,
    left: () => {
      // Its row is on Capture: elsewhere (Todos), say where
      const where = location.pathname === "/" ? "" : ": it's on Capture";
      if (!hold) return toast(`Kept as a draft${where}`);
      void promote((older) =>
        older ? `Kept as a draft, in place of the older one${where}` : `Kept as a draft${where}`,
      );
    },
    ondiscard: () => {
      text.value = "";
      files.length = 0;
      kind.reset("note");
      tags.reset([]);
      todo.reset(null, null);
      showThumbs();
      tagLine.refresh();
      todoLine.refresh();
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
    const body = tidy(text.value);
    if (!body && !files.length) return text.focus();
    const long = tooLong(body, embedBytes(files));
    if (long) return toast(long, "", undefined, 8000); // kept in the composer to shorten
    const tagged = tags.value();
    // The server's tag limits too: a capture it refuses would sit in the queue, unfixable.
    const bad = tagProblem(tagged);
    if (bad) return toast(`${bad} Fix the tags to save.`, "", undefined, 10000);
    const capture: Capture = {
      text: body || undefined,
      kind: files.length ? undefined : toSend(kind.value(), kind.picked(), "note"),
      tags: tagged.length ? tagged : undefined,
      due: todoNow()?.due ?? undefined,
      priority: todoNow()?.priority ?? undefined,
      source: "pwa",
      files: files.map((f) => ({ name: f.name, blob: f })),
    };
    // Check the server's limit now: a capture it refuses could only be split or discarded.
    const size = files.reduce((n, f) => n + f.size, 0);
    const max = uploadLimit();
    if (overLimit(size) && !separately) {
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
    // Offline, Capture's waiting row says it; elsewhere (Todos) only this does
    if (navigator.onLine) toast("Saved");
    else if (location.pathname !== "/") toast("Saved on the phone: uploads when online");
  };
  if (!files.length) text.focus();
}

// The composer: a new capture's text, photos, kind and tags, in the editor. A chunk of its own with
// the editor (loaded when it opens; the service worker keeps it for offline use). Its photos and
// files are tokens in the text with a chip each, as the page editor's embeds are (pending.ts).
import { overLimit, uploadLimit } from "./api";
import { queue } from "./app";
import { FILES, picker } from "./capture";
import { drafts } from "./db";
import {
  editor,
  embedded,
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
import { embedBytes, tooLong } from "./pagecap";
import { pend, placeAt, placed, wire } from "./pending";
import type { Capture } from "./queue";
import { refused } from "./refused";
import { split } from "./split";
import { tagProblem } from "./tagedit";
import { clearToasts, h, toast } from "./ui";

export interface Draft {
  text: string;
  kind?: string;
  picked?: boolean; // the user chose the kind
  hint?: string; // the kind, in drafts of older builds ("": Note)
  tags?: string[];
  todo?: { due: string | null; priority: string | null }; // while the kind is Todo
  files: File[]; // IndexedDB keeps them, so photos survive a killed app too
  tokens?: string[]; // each file's token in text (#403); none in older builds' drafts
}

/** What the text box asks for, by kind. */
const ASK: Record<string, string> = {
  todo: "What needs doing?",
  consume: "Link or title",
  whiteboard: "What the board is about",
  document: "What the document is",
};

/** as: a kind chosen before it opens (the Todos screen's New todo, or a search's New for its
 * kind). resume: open the kept draft (Capture's draft row); otherwise a fresh capture (the
 * tiles, New todo). given: tags filled in to start with (a search's New, for its tags). */
export async function compose(picked: File[], as?: string, resume = false, given: string[] = []) {
  // A fresh capture left behind by a killed app first becomes the kept draft (fresh.ts)
  await recover();
  // The kept draft comes back only when asked for: a tile always starts afresh.
  const stored = await drafts.get<Draft>(DRAFT).catch(() => undefined);
  const kept = resume ? stored : undefined;
  // A fresh one beside a kept draft is saved under a key of its own, and takes the kept one's
  // place only if left by Back with something in it (Undo puts the older one back)
  const hold = !resume && !!stored;
  const text = h("textarea", { rows: 5, value: kept?.text ?? "" });
  // Its photos and files: a token each in the text, with a chip under it (pending.ts)
  const em = embedded(text);
  const pending = () => em.list().filter((e) => e.blob);
  const inText = () => placed(text.value, pending()); // those still in the text
  // The kind: Note unless chosen (a bare URL suggests Later); with photos too, as the page's
  // editor has it (left as Note, ingest decides from the first photo).
  const kind = kindPicker(
    as ?? kept?.kind ?? (kept?.hint || "note"),
    !!as || (kept?.picked ?? !!kept?.hint),
  );
  text.addEventListener("input", () => {
    kind.suggest(suggested(text.value));
    showTodo(); // a suggested kind (a link: Later) asks for it in its own words
  });
  // Its tags, as the page's editor has them; photos too (Claude's join them on its first reading)
  const start = kept?.tags ?? given;
  const tags = tagField(start, () => ed.keep());
  // A todo's due date (Today, Tomorrow, Next week or a date) and priority, as on its page:
  // shown while the kind is Todo
  const todo = todoField(kept?.todo?.due ?? null, kept?.todo?.priority ?? null);
  // Folded into a line each, under the text: the text stays the hero
  const tagLine = fold("Tags", tags.el, () => tagsSay(tags.value()), "tag");
  const todoLine = fold("Due", todo.el, () => todoSays(todo.value()), "due");
  const showTodo = () => {
    todoLine.el.hidden = kind.value() !== "todo";
    text.placeholder = ASK[kind.value()] ?? "Note or link";
  };
  kind.el.addEventListener("change", showTodo);
  showTodo();
  const todoNow = () => (todoLine.el.hidden ? null : todo.value());
  const dated = () => !!todoNow()?.due || !!todoNow()?.priority;
  // One capture, many photos (or files): from the camera (one at a time), the gallery or File,
  // each a token where the caret is, a paragraph of its own
  const add = (more: File[], at = text.selectionStart, to = text.selectionEnd) => {
    const tokens = more.map((f) => {
      const e = pend(f, em.list(), text.value);
      em.add(e);
      return e.token;
    });
    const c = placeAt(text.value, at, to, tokens);
    text.setRangeText(c.insert, c.from, c.to);
    text.setSelectionRange(c.start, c.end);
    text.dispatchEvent(new Event("input", { bubbles: true })); // its chips, and the draft kept
  };
  const adders = h(
    "div",
    { className: "bar" },
    picker("Camera", true, add, "add"),
    picker("Gallery", false, add, "add"),
    picker("File", false, add, "add", FILES),
  );
  // A draft's: each file with its token; one with none in the text (an older build's draft,
  // a caption and photos) gets one at the end, as the server would have put it
  const lost: File[] = [];
  kept?.files.forEach((f, i) => {
    const token = kept.tokens?.[i];
    if (token && text.value.includes(token)) em.add(pend(f, [], "", token));
    else lost.push(f);
  });
  const end = text.value.length;
  if (lost.length || picked.length) add([...lost, ...picked], end, end);
  em.show();
  const ed = editor({
    text,
    // As in a page's editor: the kind, then its due date and tags, each folded to a line, then
    // the text; Camera, Gallery and File under it, and the photos' and files' chips in sight
    read: em.value,
    before: [kind.el, todoLine.el, tagLine.el],
    after: [adders],
    foot: em.chips,
    key: hold ? FRESH : DRAFT,
    draft: (): Draft => ({
      text: em.value(),
      kind: kind.value(),
      picked: kind.picked(),
      tags: tags.value(),
      ...(dated() && { todo: todo.value() }),
      files: inText().map((e) => e.blob as File),
      tokens: inText().map((e) => e.token),
    }),
    // (the tags it opened with are no change: a search's New, closed at once, keeps nothing)
    dirty: () =>
      !!text.value.trim() || tags.value().join("\n") !== (kept ? "" : given.join("\n")) || dated(),
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
      em.set("");
      kind.reset("note");
      tags.reset([]);
      todo.reset(null, null);
      showTodo();
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
    // Each file's token as the server reads it, and the files in their tokens' order
    const { text: body, files } = wire(tidy(em.value()), pending());
    if (!body) return text.focus();
    const long = tooLong(body, embedBytes(files));
    if (long) return toast(long, "", undefined, 8000); // kept in the composer to shorten
    const tagged = tags.value();
    // The server's tag limits too: a capture it refuses would sit in the queue, unfixable.
    const bad = tagProblem(tagged);
    if (bad) return toast(`${bad} Fix the tags to save.`, "", undefined, 10000);
    const capture: Capture = {
      text: body || undefined,
      kind: toSend(kind.value(), kind.picked(), "note"),
      tags: tagged.length ? tagged : undefined,
      due: todoNow()?.due ?? undefined,
      priority: todoNow()?.priority ?? undefined,
      source: "pwa",
      files: files.map((f) => ({ name: f.name, blob: f })),
      ...(files.length && { place: "1" as const }), // its tokens are its files' places (#403)
    };
    // Check the server's limit now: a capture it refuses could only be split or discarded.
    const size = files.reduce((n, f) => n + f.size, 0);
    const max = uploadLimit();
    if (overLimit(size) && !separately) {
      const over = `${mb(size)} of files is over the server's ${mb(max)} limit.`;
      if (files.length < 2)
        return toast(`${over} Remove it to save the text.`, "", undefined, 10000);
      return toast(`${over} Remove some, or`, "Save separately", () => void store(true), 15000);
    }
    save.disabled = true;
    let ids: string[];
    try {
      ids = (await queue.addAll(separately ? split(capture) : [capture])).map((i) => i.id);
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
    if (navigator.onLine) {
      toast("Saved");
      refused(ids);
    } else if (location.pathname !== "/") toast("Saved on the phone: uploads when online");
  };
  if (!pending().length) text.focus();
}

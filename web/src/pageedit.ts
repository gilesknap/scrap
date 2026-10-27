// A page in the editor (page.ts's Edit): its text, title, kind, tags and a todo's due date
// and priority, with the draft kept on the phone, and a conflict shown if it changed
// elsewhere meanwhile. A chunk of its own with editor.ts, kept offline (vite.config.ts).
import { adopt, photoAdder, takesPhotos } from "./addphoto";
import { ADDED, ApiError, api, type Page } from "./api";
import { drafts } from "./db";
import {
  confirmRemoval,
  editor,
  embedded,
  fold,
  kindPicker,
  mergeTags,
  same,
  suggested,
  tagField,
  tagsSay,
  todoField,
  todoSays,
  todoStart,
  toSend,
} from "./editor";
import { laterField, mediaFields, mediaNow, mediaSays } from "./lateredit";
import { tooLong } from "./pagecap";
import { reading, toLine } from "./readat";
import { textPart } from "./textpart";
import { h, toast } from "./ui";

interface Draft {
  title: string;
  text: string;
  kind?: string;
  picked?: boolean; // the user chose the kind
  tags?: string[];
  tagsFrom?: string[]; // the page's tags when it was made: changed elsewhere since, they stay
  todo?: { due: string | null; priority: string | null }; // a todo's, if changed
  media?: string; // a Later page's type, if changed
  base: number; // the revision it was made on
}
const JSON_TYPE = { "Content-Type": "application/json" };

export async function edit(
  p: Page,
  load: (p: Page) => Promise<void>,
  show: (p: Page) => void,
  row = false, // from a list's row: no view read
) {
  // An unsaved edit comes back, on the revision it was made on: if the page has changed
  // since, saving it shows the conflict rather than overwriting.
  const key = `page:${p.id}`;
  const lines = p.body.split("\n").length;
  const read = row ? null : reading(lines); // taken now, while the view is as it was left
  const kept = await drafts.get<Draft>(key).catch(() => undefined);
  // Its kind. A note nobody filed yet gets one suggested from its text (a link alone: Later),
  // as in the composer, until the user picks one; a draft's kind only if the user picked it
  const unfiled = !p.kind_fixed && p.kind === "note"; // store/roles.py UNFILED
  const was = unfiled ? suggested(p.body) : p.kind;
  const initial = unfiled ? suggested(kept?.text ?? p.body) : p.kind;
  const kind = kindPicker(kept?.picked ? (kept.kind ?? initial) : initial, !!kept?.picked);
  let base = kept?.base ?? p.rev;
  let over = p.body; // the text a save replaces: its deleted embeds are warned about
  // The page's revision and text as opened: Add photo moves them on (adopted, below)
  const at = { rev: p.rev, body: p.body };
  const title = h("input", { value: kept?.title ?? p.title, "aria-label": "Title", dir: "auto" });
  const text = h("textarea", { value: kept?.text ?? p.body, rows: 8, "aria-label": "Body" });
  // Its images and files as short tokens, with a chip each under it: body() is the Markdown
  const embeds = embedded(text);
  const body = embeds.value;
  if (unfiled) text.addEventListener("input", () => kind.suggest(suggested(body())));
  // Tags: a draft's only if they were changed in it (not, say, tags Claude or another
  // device set since); and sent only if changed from those it started from
  // changed there, they are merged onto the page's now: tags set elsewhere kept, its adds
  // and removals applied
  const ours = kept?.tags && !same(kept.tags, kept.tagsFrom ?? p.tags) ? kept : null;
  let tagsFrom = p.tags;
  const tags = tagField(
    ours?.tags ? mergeTags(p.tags, ours.tagsFrom ?? p.tags, ours.tags) : p.tags,
    () => ed.keep(),
    p.model_tags,
  );
  const retagged = () => !same(tags.value(), tagsFrom);
  // A todo's due date and priority: shown while the kind is Todo, sent if changed
  const start = todoStart(kept, p); // a draft's, cleared ones too, else the page's
  const todo = todoField(start.due, start.priority);
  const todoNow = () => (kind.value() === "todo" ? todo.value() : null);
  const redated = () => {
    const t = todoNow();
    return !!t && (t.due !== (p.due ?? null) || t.priority !== (p.priority ?? null));
  };
  // A Later page's type (Book, Film ...): shown while the kind is Later, sent if changed
  const mediaWas = mediaNow(p.fields);
  const later = laterField(kept?.media ?? mediaWas);
  const retyped = () => kind.value() === "consume" && later.value() !== mediaWas;
  // Folded into a line each, under the title: the text stays the hero
  const tagLine = fold("Tags", tags.el, () => tagsSay(tags.value()), "tag");
  const todoLine = fold("Due", todo.el, () => todoSays(todo.value()), "due");
  const laterLine = fold("Type", later.el, () => mediaSays(later.value()), "later");
  const showTodo = () => {
    todoLine.el.hidden = kind.value() !== "todo";
    laterLine.el.hidden = kind.value() !== "consume";
  };
  kind.el.addEventListener("change", showTodo);
  showTodo();
  const conflict = h("div");
  let busy = false; // a save in flight (or its removal question open): no second one
  let closed = false; // saved: the editor is going, Save stays off
  const send = async () => {
    const long = tooLong(body(), 0, body() === over);
    if (long) return toast(long, "", undefined, 8000); // still editing, as it was
    if (!(await confirmRemoval(p, over, body()))) return; // still editing, as it was
    const textual = body() !== over || title.value !== p.title;
    try {
      const saved = await api<Page>(`pages/${p.id}`, {
        method: "PATCH",
        headers: JSON_TYPE,
        // The title only if changed: ingest may rename a provisional title meanwhile
        body: JSON.stringify({
          ...textPart(textual, base, body()),
          ...(title.value !== p.title && { title: title.value }),
          kind: toSend(kind.value(), kind.picked(), p.kind),
          ...(retagged() && { tags: tags.value() }),
          ...(redated() && todoNow()),
          ...(retyped() && { fields: mediaFields(later.value()) }),
        }),
      });
      closed = true;
      await ed.done();
      await load(saved); // its first image: the figures
      show(saved);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 409)) return toast(String(err));
      const theirs = await api<Page>(`pages/${p.id}`).catch(() => null);
      if (!theirs) return toast("Changed elsewhere, and the server can't be reached to show it");
      base = theirs.rev; // saving again now overwrites their version with yours
      over = theirs.body;
      conflict.replaceChildren(
        h(
          "div",
          { className: "conflict" },
          h(
            "p",
            {},
            "This page was changed elsewhere. Merge their text below into yours and save again, or discard yours.",
          ),
          h(
            "blockquote",
            { dir: "auto" },
            h("strong", {}, theirs.title),
            h("pre", {}, theirs.body),
          ),
          h(
            "button",
            {
              type: "button",
              onclick: async () => {
                await ed.done();
                await load(theirs);
                show(theirs);
              },
            },
            "Discard mine, show theirs",
          ),
        ),
      );
      conflict.scrollIntoView({ behavior: "smooth" });
    }
  };
  const save = async () => {
    if (busy) return; // a double tap, or Ctrl+Enter, while the first is still on its way
    busy = true;
    ed.save.disabled = true;
    try {
      await send();
    } finally {
      if (!closed) {
        busy = false; // refused, or a conflict to merge: save again
        ed.save.disabled = false;
      }
    }
  };
  const ed = editor({
    text,
    read: body,
    before: [kind.el, title, tagLine.el, todoLine.el, laterLine.el],
    after: [...(takesPhotos(p) ? [photoAdder(p)] : []), conflict],
    foot: embeds.chips,
    key,
    draft: (): Draft => ({
      title: title.value,
      text: body(),
      kind: kind.value(),
      picked: kind.picked(),
      tags: tags.value(),
      tagsFrom,
      ...(redated() && { todo: todo.value() }),
      ...(retyped() && { media: later.value() }),
      base,
    }),
    dirty: () =>
      title.value !== p.title ||
      body() !== at.body ||
      kind.value() !== was ||
      retagged() ||
      redated() ||
      retyped(),
    restored: !!kept,
    ondiscard: () => {
      title.value = p.title;
      embeds.set(at.body);
      kind.reset(was);
      tags.reset(p.tags);
      tagsFrom = p.tags;
      todo.reset(p.due ?? null, p.priority ?? null);
      later.reset(mediaWas);
      showTodo();
      tagLine.refresh();
      todoLine.refresh();
      laterLine.refresh();
      base = at.rev;
      over = at.body;
    },
    onsave: () => void save(),
  });
  // Photos added (Add photo, uploaded now or later) onto the revision this editor holds: the
  // embeds go to the end of its text too, and it moves on to the page's new revision, so Save
  // doesn't show the photos as a conflict. Added onto another revision (the page changed
  // meanwhile), Save shows the conflict, as for any change made elsewhere.
  const adopted = (e: Event) => {
    if (!ed.form.isConnected) return removeEventListener(ADDED, adopted);
    const page = (e as CustomEvent<Page & { appended_on: number | null }>).detail;
    if (page.id !== p.id || page.appended_on !== base) return;
    const merged = adopt(body(), over, page.body);
    if (merged === null) return;
    const { selectionStart, selectionEnd } = text; // the text before them is as it was
    embeds.set(merged);
    text.setSelectionRange(selectionStart, selectionEnd);
    base = page.rev;
    over = page.body;
    // Discard goes back to the page as it is now, photos and all: they are not the edit
    Object.assign(at, { rev: page.rev, body: page.body });
    ed.keep();
  };
  addEventListener(ADDED, adopted);
  text.focus();
  // Where the page was being read (its top if not scrolled into its text); with no view (a
  // list's row), as the box opens. A draft kept with other text: as far down its text instead
  // (its lines need not be the page's)
  if (read === null) return;
  const asRead = !kept || kept.text === p.body;
  toLine(text, asRead ? read : Math.floor((read * text.value.split("\n").length) / lines));
}

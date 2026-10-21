// A page in the editor (page.ts's Edit): its text, title, kind, tags and a todo's due date
// and priority, with the draft kept on the phone, and a conflict shown if it changed
// elsewhere meanwhile. A chunk of its own with editor.ts, kept offline (vite.config.ts).
import { ApiError, api, type Page } from "./api";
import { drafts } from "./db";
import {
  confirmRemoval,
  editor,
  kindPicker,
  same,
  suggested,
  tagField,
  todoField,
  todoStart,
  tooLong,
  toSend,
} from "./editor";
import { h, toast } from "./ui";

interface Draft {
  title: string;
  text: string;
  kind?: string;
  picked?: boolean; // the user chose the kind
  tags?: string[];
  tagsFrom?: string[]; // the page's tags when it was made: changed elsewhere since, they stay
  todo?: { due: string | null; priority: string | null }; // a todo's, if changed
  base: number; // the revision it was made on
}
const JSON_TYPE = { "Content-Type": "application/json" };

export async function edit(p: Page, load: (p: Page) => Promise<void>, show: (p: Page) => void) {
  // An unsaved edit comes back, on the revision it was made on: if the page has changed
  // since, saving it shows the conflict rather than overwriting.
  const key = `page:${p.id}`;
  const kept = await drafts.get<Draft>(key).catch(() => undefined);
  // Its kind. A note nobody filed yet gets one suggested from its text (a link alone: Read),
  // as in the composer, until the user picks one; a draft's kind only if the user picked it
  const unfiled = !p.kind_fixed && p.kind === "note";
  const was = unfiled ? suggested(p.body) : p.kind;
  const initial = unfiled ? suggested(kept?.text ?? p.body) : p.kind;
  const kind = kindPicker(kept?.picked ? (kept.kind ?? initial) : initial, !!kept?.picked);
  let base = kept?.base ?? p.rev;
  let over = p.body; // the text a save replaces: its deleted embeds are warned about
  const title = h("input", { value: kept?.title ?? p.title, "aria-label": "Title", dir: "auto" });
  const text = h("textarea", { value: kept?.text ?? p.body, rows: 8, "aria-label": "Body" });
  if (unfiled) text.addEventListener("input", () => kind.suggest(suggested(text.value)));
  // Tags: a draft's only if they were changed in it (not, say, tags Claude or another
  // device set since); and sent only if changed from those it started from
  const ours = kept?.tags && !same(kept.tags, kept.tagsFrom ?? p.tags) ? kept : null;
  let tagsFrom = ours?.tagsFrom ?? p.tags;
  const tags = tagField(ours?.tags ?? p.tags, () => ed.keep());
  const retagged = () => !same(tags.value(), tagsFrom);
  // A todo's due date and priority: shown while the kind is Todo, sent if changed
  const start = todoStart(kept, p); // a draft's, cleared ones too, else the page's
  const todo = todoField(start.due, start.priority);
  const todoNow = () => (kind.value() === "todo" ? todo.value() : null);
  const redated = () => {
    const t = todoNow();
    return !!t && (t.due !== (p.due ?? null) || t.priority !== (p.priority ?? null));
  };
  const showTodo = () => (todo.el.hidden = kind.value() !== "todo");
  kind.el.addEventListener("change", showTodo);
  showTodo();
  const conflict = h("div");
  const save = async () => {
    const long = tooLong(text.value);
    if (long) return toast(long, "", undefined, 8000); // still editing, as it was
    if (!(await confirmRemoval(p, over, text.value))) return; // still editing, as it was
    try {
      const saved = await api<Page>(`pages/${p.id}`, {
        method: "PATCH",
        headers: JSON_TYPE,
        // The title only if changed: ingest may rename a provisional title meanwhile
        body: JSON.stringify({
          base_rev: base,
          body: text.value,
          ...(title.value !== p.title && { title: title.value }),
          kind: toSend(kind.value(), kind.picked(), p.kind),
          ...(retagged() && { tags: tags.value() }),
          ...(redated() && todoNow()),
        }),
      });
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
  const ed = editor({
    text,
    before: [kind.el, title, tags.el, todo.el],
    after: [conflict],
    key,
    draft: (): Draft => ({
      title: title.value,
      text: text.value,
      kind: kind.value(),
      picked: kind.picked(),
      tags: tags.value(),
      tagsFrom,
      ...(redated() && { todo: todo.value() }),
      base,
    }),
    dirty: () =>
      title.value !== p.title ||
      text.value !== p.body ||
      kind.value() !== was ||
      retagged() ||
      redated(),
    restored: !!kept,
    ondiscard: () => {
      title.value = p.title;
      text.value = p.body;
      kind.reset(was);
      tags.reset(p.tags);
      tagsFrom = p.tags;
      todo.reset(p.due ?? null, p.priority ?? null);
      showTodo();
      base = p.rev;
      over = p.body;
    },
    onsave: () => void save(),
  });
  text.focus();
}

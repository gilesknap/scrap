// The full-screen drawing viewer and editor (in the lazy chunk; drawing.ts opens it).
//
// A layer the size of the visual viewport, like the text editor, with a history entry: the
// phone's Back closes it. View and edit are one Excalidraw scene, so zoom, scroll and unsaved
// edits are kept when switching. Edits are kept as a draft as they change, so a Back, a
// failed save or a killed app loses nothing.
import { ApiError, api } from "../api";
import { drafts } from "../db";
import type { Target } from "../drawing";
import { saveBlob } from "../sharing";
import { h, toast, when } from "../ui";
import { elementsOf, board as mount } from "./board";
import { type Drawing, madeBy, scenePayload, type Version } from "./frame";

const path = (t: Target) => `captures/${t.cid}/photos/${t.sha}/drawing`;
const draftKey = (t: Target) => `drawing:${t.cid}:${t.sha}`;

interface Draft {
  elements: unknown[];
  base: number | null; // the version it was edited from
  at: number;
}

/** The full-screen drawing viewer. onSaved is told of a new current version (a save or
 * a Restore), to refresh the page. */
export function openDrawing(t: Target, onSaved: () => void) {
  const opener = document.activeElement as HTMLElement | null;
  const behind = [...document.querySelectorAll<HTMLElement>("body > :is(header, main, nav)")];
  const tool = (label: string, onclick: () => void, extra: Record<string, unknown> = {}) =>
    h("button", { type: "button", onclick, ...extra }, label);

  let board: Awaited<ReturnType<typeof mount>> | null = null;
  let current: Drawing | null = null;
  let editing = false;
  let base: number | null = null; // the version an edit started from
  let fromDraft = false; // the scene is a draft, not yet saved
  let timer = 0;

  const host = h("div", { className: "board", "aria-label": `Drawing of ${t.name || "a photo"}` });
  const message = h("p", { className: "board-message" }, "Loading drawing…");
  const photo = h("img", { src: t.photo, alt: t.name || "The photo", draggable: false });
  const body = h(
    "div",
    { className: "drawing-body" },
    h("figure", { className: "drawing-photo" }, photo),
    host,
    message,
  );
  const notes = h("div", { className: "drawing-notes", "aria-live": "polite" });
  const close = tool("Close", () => history.back());
  const fit = tool("Fit", () => board?.fit());
  const photoToggle = tool("Photo", () => {
    const on = !layer.classList.contains("photo-on");
    layer.classList.toggle("photo-on", on);
    photoToggle.setAttribute("aria-pressed", String(on));
    setTimeout(() => board?.fit(), 50); // the board changed size: show all of it again
  });
  photoToggle.setAttribute("aria-pressed", "false");
  const more = h(
    "details",
    { className: "more" },
    h("summary", { "aria-label": "More: history and export" }, "More"),
    h(
      "div",
      { className: "menu" },
      tool("History", () => void showHistory()),
      tool("Export .excalidraw", () => void exportAs("excalidraw")),
      tool("Export PNG", () => void exportAs("png")),
      tool("Export SVG", () => void exportAs("svg")),
    ),
  );
  const edit = tool("Edit", () => void startEdit(), { className: "primary" });
  const cancel = tool("Cancel", () => void cancelEdit());
  const undo = tool("Undo", () => board?.undo());
  const save = tool("Save", () => void saveEdit(), { className: "primary" });
  const viewTools = [close, fit, photoToggle, more, edit];
  const editTools = [cancel, undo, photoToggle, save];
  const bar = h("div", { className: "drawing-bar" });
  const layer = h(
    "div",
    { className: "drawing-layer", role: "dialog", "aria-modal": "true", "aria-label": "Drawing" },
    bar,
    notes,
    body,
  );

  const showTools = () => {
    bar.replaceChildren(...(editing ? editTools : viewTools));
    layer.classList.toggle("editing-drawing", editing);
    for (const b of [fit, edit, more]) b.toggleAttribute("disabled", !board);
  };
  // a banner: "restored" (a draft) or "conflict", as the text editor's, or plain
  const note = (className: string, ...kids: (Node | string)[]) =>
    notes.replaceChildren(h("div", { className }, ...kids));
  const clearNote = () => notes.replaceChildren();
  const dirty = () => editing && (fromDraft || !!board?.changed());

  // ---- drafts
  const keep = () => {
    clearTimeout(timer);
    if (!board || !editing) return;
    if (!dirty()) return void drafts.del(draftKey(t)).catch(() => {});
    const draft: Draft = { elements: [...board.elements()], base, at: Date.now() };
    drafts.put(draftKey(t), draft).catch(() => {}); // refused: the scene is still open
  };
  const changed = () => {
    clearTimeout(timer);
    timer = window.setTimeout(keep, 500);
  };
  const dropDraft = () => drafts.del(draftKey(t)).catch(() => {});

  // ---- loading
  async function load() {
    message.hidden = false;
    message.textContent = "Loading drawing…";
    try {
      current = await api<Drawing>(path(t));
      board = await mount(host, current.data, changed);
      message.hidden = true;
      const kept = await drafts.get<Draft>(draftKey(t)).catch(() => undefined);
      // A short mark on Edit (the bar has no room for words) and the words under the bar
      edit.classList.toggle("dot", !!kept);
      if (kept) {
        edit.setAttribute("aria-label", "Edit (unsaved draft)");
        note("restored", "You have an unsaved edit of this drawing: Edit to carry on.");
      }
    } catch (err) {
      console.error("drawing viewer", err);
      message.replaceChildren(
        err instanceof ApiError
          ? `Can't open the drawing: ${err.message}`
          : "Can't open the drawing: the server can't be reached.",
        " ",
        tool("Retry", () => void load()),
      );
    }
    showTools();
  }

  async function reload(drawing: Drawing) {
    current = drawing;
    board?.load(await elementsOf(drawing.data));
    onSaved();
  }

  // ---- edit
  async function startEdit() {
    if (!board || !current) return;
    clearNote(); // e.g. History: no Restore under an edit
    const kept = await drafts.get<Draft>(draftKey(t)).catch(() => undefined);
    base = current.version;
    fromDraft = false;
    if (kept) {
      board.load(kept.elements as never);
      base = kept.base;
      fromDraft = true;
      const discard = tool("Discard it", () => {
        void dropDraft();
        void reload(current as Drawing);
        fromDraft = false;
        base = current?.version ?? null;
        clearNote();
      });
      note("restored", "Restored your unsaved drawing. ", discard);
    }
    editing = true;
    edit.classList.remove("dot");
    edit.removeAttribute("aria-label");
    board.setEditing(true);
    showTools();
  }

  async function stopEdit() {
    clearTimeout(timer); // no draft kept after this
    editing = false;
    fromDraft = false;
    board?.setEditing(false);
    showTools();
  }

  async function cancelEdit() {
    if (dirty() && !confirm("Discard your changes to the drawing?")) return;
    clearTimeout(timer);
    await dropDraft();
    clearNote();
    if (current) await reload(current);
    await stopEdit();
  }

  async function saveEdit() {
    if (!board || !current) return;
    clearTimeout(timer);
    keep(); // whatever happens next, the draft has it
    save.setAttribute("aria-busy", "true");
    try {
      const frame = current.data.width
        ? { width: current.data.width, height: current.data.height as number }
        : null;
      const saved = await api<Drawing>(path(t), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_version: base,
          scene: scenePayload(board.elements(), frame, board.background()),
        }),
      });
      current = saved;
      board.load(board.elements()); // the saved scene, as it is on screen
      await dropDraft();
      clearNote();
      await stopEdit();
      toast(`Saved as version ${saved.version}`);
      onSaved();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) return conflict(err.body.version);
      const why =
        err instanceof ApiError ? err.message : "can't reach the server. It is kept as a draft";
      toast(`Not saved: ${why}`, "", undefined, 8000);
    } finally {
      save.removeAttribute("aria-busy");
    }
  }

  function conflict(theirs: number | null | undefined) {
    note(
      "conflict",
      `This drawing was changed elsewhere (now version ${theirs ?? "none"}). Nothing is lost:`,
      " saving yours adds it as a new version, theirs stays in History. ",
      tool("Save mine", () => {
        base = theirs ?? null;
        clearNote();
        void saveEdit();
      }),
      " ",
      tool("Discard mine, show theirs", async () => {
        clearNote();
        try {
          await reload(await api<Drawing>(path(t)));
        } catch {
          toast("Can't reach the server to show theirs");
        }
        await stopEdit();
        await dropDraft(); // last: showing theirs may have queued a write of the scene
      }),
    );
  }

  // ---- history and export
  async function showHistory() {
    more.open = false;
    try {
      const versions = await api<Version[]>(`${path(t)}/versions`);
      const list = h(
        "ol",
        { className: "versions" },
        ...versions.map((v) =>
          h(
            "li",
            {},
            h("span", {}, `v${v.version} · ${madeBy(v)} · ${when(v.created_at)}`),
            v.current
              ? h("strong", {}, "current")
              : tool("Restore", () => void restore(v.version), {
                  "aria-label": `Restore version ${v.version}`,
                }),
          ),
        ),
      );
      note("history", h("strong", {}, "History"), " ", tool("Hide", clearNote), list);
    } catch (err) {
      toast(`Can't load the history: ${err instanceof ApiError ? err.message : "offline?"}`);
    }
  }

  async function restore(version: number) {
    if (editing) return; // History is closed while editing; never swap the scene under it
    try {
      const drawing = await api<Drawing>(`${path(t)}/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version, base_version: current?.version }),
      });
      await reload(drawing);
      clearNote();
      toast(`Version ${version} restored as version ${drawing.version}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast("Changed elsewhere meanwhile: showing the latest");
        await reload(await api<Drawing>(path(t))).catch(() => {});
        return void showHistory();
      }
      toast(`Not restored: ${err instanceof ApiError ? err.message : "can't reach the server"}`);
    }
  }

  async function exportAs(kind: "excalidraw" | "png" | "svg") {
    more.open = false;
    if (!board) return;
    try {
      const blob = await board.export(kind);
      saveBlob(blob, `${t.slug}-drawing-v${current?.version ?? 0}.${kind}`);
    } catch (err) {
      toast(`Export failed: ${(err as Error).message}`);
    }
  }

  // ---- open and close: Back closes, keeping an unsaved edit as a draft
  const keys = (e: KeyboardEvent) => {
    if (e.key === "Escape" && !editing) history.back();
  };
  const onpop = (e: PopStateEvent) => {
    e.stopImmediatePropagation();
    if (dirty()) {
      keep();
      toast("Kept as a draft: open the drawing and Edit to carry on");
    }
    clearTimeout(timer);
    removeEventListener("popstate", onpop, true);
    removeEventListener("keydown", keys);
    board?.close();
    layer.remove();
    for (const el of behind) el.inert = false;
    document.body.classList.remove("drawing-open");
    opener?.focus({ preventScroll: true });
  };
  for (const el of behind) el.inert = true;
  document.body.classList.add("drawing-open");
  document.body.append(layer);
  history.pushState({ drawing: true }, "");
  addEventListener("popstate", onpop, true);
  addEventListener("keydown", keys);
  showTools();
  close.focus();
  void load();
}

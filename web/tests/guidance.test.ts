// Guidance for Claude per image (#538): at the bottom of an image's "Claude's reading" fold,
// the write-up's own fold (guidance.ts: closed, "(set)" once saved, Save only stores it, what
// is typed kept when the page is drawn again), and the text read from it in a closed fold of
// its own.
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FileRef, Ingest } from "../src/api";
import { type FakeNode, fakeDocument } from "./fakedom";

vi.mock("../src/css/reading.css", () => ({}));
vi.mock("../src/excalidraw.css", () => ({}));
vi.mock("../src/drawing", () => ({ drawingCard: () => "", openDrawing: () => {} }));
const toast = vi.fn();
vi.mock("../src/ui", async (real) => ({ ...(await real<object>()), toast }));
vi.stubGlobal("document", fakeDocument());
vi.stubGlobal("dispatchEvent", () => true);
const fetch = vi.fn();
vi.stubGlobal("fetch", fetch);
const { photoPanel } = await import("../src/ingest");
const { READ_TEXT } = await import("../src/reading");

const node = (x: unknown) => x as FakeNode;
const SHA = "a".repeat(64);
const done: Ingest = {
  state: "done",
  failures: 0,
  error: null,
  text: "Phone -> Queue",
  description: "A board of the flow.",
  image_kind: "whiteboard",
  drawing: null,
};

function panel(over: Partial<Ingest> = {}, guidance: string | null = null, refresh = vi.fn()) {
  const blob: FileRef & { ingest: Ingest } = {
    sha256: SHA,
    mime: "image/jpeg",
    size: 9,
    filename: "board.jpg",
    ingest: { ...done, ...over },
    guidance,
  };
  const p = photoPanel({
    cid: "CAP1",
    blob,
    figure: document.createElement("figure"),
    photo: "/p.jpg",
    slug: "s",
    queue: null,
    refresh,
  });
  const fold = node(p).find("DETAILS")[0];
  const card = fold.childNodes[1];
  return { fold, card, refresh };
}
const folds = (card: FakeNode) => card.childNodes.filter((k) => k.nodeName === "DETAILS");

beforeEach(() => {
  fetch.mockReset();
  toast.mockReset();
});

describe("an image's reading", () => {
  it("folds the text read from it, closed, after the description", () => {
    const { fold, card } = panel();
    expect(fold.open).toBe(false);
    const [text] = folds(card);
    expect(card.childNodes[0].className).toBe("desc");
    expect(text.className).toBe("claude-text readtext");
    expect(text.open).toBe(false);
    expect(text.childNodes[0].textContent).toBe(READ_TEXT);
    expect(text.find("PRE")[0].textContent).toBe("Phone -> Queue");
  });

  it("has Guidance for Claude at the bottom, closed, before Regenerate at the card's end", () => {
    const { card } = panel();
    const g = folds(card)[1];
    expect(g.className).toBe("claude-text sub guidance");
    expect(g.open).toBe(false);
    expect(g.childNodes[0].textContent).toBe("Guidance for Claude");
    expect(g.find("P")[0].textContent).toBe("Used by the next Regenerate, and kept with it.");
    const box = g.find("TEXTAREA")[0];
    expect(box.rows).toBe(3);
    expect(box.maxLength).toBe(2000);
    expect(String(box.placeholder)).toMatch(/^e\.g\. /);
    expect(g.find("BUTTON")[0].textContent).toBe("Save");
    expect(card.childNodes.at(-2)).toBe(g);
    expect(card.childNodes.at(-1)?.className).toBe("regen-row");
  });

  it("says (set) once some is saved, and shows it", () => {
    const g = folds(panel({}, "R1 is a resistor").card)[1];
    expect(g.childNodes[0].textContent).toBe("Guidance for Claude (set)");
    expect(g.find("TEXTAREA")[0].value).toBe("R1 is a resistor");
  });

  it("has it with no read text too, and while the reading is under way", () => {
    const { card } = panel({ text: null, state: "queued" });
    expect(folds(card).map((f) => f.className)).toEqual(["claude-text sub guidance"]);
  });

  it("only stores it on Save, then shows the page again; queues nothing", async () => {
    fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ guidance: "x" }) });
    const { card, refresh } = panel();
    const g = folds(card)[1];
    const box = g.find("TEXTAREA")[0];
    box.value = "  R1 is a resistor ";
    await (g.find("BUTTON")[0].onclick as () => Promise<void>)();
    expect(fetch).toHaveBeenCalledOnce();
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe(`/api/captures/CAP1/photos/${SHA}/guidance`);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ guidance: "  R1 is a resistor " });
    expect(refresh).toHaveBeenCalledOnce();
    expect(toast).toHaveBeenCalledWith("Saved: the next Regenerate follows it");
  });

  it("keeps what is being typed, with its fold open, when the page is drawn again", () => {
    const g = folds(panel().card)[1];
    const box = g.find("TEXTAREA")[0];
    box.value = "half typed";
    (box.oninput as () => void)();
    const redrawn = panel();
    expect(redrawn.fold.open).toBe(true); // the reading too, so it stays in sight
    const again = folds(redrawn.card)[1];
    expect(again.open).toBe(true);
    expect(again.find("TEXTAREA")[0].value).toBe("half typed");
  });

  it("says why it was not saved, and keeps what was typed", async () => {
    fetch.mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: "too long" }) });
    const g = folds(panel().card)[1];
    const box = g.find("TEXTAREA")[0];
    box.value = "kept";
    (box.oninput as () => void)();
    await (g.find("BUTTON")[0].onclick as () => Promise<void>)();
    expect(toast.mock.calls[0][0]).toMatch(/^Not saved: /);
    expect(folds(panel().card)[1].find("TEXTAREA")[0].value).toBe("kept");
  });
});

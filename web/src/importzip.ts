// Settings > Import Markdown (#417): pick a zip (a scrap export, an Obsidian vault), see how
// many pages and photos it holds and roughly what Claude would cost for each, choose, and send
// it to POST /api/import. Part of the lazy Settings chunk, never the app shell.
import { api } from "./api";
import { h } from "./ui";
import { countNames, type ZipCount, zipNames } from "./zipcount";

interface Terms {
  max_upload_bytes: number;
  enrich: boolean; // Claude can tag and summarise text pages here
  photos: boolean; // and read photos
  page_usd: number; // roughly, a text page
  photo_usd: number; // roughly, a photo
}

interface Issue {
  count: number;
  items: string[];
}

export interface Imported {
  new: number;
  skipped: number;
  enrich: number;
  photos: number;
  files: number;
  tag: string;
  issues: Record<string, Issue>;
}

const MB = 2 ** 20;

/** A rough cost in dollars, as shown. */
export const dollars = (usd: number) => (usd < 0.01 ? "under $0.01" : `about $${usd.toFixed(2)}`);

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** What an import did, in words. */
export function said(r: Imported): string {
  const parts = [`Imported ${plural(r.new, "page")}`];
  if (r.skipped) parts.push(`${r.skipped} here already, not imported again`);
  const queued = [
    r.enrich && `${plural(r.enrich, "page")} to tag and summarise`,
    r.photos && `${plural(r.photos, "photo")} to read`,
  ].filter(Boolean);
  const tagged = r.new ? ` ${r.new === 1 ? "It is" : "Each is"} tagged ${r.tag}.` : "";
  return `${parts.join("; ")}.${tagged} ${
    queued.length ? `Queued for Claude: ${queued.join(", ")}.` : "Nothing queued for Claude."
  }`;
}

/** A tick box with its cost beside it. */
function choice(label: string, cost: string, off: boolean) {
  const box = h("input", { type: "checkbox", disabled: off });
  const row = h(
    "label",
    { className: "tick" },
    box,
    h("span", {}, label),
    h("span", { className: "hint" }, off ? "Claude is off on this server" : cost),
  );
  return { box, row };
}

/** The Import Markdown button and what it opens beside it, for the Store section. */
export function importSection(): HTMLElement[] {
  const input = h("input", { type: "file", accept: ".zip,application/zip", hidden: true });
  const pick = h("button", { type: "button", className: "button" }, "Import Markdown…");
  const panel = h("div", { className: "import", hidden: true });
  const status = h("p", { className: "hint", role: "status" });
  pick.onclick = () => input.click();
  input.onchange = async () => {
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    panel.hidden = false;
    panel.replaceChildren(status);
    status.textContent = "Reading the zip…";
    let terms: Terms;
    try {
      terms = await api<Terms>("import");
    } catch (e) {
      status.textContent = `Could not reach scrap: ${(e as Error).message}`;
      return;
    }
    if (file.size > terms.max_upload_bytes) {
      status.textContent = `${file.name} is ${(file.size / MB).toFixed(0)} MB, over the ${(
        terms.max_upload_bytes / MB
      ).toFixed(0)} MB upload limit: import it with scrap import on the server.`;
      return;
    }
    const names = await zipNames(file);
    if (!names) {
      status.textContent = `${file.name} is not a zip scrap can read.`;
      return;
    }
    show(file, countNames(names), terms);
  };

  function show(file: File, n: ZipCount, terms: Terms) {
    const enrich = choice(
      "Enrich text pages with Claude",
      `${dollars(n.pages * terms.page_usd)} for up to ${plural(n.pages, "page")} (rough)`,
      !terms.enrich,
    );
    const photos = choice(
      "Read photos with Claude",
      `${dollars(n.photos * terms.photo_usd)} for up to ${plural(n.photos, "image")} in the zip (rough; the dearer model)`,
      !terms.photos,
    );
    const go = h("button", { type: "button", className: "primary" }, "Import");
    status.textContent = "";
    panel.replaceChildren(
      h(
        "p",
        { className: "hint" },
        `${file.name}: ${plural(n.pages, "page")}, ${plural(n.photos, "photo")}.`,
      ),
      enrich.row,
      photos.row,
      go,
      status,
    );
    go.onclick = async () => {
      go.disabled = pick.disabled = true;
      status.textContent = "Importing…";
      const form = new FormData();
      form.append("file", file);
      if (enrich.box.checked) form.append("enrich", "1");
      if (photos.box.checked) form.append("photos", "1");
      try {
        const r = await api<Imported>("import", { method: "POST", body: form });
        panel.replaceChildren(status, problems(r));
        status.textContent = said(r);
      } catch (e) {
        status.textContent = `Not imported: ${(e as Error).message}`;
        go.disabled = false;
      } finally {
        pick.disabled = false;
      }
    };
  }

  return [
    pick,
    input,
    h(
      "p",
      { className: "hint" },
      "A zip of Markdown pages: an export from scrap, or an Obsidian vault. Each page is tagged import and the date; a page already here is skipped, never overwritten. Claude's folder in an export is left out.",
    ),
    panel,
  ];
}

/** What the import could not do, folded: each kind counted, its first few listed. */
function problems(r: Imported) {
  const kinds = Object.entries(r.issues);
  if (!kinds.length) return "";
  const total = kinds.reduce((n, [, i]) => n + i.count, 0);
  return h(
    "details",
    {},
    h("summary", {}, `${plural(total, "note")} on the import`),
    h(
      "ul",
      {},
      ...kinds.map(([what, i]) =>
        h("li", {}, `${what}: ${i.count}`, h("ul", {}, ...i.items.map((t) => h("li", {}, t)))),
      ),
    ),
  );
}

import { expect, it } from "vitest";
import { dollars, said } from "../src/importzip";
import { countNames, zipNames } from "../src/zipcount";

/** A zip's central directory and its end (no file data: only the names are read). */
function zip(names: string[], comment = ""): Blob {
  const enc = new TextEncoder();
  const parts: Uint8Array[] = [new Uint8Array(30)]; // stands in for the files' data
  let size = 0;
  for (const name of names) {
    const n = enc.encode(name);
    const head = new DataView(new ArrayBuffer(46));
    head.setUint32(0, 0x02014b50, true);
    head.setUint16(28, n.length, true);
    parts.push(new Uint8Array(head.buffer), n);
    size += 46 + n.length;
  }
  const c = enc.encode(comment);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, names.length, true);
  end.setUint16(10, names.length, true);
  end.setUint32(12, size, true);
  end.setUint32(16, 30, true);
  end.setUint16(20, c.length, true);
  return new Blob([...parts, new Uint8Array(end.buffer), c] as BlobPart[]);
}

it("reads a zip's names from its central directory", async () => {
  const names = ["a.md", "deep/b.md", "files/x.png", "ünï.md"];
  expect(await zipNames(zip(names))).toEqual(names);
  expect(await zipNames(zip(names, "a comment"))).toEqual(names);
});

it("is null for what is not a zip it can read", async () => {
  expect(await zipNames(new Blob(["not a zip at all, just text"]))).toBeNull();
  expect(await zipNames(new Blob([]))).toBeNull();
});

it("counts pages and photos as the import reads them", () => {
  const sha = "a".repeat(64);
  const names = [
    "note.md",
    "deep/My Note.md",
    "deep/",
    `files/${sha}.jpg`,
    `files/${sha}.md`, // a stored Markdown file: not a page
    `files/${sha}-01ARZ3NDEKTSV4RRFFQ69G5FAV.excalidraw`,
    "_claude/note.md", // model text: never read
    ".obsidian/workspace.md",
    "Pasted image.PNG",
    "Shouting.MD", // the import reads .md only
    "doc.pdf",
  ];
  expect(countNames(names)).toEqual({ pages: 2, photos: 2 });
});

it("says what an import did, and rough costs", () => {
  const r = { new: 3, skipped: 1, enrich: 2, photos: 0, files: 1, tag: "import/2026-10-29" };
  expect(said({ ...r, issues: {} })).toBe(
    "Imported 3 pages; 1 here already, not imported again. Each is tagged import/2026-10-29. Queued for Claude: 2 pages to tag and summarise.",
  );
  expect(said({ ...r, new: 1, skipped: 0, enrich: 0, issues: {} })).toBe(
    "Imported 1 page. It is tagged import/2026-10-29. Nothing queued for Claude.",
  );
  expect(said({ ...r, new: 0, skipped: 3, enrich: 0, issues: {} })).toBe(
    "Imported 0 pages; 3 here already, not imported again. Nothing queued for Claude.",
  );
  expect(dollars(0.004)).toBe("under $0.01");
  expect(dollars(1.234)).toBe("about $1.23");
});

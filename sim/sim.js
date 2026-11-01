// scrap sim: a fake scrap server inside the page, so the real PWA build runs anywhere.
// Loaded as a classic script before the app. The app's routes ride in the URL's hash
// (#/todos) so the host page's own address never changes; the build replaces the app's
// location.pathname / location.search with __sim.loc's.
(() => {
  "use strict";
  const BASE = new URL(".", location.href).href; // where the sim's files are published
  const SEED_DAY = "2026-10-21"; // the day the sample data was made: dates move with today

  // ---------- the virtual address
  const parse = () => {
    const h = location.hash.startsWith("#/") ? location.hash.slice(1) : "/";
    const q = h.indexOf("?");
    return q < 0 ? { pathname: h, search: "" } : { pathname: h.slice(0, q), search: h.slice(q) };
  };
  const loc = {
    get pathname() {
      return parse().pathname;
    },
    get search() {
      return parse().search;
    },
  };
  const toHash = (url) => {
    if (url === undefined || url === null) return url;
    const u = new URL(String(url), `${location.origin}${parse().pathname}${parse().search}`);
    if (u.origin !== location.origin) return url;
    return `#${u.pathname}${u.search}`;
  };
  for (const m of ["pushState", "replaceState"]) {
    const real = History.prototype[m];
    History.prototype[m] = function (state, title, url) {
      return real.call(this, state, title, url === undefined ? undefined : toHash(url));
    };
  }

  // ---------- dates: the sample data keeps its shape relative to today
  const localDay = (d = new Date()) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const dayMs = 86400000;
  const shiftDays = Math.round((Date.parse(localDay()) - Date.parse(SEED_DAY)) / dayMs);
  const shiftDate = (d) => (d ? localDay(new Date(Date.parse(`${d}T12:00:00`) + shiftDays * dayMs)) : d);
  const shiftTime = (t) => (t ? new Date(Date.parse(t) + shiftDays * dayMs).toISOString() : t);
  const nowIso = () => new Date().toISOString();

  // ---------- the store
  const seed = window.__SIM_SEED;
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const pages = clone(seed.pages);
  const drawings = clone(seed.drawings); // "cid/sha" -> {current, versions}
  const trash = new Set();
  const userBlobs = new Map(); // sha -> object URL, for files captured in the sim
  const sources = new Map(); // page id -> capture source
  for (const p of pages) {
    // One page written over MCP, to show its Written by Claude pill
    if (p.slug === "weekly-controls-sync" && p.captures[0]) {
      p.captures[0].source = "mcp";
      p.fields = { ...p.fields, origin: "Claude Code session" };
    }
    const c = p.captures[0];
    const t = shiftTime(c?.created_at?.replace(/Z$/, ".000Z") ?? p.created_at);
    p.created_at = p.updated_at = t;
    // Page header mock: the Claude-written page made by Claude (made_by, #280) and added two
    // weeks before its last edit, so its meta line shows both dates
    if (p.slug === "weekly-controls-sync") {
      p.made_by = "claude";
      p.created_at = new Date(Date.parse(t) - 14 * dayMs).toISOString();
    }
    p.due = shiftDate(p.due);
    p.snoozed_until = shiftDate(p.snoozed_until);
    for (const cap of p.captures) cap.created_at = shiftTime(cap.created_at);
    sources.set(p.id, c?.source ?? "pwa");
  }
  for (const k of Object.keys(drawings)) {
    drawings[k].current.created_at = shiftTime(drawings[k].current.created_at);
    for (const v of drawings[k].versions) v.created_at = shiftTime(v.created_at);
  }
  // What Claude made of the photos, as it would be with ingest on
  const INGEST = window.__SIM_INGEST || {};
  for (const p of pages)
    for (const c of p.captures)
      for (const b of c.blobs) {
        const extra = INGEST[p.slug] || INGEST[p.title];
        if (extra) b.ingest = { ...b.ingest, ...extra };
        const d = drawings[`${c.id}/${b.sha256}`];
        if (d && b.ingest)
          b.ingest.drawing = {
            id: d.current.id,
            version: d.current.version,
            producer: d.current.producer,
            width: d.current.data.width,
            height: d.current.data.height,
          };
      }

  // 521 mock: images the fixtures carry as SVG text (Claude's add_svg diagrams, the owner's
  // photographed working), served as object URLs under their sha
  for (const p of pages)
    for (const c of p.captures)
      for (const b of c.blobs)
        if (b._svg && !userBlobs.has(b.sha256))
          userBlobs.set(b.sha256, URL.createObjectURL(new Blob([b._svg], { type: "image/svg+xml" })));

  // ---------- files in a page's text (design/edit-embeds): PDFs and a .md made here, as
  // object URLs under fake SHA-256s, so their links open and their cards show each state
  const pdfBlob = (lines) => {
    const stream = lines.map((t, i) => `BT /F1 14 Tf 72 ${720 - i * 22} Td (${t}) Tj ET`).join("\n");
    const objs = [
      "<< /Type /Catalog /Pages 2 0 R >>",
      "<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
      "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
      "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>",
      `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    ];
    let out = "%PDF-1.4\n";
    const at = [];
    objs.forEach((o, i) => {
      at.push(out.length);
      out += `${i + 1} 0 obj\n${o}\nendobj\n`;
    });
    const xref = out.length;
    out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
    out += at.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("");
    out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
    return new Blob([out], { type: "application/pdf" });
  };
  const fakeSha = (s) => [...s].reduce((h, c) => h + c.charCodeAt(0).toString(16), "").padEnd(64, "0").slice(0, 64);
  const fileIngest = (state, o = {}) => ({ state, failures: state === "failed" ? 1 : 0, error: null, kind: "pdf", pages: null, pages_read: null, truncated: false, text_chars: 0, searchable: false, ...o });
  const seedFile = (name, blob, ingest, text) => {
    const sha = fakeSha(name);
    userBlobs.set(sha, URL.createObjectURL(blob));
    return { sha256: sha, mime: blob.type, size: blob.size, filename: name, ingest, _text: text };
  };
  {
    const t = new Date(Date.now() - 3 * 3600e3).toISOString();
    const MINUTES = ["Controls sync, 21 October", "1. ibek 4.1: release on Friday", "2. Spare IOC power supply: ordered", "3. K3s upgrade: next sprint"];
    const minutes = seedFile("sync minutes.pdf", pdfBlob(MINUTES), fileIngest("done", { pages: 1, pages_read: 1, text_chars: 120, searchable: true }), MINUTES.join("\n"));
    const notes = seedFile("rack notes.md", new Blob(["# Rack notes\n\n- PSU in slot 3\n- spare fuse in the drawer\n"], { type: "text/markdown" }), fileIngest("done", { kind: "text", text_chars: 60, searchable: true }));
    const img1 = { sha256: "81fdcce0010c5ab1c03ac3ed241595b321d55aa1db5caa10d6b9f5da34d79a15", mime: "image/jpeg", size: 77229, filename: "whiteboard.jpg", ingest: { state: "done", failures: 0, error: null, text: null, description: "The architecture whiteboard again, for this test.", image_kind: "whiteboard", drawing: null } };
    const img2 = { sha256: "0b603180d1b9ef921a637e6ca28ab6c19fc52bf123e1db6162ccae4fc15342f5", mime: "image/jpeg", size: 55439, filename: "IMG_2050.jpg", ingest: { state: "done", failures: 0, error: null, text: null, description: "A garden border in flower.", image_kind: "photo", drawing: null } };
    const link = (b) => `[${b.filename}](/api/blobs/${b.sha256})`;
    const embed = (b) => `![](/api/blobs/${b.sha256}/preview?size=2048)`;
    const body = [
      "Two photos and two files, each where it was put: tap Edit to see a token and a chip for each.",
      embed(img1),
      "The minutes from the sync, read for search:",
      link(minutes),
      embed(img2),
      "And the rack notes, a Markdown file:",
      link(notes),
    ].join("\n\n");
    pages.push({
      id: "01M5SIMEMBEDS0000000000001", slug: "embedded-items-test", title: "Embedded items test", body, kind: "note", kind_fixed: 0, fields: {},
      created_at: t, updated_at: t, due: null, priority: null, snoozed_until: null, rev: 3, tags: ["sim"],
      captures: [{ id: "01M5SIMEMBEDSCAP000000001", kind: "photo", text: null, url: null, source: "pwa", author: "you", created_at: t, received_at: t, blobs: [img1, minutes, img2, notes] }],
      removed: [], tasks: { done: 0, total: 0 },
    });
    // A page with files still listed below its text (before the one-off sweep), one that
    // couldn't be read this time and one waiting
    const t2 = new Date(Date.now() - 26 * 3600e3).toISOString();
    const scan = seedFile("boiler certificate.pdf", pdfBlob(["Gas safety record"]), fileIngest("failed", { error: "timeout: the reader took over 60 s" }));
    const manual = seedFile("boiler manual.pdf", pdfBlob(["Combi boiler manual"]), fileIngest("queued"));
    pages.push({
      id: "01M5SIMEMBEDS0000000000002", slug: "boiler-papers", title: "Boiler papers", body: "The boiler's certificate and manual, for the plumber.", kind: "note", kind_fixed: 0, fields: {},
      created_at: t2, updated_at: t2, due: null, priority: null, snoozed_until: null, rev: 1, tags: ["house"],
      captures: [{ id: "01M5SIMEMBEDSCAP000000002", kind: "file", text: null, url: null, source: "pwa", author: "you", created_at: t2, received_at: t2, blobs: [scan, manual] }],
      removed: [], tasks: { done: 0, total: 0 },
    });
    for (const id of ["01M5SIMEMBEDS0000000000001", "01M5SIMEMBEDS0000000000002"]) sources.set(id, "pwa");
  }
  // A capture's (or an edit's) tokens for its files, as the server's helpers.placed
  const placeTokens = (text, blobs) =>
    text.replace(/⟦(?:image|file) ([1-9]\d{0,3})(?::[^⟦⟧\n]*)?⟧/g, (m, n, off) => {
      const b = blobs[Number(n) - 1];
      if (!b) return m;
      if (b.mime.startsWith("image/")) return `![](/api/blobs/${b.sha256}/preview?size=2048)`;
      const label = (b.filename || "").replace(/[[\]\\]/g, "").replace(/\s+/g, " ").trim() || "file";
      const l = `[${label}](/api/blobs/${b.sha256})`;
      return off && text[off - 1] === "!" ? ` ${l}` : l;
    });
  // A file the sim was given: its blob row, read as the server reads it (a PDF's text,
  // after a moment; an image by "Claude")
  const readable = (mime) => ["application/pdf", "text/plain", "text/markdown"].includes(mime);
  async function simBlob(file) {
    const sha = await sha256(file);
    userBlobs.set(sha, URL.createObjectURL(file));
    const mime = file.type || (/\.md$/i.test(file.name) ? "text/markdown" : "application/octet-stream");
    const b = { sha256: sha, mime, size: file.size, filename: file.name || null, ingest: null };
    if (mime.startsWith("image/")) {
      b.ingest = { state: "queued", failures: 0, error: null, text: null, description: null, image_kind: null, drawing: null };
      setTimeout(() => {
        b.ingest = { ...b.ingest, state: "done", image_kind: "photo", description: "A photo you took in the sim. In the real app, Claude describes it here and reads any text in it." };
      }, 6000);
    } else if (readable(mime)) {
      const pdf = mime === "application/pdf";
      b.ingest = fileIngest("queued", { kind: pdf ? "pdf" : "text" });
      setTimeout(() => (b.ingest = { ...b.ingest, state: "processing" }), 1500);
      setTimeout(() => {
        b.ingest = { ...b.ingest, state: "done", pages: pdf ? 1 : null, pages_read: pdf ? 1 : null, searchable: true, text_chars: 100 };
        b._text = `(The sim doesn't read PDFs: scrap would show the text it read from ${file.name} here.)`;
      }, 4000);
    }
    return b;
  }

  const live = () => pages.filter((p) => !trash.has(p.id));
  const byKey = (k) => pages.find((p) => p.id === k || p.slug === k);
  const DEFAULTS = {
    todo: { status: "open" },
    consume: { subtype: "read", status: "open" },
  };
  const slugify = (s) =>
    (s || "untitled")
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[^\w\s-]/g, "")
      .trim()
      .replace(/[\s_]+/g, "-")
      .slice(0, 60) || "untitled";
  const uniqueSlug = (s, id) => {
    let slug = slugify(s);
    let n = 2;
    while (pages.some((p) => p.slug === slug && p.id !== id)) slug = `${slugify(s)}-${n++}`;
    return slug;
  };
  const summary = (p) => {
    const {
      id, slug, title, kind, kind_fixed, fields, created_at, updated_at, due, priority,
    } = p;
    return {
      id, slug, title, kind, kind_fixed, fields, created_at, updated_at,
      due: kind === "todo" ? due : null,
      priority: kind === "todo" ? priority : null,
      snoozed_until: kind === "todo" ? p.snoozed_until ?? null : null,
      tasks: countTasks(p.body),
      thumb: thumbOf(p),
    };
  };
  // Task boxes as the server counts them: a list item's first line starting [ ] or [x], not in code
  const TASK = /^(\s*(?:[-*+]|\d+[.)])\s+)\[([ xX])\]/;
  const countTasks = (body) => {
    let done = 0;
    let total = 0;
    let fence = null;
    for (const line of body.split("\n")) {
      const f = /^\s*(```|~~~)/.exec(line);
      if (f) {
        if (!fence) fence = f[1];
        else if (line.trim().startsWith(fence)) fence = null;
        continue;
      }
      if (fence) continue;
      const m = TASK.exec(line);
      if (m) {
        total++;
        if (m[2] !== " ") done++;
      }
    }
    return { done, total };
  };
  // A note nobody filed with boxes is a todo; the last box ticked closes it, one unticked reopens it
  const fileByBoxes = (p, before, statusSent) => {
    const t = countTasks(p.body);
    if (!t.total) return;
    if (p.kind === "note" && !p.kind_fixed) {
      p.kind = "todo";
      p.fields = { ...p.fields, status: t.done === t.total ? "done" : "open" };
      return;
    }
    if (p.kind !== "todo" || statusSent || p.fields.status === "cancelled") return;
    if (t.done === t.total && p.fields.status !== "done") p.fields = { ...p.fields, status: "done" };
    else if (t.done < t.total && p.fields.status === "done" && before && before.total && before.done === before.total)
      p.fields = { ...p.fields, status: "open" };
  };
  const thumbOf = (p) => {
    const m = /\/api\/blobs\/([0-9a-f]{64})/.exec(p.body);
    if (m) return m[1];
    for (const c of p.captures) for (const b of c.blobs) if (b.mime.startsWith("image/")) return b.sha256;
    return null;
  };
  // What Claude added to text pages (enrich): a summary and related pages, on the notes
  const ENRICH = {
    "scrap-design-notes": {
      summary: "Design notes for the scrap PWA: capture comes first, originals are kept, and the common action is one tap. Lists the open questions about Todos and search, and sketches the capture path from phone to SQLite.",
      related: ["2026-10-21-13-52", "body-text-for-the-long-title-check"],
    },
    "2026-10-21-13-52": {
      summary: null, // a board has none: its write-up says what it shows
      related: ["scrap-design-notes"],
    },
    // The owner's todo with long Claude tags: Related too, to compare chip sizes against
    "pick-a-developer-portal-for-the-controls-group": {
      summary: "Choose a developer portal for the controls group: compare Backstage and the others against the group's needs.",
      related: ["controls-roadmap-for-the-winter-shutdown", "controls-backstage-trial-notes"],
    },
    // One Claude couldn't read, to show the failed state
    "weekly-controls-sync": { state: "failed", error: "fetch: the link timed out", summary: null, related: [] },
  };
  const enrichOf = (p) => {
    if (p.slug === "pinned") return null; // the Pinned page (the pins mock): only links, nothing to read
    const e = ENRICH[p.slug];
    // Claude reads text pages: not one that is a photo or a file
    const text = !p.captures.some((c) => c.blobs?.length);
    if (!e) return p.kind === "note" && text ? { on: true, state: null, error: null, summary: null } : null;
    return { on: true, state: e.state ?? "done", error: e.error ?? null, summary: e.summary };
  };
  const relatedOf = (p) =>
    (ENRICH[p.slug]?.related ?? []).map((slug) => pages.find((q) => q.slug === slug)).filter(Boolean)
      .map((q) => ({ id: q.id, slug: q.slug, title: q.title, kind: q.kind, via: "claude" }));
  window.__simEnrich = ENRICH;
  // Claude's write-up of a board page (writeup.ts)
  const WRITEUP = {
    "2026-10-21-13-52": {
      version: 1, producer: "claude-opus-5-5", created_at: new Date(Date.now() - 3 * 3600e3).toISOString(),
      prompt_version: "1", guidance: null, restored_from: null, links: ["scrap-design-notes"],
      summary: "scrap's capture path: the PWA posts to FastAPI, which stores pages in SQLite and hands photos to an ingest worker that asks Claude to read them.",
      text: "## How the parts connect\n\n- The **PWA** sends every capture to **FastAPI**, queued on the phone while offline.\n- FastAPI writes pages to **SQLite** and puts photos on the **Ingest** queue.\n- Ingest asks **Claude** to read, summarise and redraw, and writes the results back.\n\nThe note *v0: one process, no login* says all of this runs as a single server. See [[scrap-design-notes]].",
    },
  };
  const writeupOf = (p) => {
    const board = p.kind === "whiteboard";
    const cur = WRITEUP[p.slug] ?? null;
    if (!board && !cur) return null;
    return { board, on: true, guidance: null, state: cur ? "done" : null, error: null, versions: cur ? 1 : 0, current: cur };
  };
  // ---------- topics (#261): Claude's topic pages, their sources, and each one's area
  const TOPICS = window.__SIM_TOPICS || {};
  const topicSources = (p) => (TOPICS[p.slug]?.sources ?? []).map((slug) => pages.find((q) => q.slug === slug)).filter((q) => q && !trash.has(q.id));
  // The top-level tag most common among its sources (ties: the first by name), null if none
  const areaOf = (p) => {
    const n = new Map();
    for (const q of topicSources(p)) for (const t of new Set(q.tags.map((x) => x.split("/")[0]))) n.set(t, (n.get(t) || 0) + 1);
    return [...n].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0]?.[0] ?? null;
  };
  const topicOf = (p) => {
    const t = TOPICS[p.slug];
    if (!t) return null;
    return { key: t.key, sources: topicSources(p).map((q) => ({ id: q.id, slug: q.slug, title: q.title, kind: q.kind, added_by: "claude", added_at: p.created_at, excluded: 0 })) };
  };
  const topicsOf = (p) => Object.keys(TOPICS).map((slug) => pages.find((q) => q.slug === slug)).filter((t) => t && !trash.has(t.id) && TOPICS[t.slug].sources.includes(p.slug)).map((t) => ({ id: t.id, slug: t.slug, title: t.title }));
  const topicWriteup = (p) => {
    const t = TOPICS[p.slug];
    return { board: false, topic: true, on: true, guidance: null, state: "done", error: null, versions: 1,
      current: { version: 1, producer: "claude-opus-5-5", created_at: p.updated_at, prompt_version: "1", guidance: null, restored_from: null, links: [], summary: t.summary, text: t.text } };
  };
  const full = (p) => ({ ...p, ...summary(p), tags: tagOrder(p.tags), enrich: enrichOf(p), related: relatedOf(p),
    writeup: TOPICS[p.slug] ? topicWriteup(p) : writeupOf(p), topic: topicOf(p), topics: topicsOf(p) });
  const tagCount = () => {
    const n = new Map();
    for (const p of live()) for (const t of p.tags) n.set(t, (n.get(t) || 0) + 1);
    return n;
  };
  const tagOrder = (tags) => {
    const n = tagCount();
    return [...tags].sort((a, b) => (n.get(b) || 0) - (n.get(a) || 0) || a.localeCompare(b));
  };
  const cleanTag = (t) => String(t).trim().replace(/^#+/, "").replace(/\s+/g, " ").toLowerCase();

  // ---------- search
  const KIND = { later: "consume", read: "consume", board: "whiteboard", doc: "document" };
  const words = (s) => (s.toLowerCase().match(/[\p{L}\p{N}]+/gu) || []);
  const hay = (p) => {
    const ing = p.captures.flatMap((c) => c.blobs.map((b) => `${b.ingest?.text || ""} ${b.ingest?.description || ""}`));
    const body = p.body.replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1");
    return {
      title: p.title.toLowerCase(),
      tags: p.tags.join(" ").toLowerCase(),
      summary: String(p.fields.summary || "").toLowerCase(),
      all: `${p.title} ${p.tags.join(" ")} ${p.fields.summary || ""} ${body} ${ing.join(" ")}`.toLowerCase(),
      body,
    };
  };
  const hasPrefix = (text, w) => words(text).some((x) => x.startsWith(w));
  const hasWord = (text, w) => words(text).includes(w);
  const relDay = (v) => {
    const today = localDay();
    const d = { today, tomorrow: localDay(new Date(Date.now() + dayMs)), yesterday: localDay(new Date(Date.now() - dayMs)) }[v];
    if (d) return d;
    // days from today: 7d, 2w, 1m (30 days), y; the number 1 to 100, left out for 1
    const rel = /^(\d{0,3})([dwmy])$/.exec(v);
    if (rel) {
      const n = rel[1] ? Number(rel[1]) : 1;
      if (n < 1 || n > 100) return null;
      return localDay(new Date(Date.now() + n * { d: 1, w: 7, m: 30, y: 365 }[rel[2]] * dayMs));
    }
    return /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null;
  };
  const ago = (v) => {
    if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return v;
    const m = /^(\d+)([dwmy])$/.exec(v);
    if (!m) return null;
    const days = Number(m[1]) * { d: 1, w: 7, m: 30, y: 365 }[m[2]];
    return new Date(Date.now() - days * dayMs).toISOString().slice(0, 10);
  };
  const PRI = { high: 0, medium: 1, low: 2 };

  function parseQuery(q) {
    const toks = [];
    const re = /(-|!)?(?:([a-z]+):)?("[^"]*"?|\S+)/gi;
    let m;
    while ((m = re.exec(q))) {
      const [token, neg, key, raw] = m;
      const value = raw.startsWith('"') ? raw.replace(/^"|"$/g, "") : raw;
      toks.push({ token, neg: !!neg, key: key ? key.toLowerCase() : null, value, phrase: raw.startsWith('"') });
    }
    return toks;
  }
  const FILTERS = new Set(["kind", "tag", "is", "has", "image", "after", "before", "date", "due", "priority", "sort", "media", "later"]);

  function run(q) {
    const toks = parseQuery(q || "");
    let sort = null;
    let sortNeg = false;
    let created = false;
    const groups = { kind: [], priority: [] };
    const tests = [];
    const textWords = [];
    const active = [];
    for (const t of toks) {
      if (t.key === "group") continue; // the app's (it groups the results), never a filter
      if (t.key && FILTERS.has(t.key)) {
        active.push({ token: t.token, key: t.key, value: t.value, neg: t.neg });
        const v = t.value.toLowerCase();
        const add = (f) => tests.push(t.neg ? (p) => !f(p) : f);
        switch (t.key) {
          case "sort":
            sort = v;
            sortNeg = t.neg;
            break;
          case "date":
            if (v === "created") created = true;
            break;
          case "kind":
            if (t.neg) add((p) => p.kind === (KIND[v] || v));
            else groups.kind.push(KIND[v] || v);
            break;
          case "priority":
            if (t.neg) add((p) => (p.kind === "todo" ? p.priority || "none" : null) === (v === "urgent" ? "high" : v));
            else groups.priority.push(v === "urgent" ? "high" : v);
            break;
          case "tag":
            add((p) => p.tags.some((x) => `/${x}/`.includes(`/${v}/`)));
            break;
          case "is":
            add((p) =>
              v === "personal"
                ? p.fields.personal === true
                : v === "work"
                  ? p.fields.personal !== true
                  : v === "claude"
                    ? sources.get(p.id) === "mcp"
                    : v === "topic"
                      ? p.kind === "topic"
                    : v === "snoozed"
                      ? p.kind === "todo" && !!p.snoozed_until && p.snoozed_until > localDay()
                      : String(p.fields.status || "") === v,
            );
            break;
          case "media": // a Later's medium: book, article, film, tv, video, podcast, music, game
            add((p) => p.kind === "consume" && String(p.fields.media_type || "") === v);
            break;
          case "later": // a Later's subtype: read, watch, listen, play
            add((p) => p.kind === "consume" && String(p.fields.subtype || "read") === v);
            break;
          case "has":
            add((p) =>
              v === "image"
                ? p.captures.some((c) => c.blobs.some((b) => b.mime.startsWith("image/")))
                : v === "drawing"
                  ? p.captures.some((c) => c.blobs.some((b) => b.ingest?.drawing))
                  : false,
            );
            break;
          case "image":
            add((p) => p.captures.some((c) => c.blobs.some((b) => b.ingest?.image_kind === v)));
            break;
          case "after":
          case "before": {
            const d = ago(v);
            const key = t.key;
            add((p) => {
              if (!d) return false;
              const day = (created ? p.created_at : p.updated_at).slice(0, 10);
              return key === "after" ? day >= d : day <= d;
            });
            break;
          }
          case "due": {
            const m2 = /^(<=|>=|<|>)?(.*)$/.exec(v);
            const op = m2[1] || "=";
            const d = m2[2] === "none" ? "none" : relDay(m2[2]);
            add((p) => {
              if (p.kind !== "todo" || !d) return false;
              if (d === "none") return !p.due;
              if (!p.due) return false;
              return { "=": p.due === d, "<": p.due < d, "<=": p.due <= d, ">": p.due > d, ">=": p.due >= d }[op];
            });
            break;
          }
        }
      } else if (t.phrase) {
        const ph = t.value.toLowerCase();
        tests.push(t.neg ? (p) => !hay(p).all.includes(ph) : (p) => hay(p).all.includes(ph));
        if (!t.neg) textWords.push(...words(ph));
      } else {
        const ws = words(t.value).slice(0, 16);
        for (const w of ws) {
          if (t.neg) tests.push((p) => !hasWord(hay(p).all, w));
          else {
            textWords.push(w);
            tests.push((p) => hasPrefix(hay(p).all, w));
          }
        }
      }
    }
    if (groups.kind.length) tests.push((p) => groups.kind.includes(p.kind));
    if (groups.priority.length)
      tests.push((p) => p.kind === "todo" && groups.priority.includes(p.priority || "none"));
    const found = live().filter((p) => tests.every((f) => f(p)));
    const rank = (p) => {
      if (!textWords.length) return 0;
      const h = hay(p);
      if (textWords.every((w) => hasPrefix(h.title, w))) return 0;
      if (textWords.every((w) => hasPrefix(`${h.title} ${h.tags} ${h.summary}`, w))) return 1;
      return 2;
    };
    const cmp = {
      updated: (a, b) => b.updated_at.localeCompare(a.updated_at),
      created: (a, b) => b.created_at.localeCompare(a.created_at),
      title: (a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase()),
      due: (a, b) => {
        const x = a.kind === "todo" && a.due;
        const y = b.kind === "todo" && b.due;
        if (!x || !y) return (x ? -1 : 0) - (y ? -1 : 0);
        return x.localeCompare(y);
      },
      priority: (a, b) => {
        const x = a.kind === "todo" && a.priority ? PRI[a.priority] : 9;
        const y = b.kind === "todo" && b.priority ? PRI[b.priority] : 9;
        return x - y;
      },
    };
    if (sort && cmp[sort]) {
      const base = cmp[sort];
      const last = sort === "due" || sort === "priority";
      found.sort((a, b) => {
        let r = base(a, b);
        if (sortNeg) {
          if (last) {
            const missing = (p) => (sort === "due" ? !(p.kind === "todo" && p.due) : !(p.kind === "todo" && p.priority));
            if (missing(a) !== missing(b)) return missing(a) ? 1 : -1;
          }
          r = -r;
        }
        return r || cmp.updated(a, b);
      });
    } else if (textWords.length) found.sort((a, b) => rank(a) - rank(b) || cmp.updated(a, b));
    else found.sort(cmp.created);
    return { found, textWords, active };
  }

  const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  function snippet(p, ws) {
    const h = hay(p);
    const plain = (p.fields.summary || h.body || "").replace(/[#*_`>|-]+/g, " ").replace(/\s+/g, " ").trim();
    let text = plain;
    if (ws.length) {
      const low = plain.toLowerCase();
      let at = -1;
      for (const w of ws) {
        const re = new RegExp(`(^|[^\\p{L}\\p{N}])${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`, "u");
        const m = re.exec(low);
        if (m && (at < 0 || m.index < at)) at = m.index;
      }
      if (at > 40) text = `…${plain.slice(at - 30)}`;
    }
    text = text.slice(0, 160) + (text.length > 160 ? "…" : "");
    let out = esc(text);
    for (const w of ws) {
      const re = new RegExp(`(^|[^\\p{L}\\p{N}>])(${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}[\\p{L}\\p{N}]*)`, "giu");
      out = out.replace(re, "$1<mark>$2</mark>");
    }
    return out;
  }

  // ---------- the API
  const json = (body, status = 200) =>
    new Response(status === 204 ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  const err = (status, detail, extra = {}) => json({ detail, ...extra }, status);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const blobFile = (sha, size) => {
    if (userBlobs.has(sha)) return userBlobs.get(sha);
    return new URL(size ? `blobs/${sha}-${size}.jpg` : `blobs/${sha}`, BASE).href;
  };
  const realFetch = window.fetch.bind(window);

  function md(p) {
    const fm = [`title: ${JSON.stringify(p.title)}`, `kind: ${p.kind}`];
    if (p.tags.length) fm.push(`tags: [${p.tags.join(", ")}]`);
    if (p.kind === "todo" && p.due) fm.push(`due: ${p.due}`);
    if (p.kind === "todo" && p.priority) fm.push(`priority: ${p.priority}`);
    return `---\n${fm.join("\n")}\n---\n\n${p.body}\n`;
  }

  function patchPage(p, b) {
    if ("title" in b || "body" in b) {
      if (b.base_rev !== p.rev) return err(409, "the page changed since you opened it", { rev: p.rev });
    }
    if (b.kind !== undefined) {
      p.kind = b.kind;
      p.kind_fixed = 1;
      p.fields = { ...(DEFAULTS[b.kind] || {}), ...p.fields };
    }
    if (b.fields) {
      const f = { ...p.fields };
      for (const [k, v] of Object.entries(b.fields)) {
        if (v === null) delete f[k];
        else f[k] = v;
      }
      p.fields = f;
    }
    if (b.tags) {
      const t = [...new Set(b.tags.map(cleanTag).filter(Boolean))];
      if (t.some((x) => x.length > 64) || t.length > 64) return err(422, "bad tags");
      p.tags = t;
    }
    for (const k of ["due", "priority", "snoozed_until"]) {
      if (b[k] === undefined) continue;
      if (b[k] !== null && p.kind !== "todo") return err(422, `${k} is a todo's only`);
      p[k] = b[k];
    }
    let rev = false;
    if (typeof b.title === "string" && b.title !== p.title) {
      p.title = b.title.trim() || p.title;
      p.slug = uniqueSlug(p.title, p.id);
      rev = true;
    }
    if (typeof b.body === "string" && b.body !== p.body) {
      if (new TextEncoder().encode(b.body).length > 1_000_000) return err(422, "a page holds at most 1 MB of text");
      const before = countTasks(p.body);
      p.body = b.body;
      rev = true;
      fileByBoxes(p, before, !!b.fields?.status);
    }
    if (rev) {
      p.rev += 1;
      p.updated_at = nowIso();
    }
    return json(full(p));
  }

  async function handle(method, url, body) {
    const path = url.pathname;
    const qs = url.searchParams;
    let m;
    await wait(40 + Math.random() * 60); // a little like a real network
    if (path === "/healthz") return json({ status: "ok", version: "sim", max_upload_bytes: 52428800 });
    if (path === "/api/pages" && method === "GET") {
      const kind = qs.get("kind");
      const limit = Number(qs.get("limit") || 50);
      const list = live()
        .filter((p) => !kind || p.kind === kind)
        .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
        .slice(0, limit)
        .map(summary);
      return json(list);
    }
    if ((m = /^\/api\/pages\/([^/]+)\/enrich$/.exec(path)) && method === "POST") {
      // Ask Claude: queued, then read a few seconds later
      const p = byKey(decodeURIComponent(m[1]));
      if (!p) return err(404, "no such page");
      const e = (ENRICH[p.slug] ??= { summary: null, related: [] });
      e.state = "queued";
      setTimeout(() => (e.state = "processing"), 1500);
      setTimeout(() => {
        e.state = "done";
        e.summary ??= `A short note: ${p.title}.`;
      }, 4000);
      return json(full(p));
    }
    if (path === "/api/health" && method === "GET")
      return json({ checks: [["is:orphan", 7], ["is:untagged", 12], ["is:stale", 2], ["is:duplicate", 0], ["has:dangling", 1], ["is:outdated", 3]].map(([term, count]) => ({ term, count })) });
    if (path === "/api/trash" && method === "GET") {
      const t = pages.filter((p) => trash.has(p.id)).map((p) => ({ id: p.id, slug: p.slug, title: p.title, kind: p.kind, deleted_at: nowIso(), topic: p.kind === "topic", purge_at: "2026-11-26T00:00:00Z" }));
      const extra = window.__TRASH_EMPTY ? [] : pages.slice(0, 5).map((p, i) => ({ id: "x" + i, slug: p.slug, title: p.title, kind: p.kind, deleted_at: "2026-10-2" + i + "T10:00:00Z", topic: false, purge_at: "2026-11-2" + i + "T10:00:00Z" }));
      return json({ days: 30, total: t.length + extra.length, results: [...t, ...extra] });
    }
    if (path === "/api/pinned" && method === "GET") {
      // The Pinned page (pins.ts): null while there is none
      const p = byKey("pinned");
      return json(p && !trash.has(p.id) ? full(p) : null);
    }
    if ((m = /^\/api\/pages\/([^/]+)$/.exec(path))) {
      const p = byKey(decodeURIComponent(m[1]));
      if (!p || (trash.has(p.id) && method !== "GET")) return err(404, "no such page");
      if (method === "GET") return trash.has(p.id) ? err(404, "no such page") : json(full(p));
      if (method === "PATCH" && body instanceof FormData) {
        // An edit with files (pages_api): the edit as JSON, its files placed where their tokens are
        const edit = JSON.parse(body.get("edit") || "{}");
        if (edit.base_rev !== p.rev) return err(409, "the page changed since you opened it", { rev: p.rev });
        const blobs = [];
        for (const f of body.getAll("file")) blobs.push(await simBlob(f));
        const images = blobs.some((b) => b.mime.startsWith("image/"));
        p.captures.push({ id: `SIMEDIT${Date.now().toString(36).toUpperCase()}`, kind: images ? "photo" : "file", text: null, url: null, source: "pwa", author: "you", created_at: nowIso(), received_at: nowIso(), blobs });
        edit.body = placeTokens(edit.body || "", blobs);
        return patchPage(p, edit);
      }
      if (method === "PATCH") return patchPage(p, body || {});
      if (method === "DELETE") {
        trash.add(p.id);
        return json(null, 204);
      }
    }
    if ((m = /^\/api\/pages\/([^/]+)\/undelete$/.exec(path)) && method === "POST") {
      const p = byKey(decodeURIComponent(m[1]));
      if (!p) return err(404, "no such page");
      trash.delete(p.id);
      return json(full(p));
    }
    if ((m = /^\/api\/pages\/([^/]+)\/download$/.exec(path))) {
      const p = byKey(decodeURIComponent(m[1]));
      if (!p) return err(404, "no such page");
      return new Response(md(p), {
        headers: {
          "Content-Type": "text/markdown",
          "Content-Disposition": `attachment; filename="${p.slug}.md"`,
        },
      });
    }
    // A capture posted with fetch (the Pinned page, made on the first pin: pins.ts); the
    // composer's go by XMLHttpRequest, below
    if (path === "/api/captures" && method === "POST") {
      const [status, res] = await capture(JSON.stringify(body || {}));
      return json(res, status);
    }
    if (path === "/api/search") {
      const { found, textWords } = run(qs.get("q") || "");
      const off = Number(qs.get("offset") || 0);
      const lim = Math.min(Number(qs.get("limit") || 20), 100);
      return json(
        found.slice(off, off + lim).map((p) => {
          const s = summary(p);
          return {
            id: s.id, slug: s.slug, title: s.title, kind: s.kind, fields: s.fields,
            due: s.due, priority: s.priority, snoozed_until: s.snoozed_until, tasks: s.tasks, snippet: snippet(p, textWords),
            updated_at: s.updated_at, thumb: s.thumb,
            tags: p.tags, // the mock's: group:tag sections the hits by them in the app
            ...(TOPICS[p.slug] && { topic: true, area: areaOf(p) }), // area: the server would add it
          };
        }),
      );
    }
    if (path === "/api/search/facets") {
      const { found, active } = run(qs.get("q") || "");
      const kinds = new Map();
      const tags = new Map();
      let personal = 0;
      for (const p of found) {
        kinds.set(p.kind, (kinds.get(p.kind) || 0) + 1);
        if (p.fields.personal === true) personal++;
        const all = new Set();
        for (const t of p.tags) {
          const parts = t.split("/");
          for (let i = 1; i <= parts.length; i++) all.add(parts.slice(0, i).join("/"));
        }
        for (const t of all) tags.set(t, (tags.get(t) || 0) + 1);
      }
      const asked = new Set(active.filter((a) => a.key === "tag").map((a) => a.value.toLowerCase()));
      const top = [...tags]
        .filter(([t, n]) => !asked.has(t) && n < found.length)
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .slice(0, Math.min(Number(qs.get("top") || 12), 1000));
      return json({
        total: found.length,
        kinds: [...kinds].sort((a, b) => b[1] - a[1]),
        tags: top,
        personal: { work: found.length - personal, personal },
        active,
      });
    }
    if (path === "/api/topics") {
      // The topics index: each one's area, the biggest area first (then by name), no area last
      const rows = live().filter((p) => TOPICS[p.slug]).map((p) => ({ id: p.id, slug: p.slug, title: p.title,
        summary: TOPICS[p.slug].summary, sources: topicSources(p).length, updated_at: p.updated_at, area: areaOf(p) }));
      const size = new Map();
      for (const r of rows) size.set(r.area, (size.get(r.area) || 0) + 1);
      rows.sort((a, b) => (a.area === null) - (b.area === null) || size.get(b.area) - size.get(a.area) ||
        String(a.area).localeCompare(String(b.area)) || b.updated_at.localeCompare(a.updated_at));
      return json(rows);
    }
    if (path === "/api/tags") {
      const n = new Map();
      const own = tagCount();
      for (const p of live()) {
        const all = new Set();
        for (const t of p.tags) {
          const parts = t.split("/");
          for (let i = 1; i <= parts.length; i++) all.add(parts.slice(0, i).join("/"));
        }
        for (const t of all) n.set(t, (n.get(t) || 0) + 1);
      }
      return json([...n].sort((a, b) => a[0].localeCompare(b[0])).map(([t, c]) => [t, c, own.get(t) || 0]));
    }
    if (path === "/api/ingest")
      return json({ enabled: true, paused: false, reason: null, paused_until: null, jobs: {}, spent_today_usd: 0.42 });
    if (path === "/api/ingest/resume") return json({ enabled: true, paused: false, reason: null, paused_until: null });
    if ((m = /^\/api\/captures\/([^/]+)\/files\/([0-9a-f]+)\/text$/.exec(path))) {
      const b = pages.flatMap((p) => p.captures).find((c) => c.id === m[1])?.blobs.find((x) => x.sha256 === m[2]);
      if (!b || b.mime !== "application/pdf") return err(404, "no such PDF");
      return json({ text: b.ingest?.state === "done" ? (b._text ?? null) : null, truncated: false });
    }
    if ((m = /^\/api\/captures\/([^/]+)\/reprocess$/.exec(path))) {
      for (const p of pages)
        for (const c of p.captures)
          if (c.id === m[1])
            for (const b of c.blobs) {
              if (body?.photo && body.photo !== b.sha256) continue;
              if (b.ingest && "kind" in b.ingest) {
                b.ingest = { ...b.ingest, state: "processing", error: null };
                setTimeout(() => {
                  b.ingest = { ...b.ingest, state: "done", failures: 0, pages: b.ingest.kind === "pdf" ? 1 : null, pages_read: b.ingest.kind === "pdf" ? 1 : null, searchable: true, text_chars: 40 };
                  b._text ??= `(The sim doesn't read PDFs: scrap would show the text it read from ${b.filename} here.)`;
                }, 3000);
                continue;
              }
              b.ingest = { ...(b.ingest || { failures: 0, error: null, text: null, description: null, image_kind: null, drawing: null }), state: "processing" };
              const done = { ...b.ingest };
              setTimeout(() => {
                b.ingest = { ...done, state: "done", description: done.description || "A photo (described by Claude in the real app)." };
              }, 4000);
            }
      return json({ queued: 1, already: 0 });
    }
    if ((m = /^\/api\/captures\/([^/]+)\/photos\/([0-9a-f]+)\/drawing(\/versions|\/restore)?$/.exec(path))) {
      const key = `${m[1]}/${m[2]}`;
      const d = drawings[key];
      const blob = pages.flatMap((p) => p.captures).find((c) => c.id === m[1])?.blobs.find((b) => b.sha256 === m[2]);
      const setCurrent = (cur) => {
        if (blob?.ingest) blob.ingest.drawing = { id: cur.id, version: cur.version, producer: cur.producer, width: cur.data.width, height: cur.data.height };
      };
      if (m[3] === "/versions") return d ? json(d.versions) : json([]);
      if (method === "GET") return d ? json(d.current) : err(404, "no drawing");
      if (m[3] === "/restore") {
        if (!d) return err(404, "no drawing");
        if (body.base_version !== d.current.version) return err(409, "the drawing changed", { version: d.current.version });
        const old = d.versionData?.[body.version] || d.current.data;
        const v = d.current.version + 1;
        const cur = { ...d.current, id: d.current.id + 1, version: v, producer: "human", author: "you", created_at: nowIso(), restored_from: body.version, data: clone(old) };
        d.versionData = { ...(d.versionData || { [d.current.version]: d.current.data }), [v]: cur.data };
        d.current = cur;
        d.versions.unshift({ ...cur, data: undefined });
        setCurrent(cur);
        return json(cur);
      }
      if (method === "PUT") {
        const cv = d ? d.current.version : null;
        if (body.base_version !== cv) return err(409, "the drawing changed", { version: cv });
        const v = (cv || 0) + 1;
        const data = { format: "scene", width: body.scene.width ?? d?.current.data.width, height: body.scene.height ?? d?.current.data.height, elements: body.scene.elements, appState: body.scene.appState || {} };
        const cur = { id: (d?.current.id || 0) + 1, version: v, producer: "human", author: "you", run_id: null, created_at: nowIso(), current: true, format: "scene", restored_from: null, data };
        if (d) {
          d.versionData = { ...(d.versionData || { [d.current.version]: d.current.data }), [v]: data };
          d.current = cur;
          d.versions.unshift({ ...cur, data: undefined });
        } else drawings[key] = { current: cur, versions: [{ ...cur, data: undefined }], versionData: { [v]: data } };
        setCurrent(cur);
        return json(cur);
      }
    }
    if ((m = /^\/api\/blobs\/([0-9a-f]+)\/uses$/.exec(path))) {
      const sha = m[1];
      const other = live().filter((p) => p.id !== qs.get("page") && (p.body.includes(sha) || p.captures.some((c) => c.blobs.some((b) => b.sha256 === sha))));
      return json({ pages: other.length });
    }
    if ((m = /^\/api\/blobs\/([0-9a-f]+)(\/preview)?$/.exec(path)))
      return realFetch(blobFile(m[1], m[2] ? Number(qs.get("size") || 2048) : 0));
    return err(404, `the sim has no ${method} ${path}`);
  }

  // ---------- captures (the app posts them with XMLHttpRequest, for upload progress)
  const ulidTime = () => new Date().toISOString();
  async function sha256(blob) {
    const h = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
    return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }
  async function capture(body) {
    let f = {};
    const files = [];
    if (body instanceof FormData) {
      for (const [k, v] of body.entries()) {
        if (k === "file") files.push(v);
        else if (k === "tags") (f.tags ||= []).push(v);
        else f[k] = v;
      }
    } else f = JSON.parse(body);
    const existing = pages.find((p) => p.captures.some((c) => c.id === f.id));
    if (existing) return [200, { capture_id: f.id, page_id: existing.id, slug: existing.slug }];
    const kind = f.kind || f.hint || null;
    if (!f.url && /^https?:\/\/\S+$/.test((f.text || "").trim())) {
      f.url = f.text.trim();
      f.text = null;
    }
    const blobs = [];
    for (const file of files) blobs.push(await simBlob(file));
    const raw = (f.text || "").replace(/\r\n/g, "\n");
    // The composer's tokens are its files' places (#403)
    const text = f.place === "1" ? placeTokens(raw, blobs) : raw;
    const first = text.split("\n").find((l) => l.trim()) || "";
    const title = (first.replace(/^#+\s*/, "").trim() || (f.url ? f.url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "") : "") || (blobs[0]?.filename ?? "Untitled")).slice(0, 120);
    const shown = (b) => text.includes(`/api/blobs/${b.sha256}`);
    const embeds = blobs.filter((b) => b.mime.startsWith("image/") && !shown(b)).map((b) => `![](/api/blobs/${b.sha256}/preview?size=2048)`);
    const others = blobs.filter((b) => !b.mime.startsWith("image/") && !shown(b)).map((b) => `[${b.filename || "file"}](/api/blobs/${b.sha256})`);
    const bodyText = [text, f.url && !text ? `<${f.url}>` : "", ...embeds, ...others].filter(Boolean).join("\n\n");
    const id = `SIM${Date.now().toString(36).toUpperCase()}${Math.random().toString(36).slice(2, 8).toUpperCase()}`;
    const t = f.created_at || ulidTime();
    const pk = kind || "note";
    const fields = { ...(DEFAULTS[pk] || {}) };
    if (pk === "consume" && f.url) fields.source = f.url;
    const p = {
      id,
      slug: uniqueSlug(title, id),
      title,
      body: bodyText,
      kind: pk,
      kind_fixed: kind ? 1 : 0,
      fields,
      created_at: nowIso(),
      updated_at: nowIso(),
      due: pk === "todo" ? f.due || null : null,
      priority: pk === "todo" ? f.priority || null : null,
      rev: 1,
      tags: [...new Set((f.tags || []).map(cleanTag).filter(Boolean))],
      captures: [{ id: f.id, kind: blobs.length ? "photo" : f.url ? "link" : "text", text: f.text || null, url: f.url || null, source: f.source || "pwa", author: "you", created_at: t, received_at: nowIso(), blobs }],
      removed: [],
    };
    fileByBoxes(p, null, false);
    pages.push(p);
    sources.set(p.id, p.captures[0].source);
    // (Claude reads new photos, and scrap a file's text, after a few seconds: simBlob)
    return [201, { capture_id: f.id, page_id: id, slug: p.slug }];
  }

  const RealXHR = window.XMLHttpRequest;
  class SimXHR extends RealXHR {
    open(method, url, ...rest) {
      const u = new URL(url, location.origin);
      this._sim = u.origin === location.origin && u.pathname === "/api/captures" ? method : null;
      this._simStatus = 0;
      this._simText = "";
      if (!this._sim) return super.open(method, url, ...rest);
      this._listeners = {};
    }
    setRequestHeader(...a) {
      if (!this._sim) return super.setRequestHeader(...a);
    }
    get status() {
      return this._sim ? this._simStatus : super.status;
    }
    get responseText() {
      return this._sim ? this._simText : super.responseText;
    }
    get readyState() {
      return this._sim ? (this._simStatus ? 4 : 1) : super.readyState;
    }
    abort() {
      if (!this._sim) return super.abort();
      this._aborted = true;
      this.onabort?.(new Event("abort"));
    }
    send(body) {
      if (!this._sim) return super.send(body);
      const up = this.upload;
      (async () => {
        await wait(150);
        if (this._aborted) return;
        if (!navigator.onLine) return this.onerror?.(new Event("error"));
        up.onprogress?.(new ProgressEvent("progress", { loaded: 1, total: 1 }));
        await wait(250);
        up.onload?.(new ProgressEvent("load"));
        try {
          const [status, res] = await capture(body);
          this._simStatus = status;
          this._simText = JSON.stringify(res);
        } catch (e) {
          console.error("sim capture", e);
          this._simStatus = 500;
          this._simText = JSON.stringify({ detail: String(e) });
        }
        if (this._aborted) return;
        this.onload?.(new ProgressEvent("load"));
        this.onloadend?.(new ProgressEvent("loadend"));
        dispatchEvent(new Event("scrap:wrote"));
      })();
    }
  }
  window.XMLHttpRequest = SimXHR;

  // ---------- fetch
  window.fetch = async (input, init = {}) => {
    const req = input instanceof Request ? input : null;
    const url = new URL(req ? req.url : String(input), location.origin);
    const sameOrigin = url.origin === location.origin;
    if (!sameOrigin || !(url.pathname.startsWith("/api/") || url.pathname === "/healthz"))
      return realFetch(input, init);
    const method = (init.method || req?.method || "GET").toUpperCase();
    let body = init.body ?? null;
    if (req && !body && method !== "GET") body = await req.text();
    if (typeof body === "string" && body) {
      try {
        body = JSON.parse(body);
      } catch {}
    }
    if (init.signal?.aborted) throw new DOMException("aborted", "AbortError");
    if (!navigator.onLine) throw new TypeError("Failed to fetch");
    try {
      return await handle(method, url, body);
    } catch (e) {
      console.error("sim", method, url.pathname, e);
      return err(500, String(e));
    }
  };

  // ---------- images and links to the API (not fetches: the page asks the host for them)
  const mapUrl = (v) => {
    if (!v) return v;
    const u = new URL(v, location.origin);
    if (u.origin !== location.origin) return v;
    const m = /^\/api\/blobs\/([0-9a-f]{64})(\/preview)?$/.exec(u.pathname);
    if (!m) return v;
    return blobFile(m[1], m[2] ? Number(u.searchParams.get("size") || 2048) : 0);
  };
  // Rewrite as the address is set, before the browser asks for it
  for (const C of [HTMLImageElement, HTMLSourceElement]) {
    for (const prop of ["src", "srcset"]) {
      const d = Object.getOwnPropertyDescriptor(C.prototype, prop);
      if (!d?.set) continue;
      Object.defineProperty(C.prototype, prop, {
        ...d,
        set(v) {
          d.set.call(this, typeof v === "string" && v.includes("/api/blobs/") ? (prop === "srcset" ? v.split(",").map((s) => s.trim().replace(/^\S+/, mapUrl)).join(", ") : mapUrl(v)) : v);
        },
      });
    }
  }
  const realSetAttr = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    if ((name === "src" || name === "srcset") && typeof value === "string" && value.includes("/api/blobs/") && (this instanceof HTMLImageElement || this instanceof HTMLSourceElement))
      value = name === "srcset" ? value.split(",").map((s) => s.trim().replace(/^\S+/, mapUrl)).join(", ") : mapUrl(value);
    return realSetAttr.call(this, name, value);
  };
  const fix = (el) => {
    if (el.nodeType !== 1) return;
    const all = el.matches?.("img,source,a,link") ? [el] : [];
    all.push(...el.querySelectorAll("img,source"));
    for (const x of all) {
      for (const a of ["src", "srcset"]) {
        const v = x.getAttribute(a);
        if (v?.includes("/api/blobs/")) {
          const nv = a === "srcset" ? v.split(",").map((s) => s.trim().replace(/^\S+/, mapUrl)).join(", ") : mapUrl(v);
          if (nv !== v) x.setAttribute(a, nv);
        }
      }
    }
  };
  new MutationObserver((recs) => {
    for (const r of recs) {
      if (r.type === "attributes") fix(r.target);
      else for (const n of r.addedNodes) fix(n);
    }
  }).observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ["src", "srcset"] });

  // Links the app leaves to the browser: downloads, files and in-page anchors
  document.addEventListener(
    "click",
    async (e) => {
      const a = e.target.closest?.("a");
      if (!a || e.defaultPrevented || e.button !== 0 || a.closest(".orig")) return;
      const href = a.getAttribute("href") || "";
      if (href.startsWith("#") && !href.startsWith("#/")) {
        e.preventDefault();
        e.stopImmediatePropagation();
        let id = href.slice(1);
        try {
          id = decodeURIComponent(id);
        } catch {}
        document.getElementById(id)?.scrollIntoView();
        return;
      }
      let u;
      try {
        u = new URL(href, location.origin);
      } catch {
        return;
      }
      if (u.origin !== location.origin) return;
      if (!u.pathname.startsWith("/api/") && u.pathname !== "/share") return;
      e.preventDefault();
      e.stopImmediatePropagation();
      const r = await window.fetch(u.pathname + u.search);
      const blob = await r.blob();
      const name = (/filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "") || [])[1] || a.getAttribute("download") || u.pathname.split("/").pop();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      if (a.hasAttribute("download") || r.headers.get("Content-Disposition")) link.download = name;
      else link.target = "_blank";
      link.click();
    },
    true,
  );

  // ---------- the share sheet: the artifact frame has none, so the app would hide Share. A
  // stand-in says what would have been shared, so the menu (Link, Text, Download) can be seen.
  const note = (text) => {
    const el = document.createElement("div");
    el.className = "sim-note";
    el.textContent = text;
    document.body.append(el);
    setTimeout(() => el.remove(), 3500);
  };
  if (!navigator.share) {
    Object.defineProperty(navigator, "share", {
      configurable: true,
      value: async (d) => {
        const what = d.files ? `a photo (${d.files[0]?.name})` : d.url ? `the link ${d.url}` : `the text of “${d.title}”`;
        note(`Sim: the share sheet would open with ${what}`);
      },
    });
    Object.defineProperty(navigator, "canShare", { configurable: true, value: () => true });
  }

  // ---------- feedback: a note about the screen in view, kept where Claude can read it
  const SCREEN = () => {
    const p = loc.pathname;
    const t = document.querySelector("#view h1")?.textContent?.trim();
    const where = p === "/" ? "Capture" : p.startsWith("/p/") ? `Page “${t ?? p.slice(3)}”` : p.slice(1).replace(/^./, (c) => c.toUpperCase());
    const extra = [
      document.body.classList.contains("editing") && "editor open",
      document.querySelector("dialog[open]") && "Filters open",
      document.querySelector(".todoedit") && "due form open",
      document.querySelector(".tagform") && "tags open",
    ].filter(Boolean);
    return `${where}${loc.search ? ` (${decodeURIComponent(loc.search)})` : ""}${extra.length ? ` · ${extra.join(", ")}` : ""}`;
  };
  const css = document.createElement("style");
  css.textContent = `
    .sim-fb { position: fixed; z-index: 50; top: 38%; right: 0; writing-mode: vertical-rl;
      font: 600 12px/1 system-ui, sans-serif; padding: 12px 7px; border-radius: 8px 0 0 8px; border: 0;
      background: #2a5bd7; color: #fff; box-shadow: 0 2px 10px rgb(0 0 0 / 25%); opacity: 0.9; }
    .sim-back { top: calc(38% - 92px); background: #3a3a3a; }
    .sim-var { top: calc(38% + 92px); background: #8a4b0f; }
    .sim-fb-pane { position: fixed; z-index: 51; inset: auto 8px 8px 8px; padding: 12px; border-radius: 14px;
      background: #fff; color: #1b1b1b; box-shadow: 0 8px 30px rgb(0 0 0 / 35%); font: 15px/1.4 system-ui, sans-serif;
      display: flex; flex-direction: column; gap: 8px; }
    .sim-fb-pane small { color: #555; }
    .sim-fb-pane textarea { min-height: 7em; font: inherit; padding: 8px; border: 1px solid #aaa; border-radius: 8px; color: #1b1b1b; background: #fff; }
    .sim-fb-pane div { display: flex; gap: 8px; justify-content: flex-end; }
    .sim-fb-pane button { font: 600 15px system-ui, sans-serif; padding: 10px 16px; border-radius: 10px; border: 1px solid #aaa; background: #fff; color: #1b1b1b; }
    .sim-fb-pane button.go { background: #2a5bd7; color: #fff; border-color: #2a5bd7; }
    .sim-note { position: fixed; z-index: 52; left: 50%; top: 56px; translate: -50% 0; max-width: 90vw;
      padding: 10px 14px; border-radius: 10px; background: #2a5bd7; color: #fff; font: 14px/1.35 system-ui, sans-serif; }`;
  document.head.append(css);
  let db = null;
  const store = () => (db ??= window.claude?.use ? window.claude.use("db").catch(() => null) : Promise.resolve(null));
  const open = () => {
    if (document.querySelector(".sim-fb-pane")) return;
    const screen = SCREEN();
    const pane = document.createElement("form");
    pane.className = "sim-fb-pane";
    pane.innerHTML = `<small></small><textarea id="sim-fb-text" placeholder="What should change here?"></textarea><div><button type="button">Cancel</button><button class="go">Send</button></div>`;
    pane.querySelector("small").textContent = `Feedback on: ${screen}`;
    const text = pane.querySelector("textarea");
    pane.querySelector("button").onclick = () => pane.remove();
    pane.onsubmit = async (e) => {
      e.preventDefault();
      const said = text.value.trim();
      if (!said) return text.focus();
      const go = pane.querySelector(".go");
      go.disabled = true;
      go.textContent = "Sending…";
      try {
        const d = await store();
        if (!d) throw new Error("this view can't save feedback");
        await d.collection("feedback").add({ at: new Date().toISOString(), screen, text: said, width: innerWidth, theme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light" });
        pane.remove();
        note("Sent: thanks");
      } catch (err) {
        go.disabled = false;
        go.textContent = "Send";
        note(`Not sent: ${err?.message ?? err}. Copy it into the chat instead.`);
      }
    };
    document.body.append(pane);
    text.focus();
  };
  // 521 mock: the design's variants, on <html> (web/src/reading.ts), kept across reloads
  const V521 = { chev: ["before", "after"], regen: ["in", "out"] };
  let m521 = {}; // where storage is refused (the artifact host may), for this visit only
  const get521 = () => {
    try {
      return JSON.parse(localStorage.getItem("sim.m521") || "{}");
    } catch {
      return m521;
    }
  };
  const set521 = (v) => {
    m521 = v;
    try {
      localStorage.setItem("sim.m521", JSON.stringify(v));
    } catch {}
  };
  const v521 = () => {
    const v = get521();
    for (const k of Object.keys(V521)) document.documentElement.dataset[`m521${k[0].toUpperCase()}${k.slice(1)}`] = V521[k].includes(v[k]) ? v[k] : V521[k][0];
  };
  v521();
  const variants = () => {
    if (document.querySelector(".sim-fb-pane")) return;
    const pane = document.createElement("div");
    pane.className = "sim-fb-pane";
    const row = (k, label, names) => {
      const d = document.createElement("div");
      d.style.cssText = "justify-content:flex-start;align-items:center;flex-wrap:wrap";
      d.append(label);
      V521[k].forEach((v, i) => {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = names[i];
        if (document.documentElement.dataset[`m521${k[0].toUpperCase()}${k.slice(1)}`] === v) b.className = "go";
        b.onclick = () => {
          set521({ ...get521(), [k]: v });
          v521();
          pane.remove();
          variants();
        };
        d.append(b);
      });
      return d;
    };
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "Close";
    close.onclick = () => pane.remove();
    const end = document.createElement("div");
    end.append(close);
    const t = document.createElement("small");
    t.textContent = "Claude's reading (#521): pick a variant, then open a fold";
    pane.append(t, row("chev", "Chevron:", ["A: before", "B: after"]), row("regen", "Regenerate:", ["A: in fold", "B: on its line"]), end);
    document.body.append(pane);
  };
  addEventListener("DOMContentLoaded", () => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "sim-fb";
    b.textContent = "Feedback";
    b.onclick = open;
    // The phone's Back gesture closes the artifact here, not a step in the app: this stands in
    const back = document.createElement("button");
    back.type = "button";
    back.className = "sim-fb sim-back";
    back.textContent = "‹ Back";
    back.onclick = () => history.back();
    const v = document.createElement("button");
    v.type = "button";
    v.className = "sim-fb sim-var";
    v.textContent = "Variants";
    v.onclick = variants;
    document.body.append(back, b, v);
  });

  // The artifact viewer blocks native dialogs: confirm() returns false at once, unseen, so
  // Cancel's "Discard your changes?" could never be answered. Unseen, it counts as yes.
  {
    const ask = window.confirm.bind(window);
    window.confirm = (m) => {
      const t = performance.now();
      const yes = ask(m);
      return yes || performance.now() - t < 50;
    };
  }
  window.__sim = { loc, base: BASE, pages, reset: () => location.reload() };
})();

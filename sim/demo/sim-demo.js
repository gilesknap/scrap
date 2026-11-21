// The demo video's additions to the sim (sim/demo/build.sh loads this after sim.js):
// hides the sim's own tabs, drops the sim-only test page that sim.js makes, and adds
// __sim.write(page), which stores a page as Claude Code's write over MCP would, so the
// recorder can make the page "Claude writes" appear in the PWA at the right moment.
(() => {
  "use strict";
  const sim = window.__sim;
  const pages = sim.pages;
  const i = pages.findIndex((p) => p.slug === "embedded-items-test");
  if (i >= 0) pages.splice(i, 1);
  // The seed's times are hours before 18:00 on today's date, so before then some are still to
  // come: move them all back so the newest is a few minutes ago, and what the demo adds is
  // at the top of Latest
  const ms = (t) => Date.parse(t) || 0;
  const ahead = Math.max(...pages.map((p) => ms(p.updated_at))) - Date.now() + 5 * 60e3;
  if (ahead > 0) {
    const back = (t) => (t ? new Date(ms(t) - ahead).toISOString() : t);
    for (const p of pages) {
      p.created_at = back(p.created_at);
      p.updated_at = back(p.updated_at);
      for (const c of p.captures) c.created_at = back(c.created_at);
    }
  }

  const style = document.createElement("style");
  style.textContent = ".sim-fb, .sim-fb-pane { display: none !important; }";
  addEventListener("DOMContentLoaded", () => document.head.append(style));

  const slugify = (s) =>
    (s || "untitled").toLowerCase().normalize("NFKD").replace(/[^\w\s-]/g, "").trim().replace(/[\s_]+/g, "-").slice(0, 60);

  // page: {title, slug?, body, tags?, kind?, due?, priority?, fields?, summary?} (a write's
  // record, as written-page.json has it); returns the stored page's slug
  sim.write = (w) => {
    const now = new Date().toISOString();
    const slug = w.slug || slugify(w.title);
    const had = pages.find((p) => p.slug === slug);
    if (had) { // an append (write's append_to): the page's new text, now its newest
      Object.assign(had, { title: w.title, body: w.body, tags: w.tags || had.tags, updated_at: now, rev: had.rev + 1 });
      if (w.due !== undefined) had.due = w.due;
      return slug;
    }
    const id = `SIMDEMO${Date.now().toString(36).toUpperCase()}`;
    pages.push({
      id, slug, title: w.title, body: w.body, kind: w.kind || "note", kind_fixed: w.kind ? 1 : 0,
      fields: { origin: "Claude Code session", ...(w.kind === "todo" && { status: "open" }), ...w.fields },
      created_at: now, updated_at: now, due: w.due ?? null, priority: w.priority ?? null, snoozed_until: null, rev: 1, tags: w.tags || [], made_by: "claude",
      captures: [{ id: `${id}C`, kind: "text", text: w.body, url: null, source: "mcp", author: "claude",
        created_at: now, received_at: now, blobs: [] }],
      removed: [], tasks: { done: 0, total: 0 },
    });
    if (w.summary && window.__simEnrich) window.__simEnrich[slug] = { summary: w.summary, related: w.related || [] };
    return slug;
  };
})();

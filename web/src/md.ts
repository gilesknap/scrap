// A tiny Markdown renderer for page text: headings, **bold**, *italic*, `code`, fenced code,
// lists, quotes, links, rules and paragraphs (a line break stays one). Every piece of text is
// HTML-escaped before anything else, there is no raw HTML, links are http(s) or mailto only, or
// [[slug]] and [[slug|label]] to another page, and images only this server's own files. The
// stored text is never changed.
const ESC: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};
export const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ESC[c]);

const LINK = /^(https?:\/\/|mailto:)/i;
const IMAGE = /^\/api\/blobs\/[0-9a-f]{64}(\/preview\?size=(480|2048))?$/;
const a = (href: string, text: string) =>
  `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`;

/** One line or paragraph of text, escaped, then formatted. */
export function inline(raw: string): string {
  const kept: string[] = []; // finished HTML, kept out of later rules (U+E000 marks them)
  const keep = (html: string) => `\uE000${kept.push(html) - 1}\uE000`;
  let s = esc(raw.replaceAll("\uE000", ""));
  const em = (t: string) =>
    t
      .replace(/(\*\*|__)(?=\S)(.+?)(?<=\S)\1/g, "<strong>$2</strong>")
      .replace(/(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])/g, "<em>$1</em>")
      .replace(/(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)/g, "<em>$1</em>");
  s = s.replace(/(`+)(.+?)\1/g, (_, __, code: string) => keep(`<code>${code.trim()}</code>`));
  // No marker inside an address or alt text: only ever in text, so it is safe to restore
  s = s.replace(/!\[([^\]\uE000]*)\]\(([^)\s\uE000]+)\)/g, (m, alt: string, src: string) =>
    IMAGE.test(src) ? keep(`<img src="${src}" alt="${alt}" loading="lazy">`) : m,
  );
  s = s.replace(/\[\[([a-z0-9-]+)(?:\|([^\]]+))?\]\]/g, (_, slug: string, label?: string) =>
    keep(`<a href="/p/${slug}">${em(label ?? slug)}</a>`),
  );
  s = s.replace(/\[([^\]]+)\]\(([^)\s\uE000]+)\)/g, (m, text: string, href: string) =>
    LINK.test(href) ? keep(a(href, em(text))) : m,
  );
  s = s.replace(/https?:\/\/[^\s\uE000]+/g, (m) => {
    const url = m.split(/&(?:lt|gt|quot|#39);/)[0].replace(/[.,;:!?)]+$/, "");
    return keep(a(url, url)) + m.slice(url.length);
  });
  let html = em(s);
  while (html.includes("\uE000"))
    // kept HTML may hold markers too (code in a link)
    html = html.replace(/\uE000(\d+)\uE000/g, (_, n) => kept[Number(n)]);
  return html;
}

/** Markdown to HTML that is safe to set as innerHTML. */
export function markdown(text: string): string {
  const out: string[] = [];
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  let para: string[] = [];
  const flush = () => {
    if (para.length) out.push(`<p>${para.map(inline).join("<br>")}</p>`);
    para = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    const list = line.match(/^\s*([-*+]|\d+[.)])\s+/);
    // A run of lines that match re, from line i on; i is left on the last of them.
    const run = (re: RegExp) => {
      const got: string[] = [];
      for (; i < lines.length && re.test(lines[i]); i++) got.push(lines[i]);
      i--;
      return got;
    };
    const fence = line.match(/^ {0,3}(`{3,}|~{3,})/)?.[1];
    if (fence) {
      flush(); // closed by the same character, at least as many, and nothing after
      const close = new RegExp(`^ {0,3}${fence[0]}{${fence.length},}\\s*$`);
      const code: string[] = [];
      while (++i < lines.length && !close.test(lines[i])) code.push(lines[i]);
      out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
    } else if (heading) {
      flush();
      const n = heading[1].length;
      out.push(`<h${n}>${inline(heading[2])}</h${n}>`);
    } else if (/^ {0,3}([-*_])( *\1){2,} *$/.test(line)) {
      flush();
      out.push("<hr>");
    } else if (/^\s*>/.test(line)) {
      flush();
      const quote = run(/^\s*>/).map((l) => l.replace(/^\s*> ?/, ""));
      out.push(`<blockquote>${markdown(quote.join("\n"))}</blockquote>`);
    } else if (list) {
      flush();
      const ordered = /\d/.test(list[1]);
      const item = ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*+]\s+/;
      const items = run(item).map((l) => `<li>${inline(l.replace(item, ""))}</li>`);
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>${items.join("")}</${tag}>`);
    } else if (line.trim()) para.push(line);
    else flush();
  }
  flush();
  return out.join("\n");
}

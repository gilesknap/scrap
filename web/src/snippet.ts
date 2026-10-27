// Search snippets arrive as HTML-escaped text with <mark> around hits. Never hand them to
// innerHTML: split on the two tags, unescape the rest and let the caller make text nodes.
const ENTITIES: Record<string, string> = {
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#x27;": "'",
};

export function snippetParts(html: string): { text: string; mark: boolean }[] {
  const parts: { text: string; mark: boolean }[] = [];
  let mark = false;
  for (const part of html.split(/(<\/?mark>)/)) {
    if (part === "<mark>" || part === "</mark>") mark = part === "<mark>";
    else if (part)
      parts.push({ text: part.replace(/&(?:amp|lt|gt|quot|#x27);/g, (e) => ENTITIES[e]), mark });
  }
  return parts;
}

// For comparing words alone: "Review PR #125: page cap" is "review pr 125 page cap", and
// "sqlite-vec" or "sqlite_vec" is "sqlite vec" (punctuation, hyphens and underscores part words)
const plain = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]|_/gu, " ")
    .replace(/\s+/g, " ")
    .trim();

/** Whether a search hit's snippet (its text) only says its title again, whole words of it in
 * order: then it is not shown. (A fragment of a word, "eat" of "Great", says something else.) */
export const echoes = (title: string, snip: string) => {
  const said = plain(snip);
  return !said || ` ${plain(title)} `.includes(` ${said} `);
};

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

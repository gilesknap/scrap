// The text Share sends: a page's, without the lines that embed its images (page.ts).

const EMBEDS = /^\s*(!\[[^\]\n]*\]\(\/api\/blobs\/[^)\s]+\)\s*)+$/;

/** Text for other apps (Share): without the lines that only embed this server's images, nor
 * the blank line each leaves; code and everything else as typed. */
export function unembedded(text: string): string {
  const out: string[] = [];
  let fence: RegExp | null = null; // what closes the open code fence
  let gap = false; // a line was dropped since the last line kept
  for (const line of text.replace(/\r\n?/g, "\n").split("\n")) {
    const open = line.match(/^ {0,3}(`{3,}|~{3,})/)?.[1];
    if (fence) {
      if (fence.test(line)) fence = null;
    } else if (open) fence = new RegExp(`^ {0,3}${open[0]}{${open.length},}\\s*$`);
    else if (EMBEDS.test(line)) {
      gap = true;
      continue;
    }
    if (gap && !line.trim() && !out.at(-1)?.trim()) continue; // the blank line it left
    gap = false;
    out.push(line);
  }
  while (gap && out.length && !out.at(-1)?.trim()) out.pop(); // a gap left at the end
  return out.join("\n");
}

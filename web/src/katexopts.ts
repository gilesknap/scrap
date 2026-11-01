// KaTeX's options, the same for the page view (math.ts) and a public page (publish.ts), so a
// formula is drawn the same way in both. No \href, \url or \htmlClass (trust: false); a
// formula it can't draw throws, and stays as its TeX.
export const KATEX = { throwOnError: true, trust: false, strict: "ignore" } as const;

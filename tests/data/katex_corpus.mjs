// Renders tests/data/katex_corpus.json: KaTeX's own markup (katex.renderToString with the
// PWA's options, web/src/math.ts) for formulas that use every kind of markup KaTeX writes,
// for tests/test_publish_check.py. Run from web/ after npm ci, when KaTeX is upgraded:
//   node ../tests/data/katex_corpus.mjs > ../tests/data/katex_corpus.json
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(path.join(process.cwd(), "package.json"));
const katex = require("katex");

const TEX = [
  "x^2 + y_1",
  "\\frac{a}{b} + \\dfrac{1}{2} + \\tfrac{3}{4}",
  "\\sqrt{x} + \\sqrt[3]{y} + \\sqrt{\\frac{a}{b}}",
  "\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}",
  "\\int_0^\\infty e^{-x}\\,dx",
  "\\lim_{x \\to 0} \\frac{\\sin x}{x} = 1",
  "\\left( \\frac{a}{b} \\right) \\left[ x \\right] \\left\\{ y \\right\\}",
  "\\overbrace{a+b}^{n} \\underbrace{c+d}_{m}",
  "\\widehat{abc} \\widetilde{xyz} \\overrightarrow{AB} \\overleftarrow{CD}",
  "\\xrightarrow[below]{above} \\xleftarrow{x} \\xLeftrightarrow{y}",
  "\\cancel{x} \\bcancel{y} \\xcancel{z}",
  "\\boxed{E=mc^2} \\fbox{box}",
  "\\colorbox{yellow}{hi} \\fcolorbox{red}{#eef}{there}",
  "\\color{red} x \\textcolor{#0b57d0}{y} \\color{#080} z",
  "\\begin{array}{c|c} a & b \\\\ \\hline c & d \\\\ \\hdashline e & f \\end{array}",
  "\\begin{pmatrix} 1 & 0 \\\\ 0 & 1 \\end{pmatrix} \\begin{bmatrix} a \\end{bmatrix}",
  "\\begin{cases} x & x > 0 \\\\ -x & \\text{otherwise} \\end{cases}",
  "\\begin{aligned} a &= b + c \\\\ &= d \\end{aligned}",
  "\\boldsymbol{\\alpha} \\bm{x} \\mathbf{v} \\pmb{\\mu}",
  "\\mathbb{R} \\mathcal{L} \\mathfrak{g} \\mathrm{d} \\mathit{x} \\mathsf{s} \\mathtt{t}",
  "\\operatorname{argmax}_x f(x) \\pmod{7} \\bmod 3",
  "\\overline{z} \\underline{w} \\vec{v} \\hat{h} \\tilde{t} \\dot{d} \\ddot{q} \\bar{b}",
  "\\phantom{x} \\hphantom{y} \\vphantom{z} \\smash{q} \\mathllap{a} \\mathrlap{b}",
  "\\kern1em \\hspace{2em} \\, \; \\quad \\qquad \\! \\rule{1em}{0.5em}",
  "\\stackrel{!}{=} \\overset{def}{=} \\underset{x}{y} \\binom{n}{k} \\tbinom{a}{b}",
  "a \\not= b \\neq c \\leq d \\geq e \\approx f \\equiv g",
  "\\text{plain text} \\textbf{bold} \\textit{it} \\textsf{sf} \\texttt{tt}",
  "\\displaystyle\\sum x \\textstyle\\sum y \\scriptstyle z \\scriptscriptstyle w",
  "\\Huge A \\large B \\small C \\tiny D",
  "\\angl{n} \\sout{struck} \\underlinesegment{AB} \\overlinesegment{CD}",
  "\\begin{matrix} a & b \\end{matrix} \\begin{vmatrix} a \\end{vmatrix} \\begin{Vmatrix} b \\end{Vmatrix}",
  "\\begin{gathered} a \\\\ b \\end{gathered} \\begin{split} x &= y \\end{split}",
  "\\begin{CD} A @>a>> B \\end{CD}",
  "\\tag{1} E = mc^2",
  "x \\atop y",
  "\\big( \\Big[ \\bigg\\{ \\Bigg| x",
  "\\lvert x \\rvert \\lVert y \\rVert \\langle z \\rangle \\lceil a \\rceil \\lfloor b \\rfloor",
  "\\mathring{a} \\check{b} \\breve{c} \\acute{d} \\grave{e} \\utilde{f}",
  "\\overleftrightarrow{AB} \\overgroup{abc} \\undergroup{def} \\underrightarrow{x}",
  "\\raisebox{0.25em}{up} \\mathclap{c} \\llap{l} \\rlap{r}",
  "\\verb|code| \\char\"41 \\TeX \\LaTeX",
  "\\begin{alignat}{2} a &= b & c &= d \\end{alignat}",
  "\\begin{array}{|l:r|} \\hline 1 & 2 \\\\ \\hline \\end{array}",
  "\\uparrow\\downarrow \\Updownarrow \\Big\\Vert",
  "\\sqrt{\\dfrac{\\sum_{i}^{N} x_i^2}{\\int_a^b f}}",
  "\\xrightleftharpoons[ab]{cd} \\xhookrightarrow{e} \\xmapsto{f} \\xtofrom{g}",
  "\\Set{ x | x > 0 } \\set{ y }",
];

const OPTIONS = { throwOnError: true, trust: false, strict: "ignore" };
const cases = [];
for (const tex of TEX) {
  for (const displayMode of [false, true]) {
    try {
      cases.push({ tex, display: displayMode, html: katex.renderToString(tex, { ...OPTIONS, displayMode }) });
    } catch (e) {
      // display-only environments ({split}, {CD}, \tag) are drawn in display mode alone
      process.stderr.write(`skipped ${JSON.stringify(tex)} (display ${displayMode}): ${e.message}\n`);
    }
  }
}
process.stdout.write(`${JSON.stringify({ katex: katex.version, options: OPTIONS, cases }, null, 1)}\n`);

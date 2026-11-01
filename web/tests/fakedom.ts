// A fake of the few DOM parts ui.ts's h(), a dialog and a template use, for the unit tests
// (they run in node). Install it with vi.stubGlobal("document", fakeDocument()).
export class FakeNode {
  nodeType = 1;
  childNodes: FakeNode[] = [];
  parentNode: FakeNode | null = null;
  data = "";
  attrs = new Map<string, string>();
  listeners = new Map<string, ((e: { target: unknown; preventDefault(): void }) => void)[]>();
  className = "";
  open = false;
  onclick: (() => void) | null = null;
  [k: string]: unknown;
  constructor(public nodeName: string) {}
  get tagName() {
    return this.nodeName;
  }
  get textContent(): string {
    return this.nodeType === 3 ? this.data : this.childNodes.map((k) => k.textContent).join("");
  }
  set textContent(s: string) {
    this.childNodes = [text(s)];
  }
  setAttribute(k: string, v: string) {
    this.attrs.set(k, String(v));
  }
  getAttribute(k: string) {
    return this.attrs.get(k) ?? null;
  }
  append(...kids: (FakeNode | string)[]) {
    for (const k of kids) {
      const n = typeof k === "string" ? text(k) : k;
      n.parentNode = this;
      this.childNodes.push(n);
    }
  }
  remove() {
    const p = this.parentNode;
    if (p) p.childNodes = p.childNodes.filter((k) => k !== this);
    this.parentNode = null;
  }
  addEventListener(type: string, f: (e: { target: unknown; preventDefault(): void }) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), f]);
  }
  fire(type: string, target: unknown = this) {
    let stopped = false;
    for (const f of this.listeners.get(type) ?? [])
      f({ target, preventDefault: () => (stopped = true) });
    return !stopped;
  }
  focus() {
    doc.activeElement = this;
  }
  showModal() {
    this.open = true;
  }
  close() {
    this.open = false;
  }
  /** Every element under this one with this tag name. */
  find(name: string): FakeNode[] {
    return this.childNodes.flatMap((k) =>
      k.nodeType === 1 ? [...(k.nodeName === name ? [k] : []), ...k.find(name)] : [],
    );
  }
  set innerHTML(s: string) {
    // A template's markup (an icon's SVG): one element standing for it
    const svg = new FakeNode("SVG");
    svg.setAttribute("data-html", s);
    this.content = { firstChild: svg };
  }
}
const text = (s: string) => {
  const n = new FakeNode("#text");
  n.nodeType = 3;
  n.data = s;
  return n;
};

const doc = {
  activeElement: null as FakeNode | null,
  body: new FakeNode("BODY"),
  createElement: (name: string) => new FakeNode(name.toUpperCase()),
};

/** The fake document: body is where dialogs are added. */
export function fakeDocument() {
  doc.activeElement = null;
  doc.body = new FakeNode("BODY");
  return doc;
}

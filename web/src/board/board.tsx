// The drawing viewer's lazy chunk: Excalidraw and React live only here, loaded by a dynamic
// import (drawing.ts) when a drawing is first shown. It renders the static preview on the page
// and runs the full-screen viewer and editor.
import {
  CaptureUpdateAction,
  convertToExcalidrawElements,
  Excalidraw,
  exportToBlob,
  exportToCanvas,
  exportToSvg,
  getCommonBounds,
  getSceneVersion,
  restoreElements,
  serializeAsJSON,
} from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { createRoot } from "react-dom/client";
import {
  type Drawing,
  type Frame,
  frameOf,
  frameView,
  frameViewBox,
  pinTextBindings,
} from "./frame";

// biome-ignore lint/suspicious/noExplicitAny: Excalidraw's element types are not exported here
type Elements = readonly any[];

/** A stored drawing as Excalidraw elements: Claude's skeleton is expanded (with the text
 * binding workaround), a saved scene is restored as Excalidraw loads a file. */
function convert(data: Drawing["data"]): Elements {
  if (data.format === "skeleton") {
    // biome-ignore lint/suspicious/noExplicitAny: skeletons are checked by the server
    const skeleton = pinTextBindings(data.elements) as any[];
    return convertToExcalidrawElements(skeleton, { regenerateIds: false });
  }
  // biome-ignore lint/suspicious/noExplicitAny: as above
  return restoreElements(data.elements as any[], null, { repairBindings: true });
}

/** Text is measured as it is converted, so convert again once its fonts are loaded (the
 * second workaround): exporting a 1 px canvas makes Excalidraw load the fonts it uses. */
export async function elementsOf(data: Drawing["data"]): Promise<Elements> {
  const first = convert(data);
  if (!first.some((e) => e.type === "text")) return first;
  await exportToCanvas({
    elements: first.filter((e) => e.type === "text"),
    files: null,
    getDimensions: () => ({ width: 1, height: 1, scale: 1 }),
  });
  await document.fonts.ready;
  return convert(data);
}

const dark = () => matchMedia("(prefers-color-scheme: dark)").matches;

/** A static SVG of the drawing for the page: framed like its photo, and inert. */
export async function preview(data: Drawing["data"]): Promise<SVGSVGElement> {
  const elements = await elementsOf(data);
  const svg = await exportToSvg({
    elements,
    appState: { exportBackground: false, exportWithDarkMode: dark() },
    files: null,
    exportPadding: 0,
    skipInliningFonts: true, // the page has them; inlining loads a big font subsetter
  });
  const frame = frameOf(data);
  if (frame && elements.length) {
    const [minX, minY] = getCommonBounds(elements);
    svg.setAttribute("viewBox", frameViewBox(frame, minX, minY));
  }
  svg.removeAttribute("width");
  svg.removeAttribute("height");
  svg.setAttribute("aria-hidden", "true");
  return svg;
}

export interface Board {
  /** View (pan and zoom only) or edit. The scene, zoom and scroll are kept across. */
  setEditing(on: boolean): void;
  /** Fit the frame (or the drawing) to the box. */
  fit(): void;
  undo(): void;
  elements(): Elements;
  background(): string;
  /** Changes since the last load. */
  changed(): boolean;
  /** Replace the scene (a saved version or a draft), not undoable. */
  load(elements: Elements): void;
  export(kind: "excalidraw" | "png" | "svg"): Promise<Blob>;
  close(): void;
}

/** The full-screen viewer on host: view mode at first, fitted to the frame. onChange is told
 * of every edit (for drafts). */
export async function board(
  host: HTMLElement,
  data: Drawing["data"],
  onChange: () => void,
): Promise<Board> {
  const frame: Frame | null = frameOf(data);
  const initial = await elementsOf(data);
  const background = data.appState?.viewBackgroundColor ?? "#ffffff";
  const root = createRoot(host);
  let api: ExcalidrawImperativeAPI | null = null;
  let editing = false;
  let base = getSceneVersion(initial);
  let rerender = () => {};
  const ready = new Promise<void>((ok) => {
    const render = () =>
      root.render(
        <Excalidraw
          excalidrawAPI={(a) => {
            api = a;
            ok();
          }}
          initialData={{
            elements: initial,
            appState: { viewBackgroundColor: background, ...fitted() },
          }}
          viewModeEnabled={!editing}
          zenModeEnabled={!editing}
          theme={dark() ? "dark" : "light"}
          name="drawing"
          onChange={(els) => {
            if (editing && getSceneVersion(els) !== base) onChange();
          }}
          UIOptions={{
            canvasActions: {
              changeViewBackgroundColor: false,
              clearCanvas: false,
              export: false,
              loadScene: false,
              saveAsImage: false,
              saveToActiveFile: false,
              toggleTheme: false,
            },
            tools: { image: false },
          }}
        />,
      );
    rerender = render;
    render();
  });
  const scheme = matchMedia("(prefers-color-scheme: dark)");
  const themed = () => rerender();
  scheme.addEventListener("change", themed);

  function fitted() {
    if (!frame) return {};
    // Clear of Excalidraw's footer (both modes) and its tool bar (editing, on top)
    const [top, bottom] = editing ? [72, 72] : [0, 72];
    const { zoom, scrollX, scrollY } = frameView(
      frame,
      host.clientWidth,
      host.clientHeight,
      8,
      top,
      bottom,
    );
    return { zoom: { value: zoom as never }, scrollX, scrollY };
  }
  await ready;
  const a = () => api as ExcalidrawImperativeAPI;
  let lastFit: number[] = []; // the view the last fit left: has the user moved it since?
  const view = () => {
    const { zoom, scrollX, scrollY } = a().getAppState();
    return [zoom.value, scrollX, scrollY];
  };
  const moved = () => {
    const [z, x, y] = view();
    const [z0, x0, y0] = lastFit;
    return !(Math.abs(z / z0 - 1) < 0.01 && Math.abs(x - x0) * z < 2 && Math.abs(y - y0) * z < 2);
  };
  const fitFrame = () => {
    if (frame) {
      const appState = fitted() as { scrollX: number; scrollY: number; zoom: never };
      a().updateScene({ appState, captureUpdate: CaptureUpdateAction.NEVER });
    } else a().scrollToContent(undefined, { fitToViewport: true, animate: false });
    requestAnimationFrame(() => {
      lastFit = view(); // as Excalidraw has applied it
    });
  };
  // The box changes size (rotation, the photo beside it, first layout): while viewing, fit
  // the frame again; while editing, keep the zoom and scroll the edit is at
  let size = "";
  const resized = new ResizeObserver(() => {
    const now = `${host.clientWidth}x${host.clientHeight}`;
    if (now === size || !host.clientWidth) return;
    size = now;
    a().refresh();
    if (!editing) fitFrame();
  });
  resized.observe(host);
  const live = () => a().getSceneElements();
  return {
    setEditing(on) {
      // Still as fitted: fit again around the tool bars of the new mode; else keep the
      // zoom and scroll the user chose
      const untouched = !moved();
      editing = on;
      rerender();
      if (untouched) requestAnimationFrame(fitFrame);
    },
    fit: fitFrame,
    undo() {
      // Excalidraw's own shortcut, on its container: it listens there, not on the document
      const target = host.querySelector(".excalidraw") ?? host;
      for (const type of ["keydown", "keyup"]) {
        const key = { key: "z", code: "KeyZ", ctrlKey: true, bubbles: true, cancelable: true };
        target.dispatchEvent(new KeyboardEvent(type, key));
      }
    },
    elements: live,
    background: () => a().getAppState().viewBackgroundColor,
    changed: () => getSceneVersion(live()) !== base,
    load(elements) {
      a().updateScene({ elements, captureUpdate: CaptureUpdateAction.NEVER });
      a().history.clear();
      base = getSceneVersion(live());
    },
    async export(kind) {
      const elements = live();
      const appState = { exportBackground: true, viewBackgroundColor: "#ffffff" };
      if (kind === "png") {
        return exportToBlob({ elements, appState, files: null, mimeType: "image/png" });
      }
      if (kind === "svg") {
        const svg = await exportToSvg({ elements, appState, files: null });
        return new Blob([new XMLSerializer().serializeToString(svg)], { type: "image/svg+xml" });
      }
      const json = serializeAsJSON(elements, { viewBackgroundColor: background }, {}, "local");
      return new Blob([json], { type: "application/vnd.excalidraw+json" });
    },
    close() {
      resized.disconnect();
      scheme.removeEventListener("change", themed);
      root.unmount();
    },
  };
}

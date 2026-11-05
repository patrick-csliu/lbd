import { KeyboardEvent, PointerEvent, RefObject, useEffect, useRef, useState } from "react";

/**
 * A pane whose width is dragged at its edge (the Files sidebar, the Library's filters, the
 * Library's selected file): drag the handle, double-click it to fit the content, ← → with the
 * keyboard (Home: the default). The width is remembered in this browser (localStorage).
 *
 * `side`: where the pane is: "left" panes grow as the handle is dragged to the right, "right"
 * panes as it is dragged to the left, "bottom" panes grow upwards (their *height*; ↑ ↓ with the
 * keyboard). The size changes by the pointer's travel since the press.
 */
export interface Resizable {
  /** the width (for side "bottom": the height) */
  width: number;
  /** true when the user chose the size (dragged now, or remembered); false: the initial size */
  chosen: boolean;
  setWidth: (w: number) => void;
  /** props for the handle element (role="separator") */
  handle: {
    onPointerDown: (e: PointerEvent<HTMLElement>) => void;
    onPointerMove: (e: PointerEvent<HTMLElement>) => void;
    onPointerUp: () => void;
    onPointerCancel: () => void;
    onDoubleClick: () => void;
    onKeyDown: (e: KeyboardEvent<HTMLElement>) => void;
    role: "separator";
    "aria-orientation": "vertical" | "horizontal";
    "aria-valuenow": number;
    "aria-valuemin": number;
    tabIndex: number;
  };
}

export interface ResizableOptions {
  key: string;
  /** the width until one is dragged; a function follows the window as it is resized */
  initial: number | (() => number);
  min: number;
  /** the widest (highest) it may be, as a share of the window's width, or of the container's
   * size with `maxOfContainer` */
  maxShare?: number;
  maxOfContainer?: boolean;
  side?: "left" | "right" | "bottom";
  /** the element the pane's edge is measured from */
  container: RefObject<HTMLElement | null>;
  /** double-click: the width that fits the pane's content (null: nothing to fit) */
  fit?: () => number | null;
  /** double-click goes back to the initial size (and forgets the one dragged), instead of `fit` */
  resetOnDoubleClick?: boolean;
}

function load(key: string): number | null {
  try {
    const w = Number(localStorage.getItem(key));
    return w > 0 ? w : null;
  } catch {
    return null;
  }
}

function save(key: string, w: number) {
  try {
    localStorage.setItem(key, String(w));
  } catch {
    /* storage unavailable: the width just isn't remembered */
  }
}

export function useResizable(o: ResizableOptions): Resizable {
  const tall = o.side === "bottom";
  const room = () => {
    const box = o.maxOfContainer ? o.container.current?.getBoundingClientRect() : undefined;
    return box ? (tall ? box.height : box.width) : tall ? window.innerHeight : window.innerWidth;
  };
  const clamp = (w: number) => Math.round(Math.max(o.min, Math.min(w, room() * (o.maxShare ?? 0.6))));
  const initial = () => (typeof o.initial === "function" ? o.initial() : o.initial);
  // a width dragged (and remembered) stays; until then the initial one, following the window
  const [chosen, setChosen] = useState<number | null>(() => load(o.key));
  // the width is worked out again when the window changes (the initial one and the maximum follow it)
  const [, setWindowWidth] = useState(window.innerWidth);
  useEffect(() => {
    const on = () => setWindowWidth(window.innerWidth);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  const [dragged, setDragged] = useState<number | null>(null); // while dragging
  const width = clamp(dragged ?? chosen ?? initial());
  const dragging = useRef(false);
  // where the drag started: the pointer and the size then (the size follows the pointer's travel,
  // so a handle that isn't exactly at the pane's edge doesn't make it jump)
  const start = useRef({ pos: 0, size: 0 });
  /** Back to the initial size: the one dragged is forgotten. */
  const reset = () => {
    setDragged(null);
    setChosen(null);
    try {
      localStorage.removeItem(o.key);
    } catch {
      /* not remembered anyway */
    }
  };
  const setWidth = (w: number) => {
    const c = clamp(w);
    setDragged(null);
    setChosen(c);
    save(o.key, c);
  };
  return {
    width,
    chosen: dragged !== null || chosen !== null,
    setWidth,
    handle: {
      onPointerDown: (e) => {
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        dragging.current = true;
        start.current = { pos: tall ? e.clientY : e.clientX, size: width };
        document.body.classList.add("resizing");
      },
      onPointerMove: (e) => {
        if (!dragging.current) return;
        const travel = (tall ? e.clientY : e.clientX) - start.current.pos;
        // a pane on the left grows as the pointer goes right; on the right or below, as it goes left or up
        setDragged(clamp(start.current.size + (tall || o.side === "right" ? -travel : travel)));
      },
      onPointerUp: () => {
        if (!dragging.current) return;
        dragging.current = false;
        document.body.classList.remove("resizing");
        if (dragged !== null) setWidth(dragged);
      },
      onPointerCancel: () => {
        dragging.current = false;
        document.body.classList.remove("resizing");
        setDragged(null);
      },
      onDoubleClick: () => {
        if (o.resetOnDoubleClick) return reset();
        const w = o.fit?.();
        if (w) setWidth(w);
      },
      onKeyDown: (e) => {
        const step = o.side === "right" ? -20 : 20; // ← narrows a left pane, widens a right one
        if (!tall && e.key === "ArrowLeft") setWidth(width - step);
        else if (!tall && e.key === "ArrowRight") setWidth(width + step);
        else if (tall && e.key === "ArrowUp") setWidth(width + 20); // ↑ raises the top edge of a pane below
        else if (tall && e.key === "ArrowDown") setWidth(width - 20);
        else if (e.key === "Home") reset();
        else return;
        e.preventDefault();
      },
      role: "separator",
      "aria-orientation": tall ? "horizontal" : "vertical",
      "aria-valuenow": width,
      "aria-valuemin": o.min,
      tabIndex: 0,
    },
  };
}

/** The width that shows the widest of `selector` inside `pane` whole, plus `extra` px. */
export function widestContent(pane: HTMLElement | null, selector: string, extra: number): number | null {
  if (!pane) return null;
  const left = pane.getBoundingClientRect().left;
  let widest = 0;
  pane.querySelectorAll<HTMLElement>(selector).forEach((el) => {
    widest = Math.max(widest, el.getBoundingClientRect().left - left + el.scrollWidth);
  });
  return widest ? widest + extra : null;
}

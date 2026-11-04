import { KeyboardEvent, PointerEvent, RefObject, useEffect, useRef, useState } from "react";

/**
 * A pane whose width is dragged at its edge (the Files sidebar, the Library's filters, the
 * Library's selected file): drag the handle, double-click it to fit the content, ← → with the
 * keyboard (Home: the default). The width is remembered in this browser (localStorage).
 *
 * `side`: which edge of the pane the handle is on, seen from the container: "left" panes grow to
 * the right (their width is the pointer's distance from the container's left), "right" panes grow
 * to the left (the distance from the container's right).
 */
export interface Resizable {
  width: number;
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
    "aria-orientation": "vertical";
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
  /** the widest it may be, as a share of the window's width */
  maxShare?: number;
  side?: "left" | "right";
  /** the element the pane's edge is measured from */
  container: RefObject<HTMLElement | null>;
  /** double-click: the width that fits the pane's content (null: nothing to fit) */
  fit?: () => number | null;
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
  const clamp = (w: number) => Math.round(Math.max(o.min, Math.min(w, window.innerWidth * (o.maxShare ?? 0.6))));
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
  const setWidth = (w: number) => {
    const c = clamp(w);
    setDragged(null);
    setChosen(c);
    save(o.key, c);
  };
  return {
    width,
    setWidth,
    handle: {
      onPointerDown: (e) => {
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        dragging.current = true;
        document.body.classList.add("resizing");
      },
      onPointerMove: (e) => {
        const box = o.container.current?.getBoundingClientRect();
        if (!dragging.current || !box) return;
        setDragged(clamp(o.side === "right" ? box.right - e.clientX : e.clientX - box.left));
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
        const w = o.fit?.();
        if (w) setWidth(w);
      },
      onKeyDown: (e) => {
        const step = o.side === "right" ? -20 : 20; // ← narrows a left pane, widens a right one
        if (e.key === "ArrowLeft") setWidth(width - step);
        else if (e.key === "ArrowRight") setWidth(width + step);
        else if (e.key === "Home") {
          setDragged(null);
          setChosen(null);
          try {
            localStorage.removeItem(o.key);
          } catch {
            /* not remembered anyway */
          }
        }
        else return;
        e.preventDefault();
      },
      role: "separator",
      "aria-orientation": "vertical",
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

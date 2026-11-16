import { PointerEvent as ReactPointerEvent, RefObject, useRef, useState } from "react";

/** `list` with the item at `from` moved to `to` (an index in the list without it). */
export function reorder<T>(list: T[], from: number, to: number): T[] {
  const out = [...list];
  const [item] = out.splice(from, 1);
  out.splice(Math.max(0, Math.min(to, out.length)), 0, item);
  return out;
}

/** Drag a column's right edge to change its width: `width` gives its width now; `onLive` follows
 * the drag; `onDone` gets the width when the mouse is let go. */
export function startResize(
  e: ReactPointerEvent<HTMLElement>,
  width: number,
  onLive: (w: number) => void,
  onDone: (w: number) => void,
  min = 40,
): void {
  e.preventDefault();
  e.stopPropagation();
  const x0 = e.clientX;
  let w = width;
  const move = (ev: PointerEvent) => {
    w = Math.max(min, Math.min(2000, Math.round(width + ev.clientX - x0)));
    onLive(w);
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    document.body.classList.remove("resizing");
    if (w !== width) onDone(w);
  };
  document.body.classList.add("resizing");
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

/**
 * Drag column titles to put them in another order. The titles are the elements with `data-col`
 * inside `head`. A press that moves less than 4 px stays a click (sorting); a drag shows where
 * the column would go (`drop`: the index of the title it goes in front of, or the number of
 * titles for the end) and calls `onMove(id, to)` when let go.
 */
export function useColumnMove(head: RefObject<HTMLElement | null>, onMove: (id: string, to: number) => void) {
  const [dragging, setDragging] = useState<string | null>(null);
  const [drop, setDrop] = useState<number | null>(null);
  const dragged = useRef(false); // the click after a drag doesn't sort
  const start = (e: ReactPointerEvent<HTMLElement>, id: string, pinned?: (index: number) => boolean) => {
    if (e.button !== 0) return;
    const x0 = e.clientX;
    let moving = false;
    let to: number | null = null;
    dragged.current = false;
    const titles = () => [...(head.current?.querySelectorAll<HTMLElement>("[data-col]") ?? [])];
    const move = (ev: PointerEvent) => {
      if (!moving && Math.abs(ev.clientX - x0) < 4) return;
      if (!moving) {
        moving = true;
        setDragging(id);
        document.body.classList.add("moving-column");
      }
      const t = titles();
      let i = t.findIndex((el) => {
        const r = el.getBoundingClientRect();
        return ev.clientX < r.left + r.width / 2;
      });
      if (i < 0) i = t.length;
      if (pinned) while (i < t.length && pinned(i)) i++;
      to = i;
      setDrop(i);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.classList.remove("moving-column");
      if (moving && to !== null) {
        dragged.current = true;
        const from = titles().findIndex((el) => el.dataset.col === id);
        const target = to > from ? to - 1 : to;
        if (from >= 0 && target !== from) onMove(id, target);
      }
      setDragging(null);
      setDrop(null);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  /** True once, right after a drag: the title's click is not a sort. */
  const wasDrag = () => {
    const d = dragged.current;
    dragged.current = false;
    return d;
  };
  return { dragging, drop, start, wasDrag };
}

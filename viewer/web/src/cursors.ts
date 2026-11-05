import { AtLine, CursorAsk, CursorRead, CursorType, ReadItem } from "./api";

/**
 * The Explore view's cursors: what is remembered for a file (positions on the data, type, cuts)
 * and how their numbers are written.
 */

/** Remembered with the view (LBD's database, never the file). Positions are in plot units. */
export interface CursorsState {
  type: CursorType;
  at: CursorAsk[]; // 0, 1 or 2 cursors
  active: 0 | 1; // the one the keys move
  cuts: boolean; // maps: the row and column through cursor 1
  on: boolean; // off: a click places no cursor; the cursors are kept, hidden, for when they are on again
  every?: boolean; // curves, a vertical or horizontal cursor: read every trace at the line (absent: yes)
  at_line?: AtLine; // ... between its stored points (absent) or the nearest stored point
}

export const NO_CURSORS: CursorsState = { type: "cross", at: [], active: 0, cuts: true, on: true };

/** A cursor's number on the plot: centre, size (CSS pixels), which cursors (0, 1) it stands for. */
export interface Badge {
  x: number;
  y: number;
  w: number;
  h: number;
  cursors: number[];
}

const BADGE = 15; // height, and width of one number
const NEAR = 2; // cursors this close (pixels) are one point: one badge "1 2"

/** Where the cursors' numbers go: each tries places around its cursor (at the line's end for a
 *  vertical or horizontal cursor) and takes the first inside the plot, off the other badge and
 *  off the other cursor's mark. Cursors at one point share a badge. */
export function labelPlaces(points: ([number, number] | null)[], plot: [number, number, number, number], type: CursorType): Badge[] {
  const [l, t, w, h] = plot;
  const r = BADGE / 2;
  const [a, b] = points;
  if (a && b && Math.hypot(a[0] - b[0], a[1] - b[1]) <= NEAR) {
    const [x, y] = spots(a, plot, type).find(([x, y]) => inside(x, y, 2 * BADGE, plot)) ?? [a[0], a[1]];
    return [{ x, y, w: 2 * BADGE, h: BADGE, cursors: [0, 1] }];
  }
  const out: Badge[] = [];
  points.forEach((p, i) => {
    if (!p) return;
    const free = ([x, y]: [number, number]) =>
      inside(x, y, BADGE, plot) &&
      out.every((o) => Math.hypot(o.x - x, o.y - y) >= BADGE + 2) &&
      points.every((q, k) => k === i || !q || Math.hypot(q[0] - x, q[1] - y) >= r + 7);
    const all = spots(p, plot, type);
    const [x, y] = all.find(free) ?? all.find(([x, y]) => inside(x, y, BADGE, plot)) ?? [Math.min(Math.max(p[0], l + r), l + w - r), Math.min(Math.max(p[1], t + r), t + h - r)];
    out.push({ x, y, w: BADGE, h: BADGE, cursors: [i] });
  });
  return out;
}

function inside(x: number, y: number, width: number, [l, t, w, h]: [number, number, number, number]): boolean {
  return x - width / 2 >= l && x + width / 2 <= l + w && y - BADGE / 2 >= t && y + BADGE / 2 <= t + h;
}

/** The places tried for a cursor's badge, best first. */
function spots([x, y]: [number, number], [l, t, w]: [number, number, number, number], type: CursorType): [number, number][] {
  const d = BADGE / 2 + 7, r = BADGE / 2 + 2, far = BADGE + 3;
  if (type === "vertical")
    return [[x + r, t + r], [x - r, t + r], [x + r, t + r + far], [x - r, t + r + far], [x + r, t + r + 2 * far], [x - r, t + r + 2 * far]];
  if (type === "horizontal") {
    const e = l + w - r;
    return [[e, y - r], [e, y + r], [e - far, y - r], [e - far, y + r], [e - 2 * far, y - r], [e - 2 * far, y + r]];
  }
  return [[x + d, y - d], [x - d, y - d], [x + d, y + d], [x - d, y + d], [x + 2 * d, y - d], [x - 2 * d, y + d]];
}

// Units that take no SI prefix.
const NO_PREFIX = new Set(["dB", "dBm", "dBc", "°", "%", "deg", "K"]);
const PREFIXES: [string, number][] = [
  ["T", 1e12],
  ["G", 1e9],
  ["M", 1e6],
  ["k", 1e3],
  ["", 1],
  ["m", 1e-3],
  ["µ", 1e-6],
  ["n", 1e-9],
  ["p", 1e-12],
  ["f", 1e-15],
];

/** A number with its unit, with an SI prefix where it fits: 5120310000 Hz → "5.12031 GHz". */
export function si(v: number | null | undefined, unit: string, digits = 7): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "empty";
  const plain = (n: number) => Number(n.toPrecision(digits)).toString().replace("-", "−");
  if (!unit) return plain(v);
  // a ratio (dB/GHz) is shown as the axis shows it: no further prefix
  if (NO_PREFIX.has(unit) || unit.includes("/") || v === 0) return `${plain(v)} ${unit}`;
  const a = Math.abs(v);
  for (const [p, f] of PREFIXES) if (a >= f * 0.9999999) return `${plain(v / f)} ${p}${unit}`;
  return `${plain(v)} ${unit}`;
}

/** One read-out number: "Frequency = 5.12031 GHz". */
export function readText(i: ReadItem): string {
  return `${i.label} = ${i.text ?? si(i.value, i.unit)}`;
}

export const item = (c: CursorRead | null | undefined, role: ReadItem["role"]) => c?.items.find((i) => i.role === role);

/** Differences and means between two cursors, per number they share (same name and unit). */
export function between(a: CursorRead, b: CursorRead): { role: string; label: string; unit: string; delta: number; mean: number }[] {
  const out = [];
  for (const ia of a.items) {
    if (ia.role === "series") continue;
    const ib = b.items.find((i) => i.role === ia.role);
    if (!ib || ib.name !== ia.name || ib.unit !== ia.unit || ia.value === null || ib.value === null) continue;
    // zero up to rounding (−0.175 and 0.175 give 2.8e−17): shown as 0
    const tiny = 1e-12 * Math.max(Math.abs(ia.value), Math.abs(ib.value));
    const zero = (v: number) => (Math.abs(v) < tiny ? 0 : v);
    out.push({ role: ia.role, label: ia.label, unit: ia.unit, delta: zero(ib.value - ia.value), mean: zero((ia.value + ib.value) / 2) });
  }
  return out;
}

/** The mouse and keys of the Explore view, for the "?" list. */
export const HELP: [string, string][] = [
  ["Click", "cursor 1 there, on the nearest stored point (maps: the cell)"],
  ["Shift + click", "cursor 2: a range, with differences and means"],
  ["Drag a cursor", "move it; a cursor on a trace stays on that trace"],
  ["Alt + click or drag", "a free position, not on the data"],
  ["Drag elsewhere", "zoom to a box (a flat box: one axis)"],
  ["Right or middle drag", "pan"],
  ["Wheel", "zoom (Shift: horizontal only, Alt: vertical only)"],
  ["Double-click", "show everything"],
  ["Right-click", "menu: cursors, max, min, peak, cuts"],
  ["← →", "move the active cursor one stored point (Shift: 10)"],
  ["↑ ↓", "curves: the next / previous trace; maps: one row"],
  ["Tab", "switch the active cursor (1 ↔ 2)"],
  ["M  N  P", "max, min, peak (between the cursors, else in the view)"],
  ["[  ]", "the first slider one step back / on"],
  ["+  −", "zoom in / out around cursor 1"],
  ["Home or 0", "show everything"],
  ["C", "cuts on / off (maps)"],
  ["K", "cursors on / off (off: a click does nothing; also: click the chosen cursor type again)"],
  ["Esc", "cancel a box; else remove the cursors"],
  ["1 … 6", "several panels: make that panel the active one"],
  ["?", "this list"],
];

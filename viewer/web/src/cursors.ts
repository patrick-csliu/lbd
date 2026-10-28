import { CursorAsk, CursorRead, CursorType, ReadItem } from "./api";

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
}

export const NO_CURSORS: CursorsState = { type: "cross", at: [], active: 0, cuts: true, on: true };

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
  return `${i.label} = ${si(i.value, i.unit)}`;
}

export const item = (c: CursorRead | null | undefined, role: ReadItem["role"]) => c?.items.find((i) => i.role === role);

/** Differences and means between two cursors, per number they share (same name and unit). */
export function between(a: CursorRead, b: CursorRead): { role: string; label: string; unit: string; delta: number; mean: number }[] {
  const out = [];
  for (const ia of a.items) {
    if (ia.role === "series") continue;
    const ib = b.items.find((i) => i.role === ia.role);
    if (!ib || ib.name !== ia.name || ib.unit !== ia.unit || ia.value === null || ib.value === null) continue;
    out.push({ role: ia.role, label: ia.label, unit: ia.unit, delta: ib.value - ia.value, mean: (ia.value + ib.value) / 2 });
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
  ["K", "cursors on / off (off: a click does nothing)"],
  ["Esc", "cancel a box; else remove the cursors"],
  ["?", "this list"],
];

/**
 * How the page writes a number with its unit: the same rule as the plots' axes.
 *
 * A unit gets an SI prefix only when the whole unit text is on the plots' list of units
 * (`lbd.plot.units.AUTO_UNITS`, sent by the server in /api/state). Every other unit is shown as
 * stored: already prefixed ones (mm, kHz), dB, %, a.u., counts, combined units (V/cm, V*s).
 * Their very large or small numbers are written in scientific notation instead (2e−7 V/cm).
 *
 * This file imports nothing, so its tests run in plain Node (viewer/web/tests/units.test.mjs).
 */

// The plots' list; empty until the server has sent it (then no unit gets a prefix).
let autoUnits: ReadonlySet<string> = new Set();

/** Use the plots' list of units that get a prefix (from /api/state `auto_units`). */
export function setAutoUnits(units: readonly string[]): void {
  autoUnits = new Set(units);
}

/** Whether `unit` may get a prefix: an exact match with the plots' list. */
export function takesPrefix(unit: string): boolean {
  return autoUnits.has(unit);
}

// Prefixes in steps of 1000, as on the plots (q, 10⁻³⁰, to Q, 10³⁰).
const PREFIXES: [string, number][] = [
  ["Q", 1e30], ["R", 1e27], ["Y", 1e24], ["Z", 1e21], ["E", 1e18], ["P", 1e15], ["T", 1e12],
  ["G", 1e9], ["M", 1e6], ["k", 1e3], ["", 1], ["m", 1e-3], ["µ", 1e-6], ["n", 1e-9],
  ["p", 1e-12], ["f", 1e-15], ["a", 1e-18], ["z", 1e-21], ["y", 1e-24], ["r", 1e-27], ["q", 1e-30],
];

/** The prefix for numbers up to `top` (the largest absolute value), with its factor. */
function prefixFor(top: number): [string, number] {
  if (top === 0) return ["", 1];
  // the tolerance keeps 999.99999… (a rounded 1000) in the larger prefix
  return PREFIXES.find(([, f]) => top >= f * 0.9999999) ?? PREFIXES[PREFIXES.length - 1];
}

// A number without a prefix is written in scientific notation outside this range.
const SCI_BELOW = 1e-3;
const SCI_FROM = 1e6;
const needsSci = (top: number) => top !== 0 && (top < SCI_BELOW || top >= SCI_FROM);

const minus = (s: string) => s.replace(/-/g, "−");
/** `digits` significant digits, trailing zeros dropped: 0.75 → "0.75". */
const plain = (n: number, digits: number) => minus(Number(n.toPrecision(digits)).toString());
/** Scientific notation: 2e−7, 1.5e6. */
function sci(n: number, digits: number): string {
  const [mantissa, exponent] = n.toExponential(digits - 1).split("e");
  return minus(`${Number(mantissa)}e${Number(exponent)}`);
}

/** A number with its unit: 5120310000 Hz → "5.12031 GHz", 0.75 mm → "0.75 mm". */
export function si(v: number | null | undefined, unit: string, digits = 7): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "empty";
  const col = columnSi([v], unit, digits);
  return col.unit ? `${col.show(v)} ${col.unit}` : col.show(v);
}

/** The numbers of one table column: a single unit with a single prefix (the largest number's),
 * so their digits line up and the unit can go in the column's head. */
export function columnSi(values: (number | null | undefined)[], unit: string, digits = 7): { unit: string; show: (v: number | null | undefined) => string } {
  const top = Math.max(0, ...values.map((v) => (v !== null && v !== undefined && Number.isFinite(v) ? Math.abs(v) : 0)));
  const [prefix, factor] = unit && takesPrefix(unit) ? prefixFor(top) : ["", 1];
  // a unit without a prefix: very large or small numbers in scientific notation (numbers
  // without any unit, such as point numbers, are written in full as before)
  const write = unit && factor === 1 && needsSci(top) ? sci : plain;
  return {
    unit: prefix + unit,
    show: (v) => (v === null || v === undefined || !Number.isFinite(v) ? "empty" : write(v / factor, digits)),
  };
}

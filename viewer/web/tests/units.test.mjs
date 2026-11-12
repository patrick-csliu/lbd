// How the page writes numbers with units (src/units.ts): the cases of plan 16, item 16.1.
// Run with `npm test` (plain Node, which reads the TypeScript file directly).
import assert from "node:assert/strict";
import { test } from "node:test";

import { columnSi, setAutoUnits, si } from "../src/units.ts";

// The plots' list (lbd.plot.units.AUTO_UNITS); the page gets it from /api/state, and
// viewer/tests/test_endpoints.py checks that the server sends exactly that list.
setAutoUnits(["Hz", "s", "V", "A", "W", "Ω", "Ohm", "F", "H", "T", "K", "m", "g", "J", "C", "S", "Pa", "N", "eV", "Wb"]);

test("units on the plots' list get a prefix", () => {
  assert.equal(si(5120310000, "Hz"), "5.12031 GHz");
  assert.equal(si(2e-6, "s"), "2 µs");
  assert.equal(si(0.002, "K"), "2 mK"); // new: K gets a prefix, as on the plots
  assert.equal(si(0.5, "C"), "500 mC"); // coulomb; °C is left alone
  assert.equal(si(1500, "m"), "1.5 km");
  assert.equal(si(0, "V"), "0 V");
  assert.equal(si(-0.0123, "V"), "−12.3 mV");
});

test("every other unit is shown as stored", () => {
  // the cases found wrong in 16.1: no prefix on top of the stored one
  assert.equal(si(0.75, "mm"), "0.75 mm");
  assert.equal(si(2500, "mm"), "2500 mm");
  assert.equal(si(5000, "kHz"), "5000 kHz"); // not 5 MHz
  assert.equal(si(0.5, "a.u."), "0.5 a.u.");
  assert.equal(si(1500, "counts"), "1500 counts");
  assert.equal(si(0.5, "min"), "0.5 min");
  // dB-type units, %, angles, ppm, other capitals, °C
  for (const unit of ["dB", "dBm", "dBc", "%", "°", "deg", "rad", "ppm", "hz", "°C", "kg"])
    assert.equal(si(0.5, unit), `0.5 ${unit}`);
  // combined units: no prefix on the first part
  for (const unit of ["V/cm", "m/s", "1/s", "V*s", "A·s", "m^2"]) assert.equal(si(0.02, unit), `0.02 ${unit}`);
});

test("very large or small numbers of a unit without a prefix use scientific notation", () => {
  assert.equal(si(2e-7, "V/cm"), "2e−7 V/cm");
  assert.equal(si(-2e-7, "V/cm"), "−2e−7 V/cm");
  assert.equal(si(1.5e6, "counts"), "1.5e6 counts");
  assert.equal(si(999999, "counts"), "999999 counts");
  assert.equal(si(0.001, "rad"), "0.001 rad");
  // numbers without a unit (point numbers) stay written in full
  assert.equal(si(1234567, ""), "1234567");
});

test("a table column has one prefix, from its largest number", () => {
  const hz = columnSi([1.5e9, 2e6, null], "Hz");
  assert.equal(hz.unit, "GHz");
  assert.deepEqual([1.5e9, 2e6, null].map(hz.show), ["1.5", "0.002", "empty"]);
  const mm = columnSi([0.75, 2500], "mm");
  assert.equal(mm.unit, "mm");
  assert.deepEqual([0.75, 2500].map(mm.show), ["0.75", "2500"]);
  const small = columnSi([2e-7, 5e-8], "V/cm");
  assert.equal(small.unit, "V/cm");
  assert.deepEqual([2e-7, 5e-8].map(small.show), ["2e−7", "5e−8"]);
});

test("until the server has sent the list, no unit gets a prefix", () => {
  setAutoUnits([]);
  try {
    assert.equal(si(5e9, "Hz"), "5e9 Hz");
  } finally {
    setAutoUnits(["Hz"]);
  }
});

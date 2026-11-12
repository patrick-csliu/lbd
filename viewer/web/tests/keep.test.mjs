// What Explore brings back when a file is opened again (src/keep.ts): plan 16, item 16.44.
// Run with `npm test` (plain Node, which reads the TypeScript file directly).
import assert from "node:assert/strict";
import { test } from "node:test";

import { kept, KEEP_DEFAULTS } from "../src/keep.ts";

const NO_CURSORS = { type: "cross", at: [], active: 0, cuts: true, on: true };

function panel(spec, settings = {}, extra = {}) {
  return { id: Math.random().toString(36), spec, settings, stat: "max", view: null, cursors: NO_CURSORS, ...extra };
}

// what a file opened for the first time gets
const start = {
  version: 2,
  panels: [panel({ values: ["I"] }, { crange: "all" })],
  active: 0,
  layout: "side",
  sync: { x: true, y: false, sliders: true, cursors: true },
};

// what was remembered: two panels, everything changed
const saved = {
  version: 2,
  file_version: "v1",
  panels: [
    panel(
      { values: ["Q"], kind: "heatmap", x: "f", y: "p", index: { t: 3 } },
      { select: { p: [1, 2] }, cmap: "magma", yscale: "log", clim: [0, 1], crange: "slice", ops: [{ op: "normalize" }], equations: { y: "y*2" } },
      { view: { xlim: [1, 2], ylim: [3, 4] }, cursors: { type: "vertical", at: [{ x: 1, y: 2 }], active: 1, cuts: false, on: false, every: false } },
    ),
    panel({ values: ["phase"] }),
  ],
  active: 1,
  layout: "stacked",
  sync: { x: false, y: true, sliders: false, cursors: false },
};

test("the defaults keep the plot, colours, limits and sliders; not operations, zoom, sync, cursor options", () => {
  const r = kept(saved, start, KEEP_DEFAULTS, "v1");
  assert.equal(r.panels.length, 2);
  assert.equal(r.layout, "stacked");
  const p = r.panels[0];
  assert.deepEqual(p.spec, saved.panels[0].spec);
  assert.deepEqual(p.settings.select, { p: [1, 2] });
  assert.equal(p.settings.cmap, "magma");
  assert.deepEqual(p.settings.clim, [0, 1]);
  assert.equal(p.settings.ops, undefined);
  assert.equal(p.settings.equations, undefined);
  assert.equal(p.view, null);
  assert.deepEqual(r.sync, start.sync);
  assert.equal(p.cursors.type, "cross");
});

test("cursor positions always start afresh, kept options or not", () => {
  for (const cursor_options of [false, true]) {
    const p = kept(saved, start, { ...KEEP_DEFAULTS, cursor_options }, "v1").panels[0];
    assert.deepEqual(p.cursors.at, []);
    assert.equal(p.cursors.active, 0);
    assert.equal(p.cursors.on, true);
    assert.equal(p.cursors.type, cursor_options ? "vertical" : "cross");
  }
});

test("each part can be left out", () => {
  const all = Object.fromEntries(Object.keys(KEEP_DEFAULTS).map((k) => [k, true]));
  const off = (k) => kept(saved, start, { ...all, [k]: false }, "v1");
  assert.equal(off("colours").panels[0].settings.cmap, undefined);
  assert.equal(off("colours").panels[0].settings.yscale, undefined);
  assert.equal(off("limits").panels[0].settings.clim, undefined);
  assert.equal(off("limits").panels[0].settings.crange, "all");
  assert.equal(off("traces").panels[0].settings.select, undefined);
  assert.equal(off("sliders").panels[0].spec.index, undefined);
  assert.deepEqual(off("plot").panels[0].spec, { values: ["I"] });
  assert.deepEqual(off("plot").panels[1].spec, { values: ["phase"] });
  assert.equal(off("zoom").panels[0].view, null);
  assert.deepEqual(off("sync").sync, start.sync);
  assert.equal(off("panels").panels.length, 1);
  assert.equal(off("panels").layout, "side");
  // all kept: as saved, apart from the cursor positions
  const r = kept(saved, start, all, "v1");
  assert.deepEqual(r.panels[0].view, { xlim: [1, 2], ylim: [3, 4] });
  assert.deepEqual(r.panels[0].settings.ops, [{ op: "normalize" }]);
  assert.deepEqual(r.sync, saved.sync);
});

test("a kept zoom is dropped once the file changed", () => {
  const all = { ...KEEP_DEFAULTS, zoom: true };
  assert.deepEqual(kept(saved, start, all, "v1").panels[0].view, { xlim: [1, 2], ylim: [3, 4] });
  assert.equal(kept(saved, start, all, "v2").panels[0].view, null);
});

test("the saved view itself is not changed", () => {
  const before = JSON.stringify(saved);
  kept(saved, start, { ...KEEP_DEFAULTS, plot: false, colours: false }, "v2");
  assert.equal(JSON.stringify(saved), before);
});

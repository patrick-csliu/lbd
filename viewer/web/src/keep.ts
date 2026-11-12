// What Explore brings back when a file is opened again (plan 16, 16.44): Settings → Explore →
// "Kept when a file is opened again". The saved view is never changed by this: the filter runs on
// open, so a part unticked and later ticked again comes back from what was saved.
//
// Types only from the other modules, so that `npm test` (plain Node) can read this file.

import type { PanelState, Remembered } from "./ExploreTab";

/** The parts of a remembered view, each kept or started afresh (config.EXPLORE_DEFAULTS "keep"). */
export interface KeepParts {
  panels: boolean; // how many panels, their order, the layout, the active one
  plot: boolean; // plot type, values and axes
  traces: boolean; // which traces are drawn (or make a map)
  colours: boolean; // colour map and scales (log or linear)
  limits: boolean; // the colour range
  sliders: boolean; // slider positions
  operations: boolean; // operations and equations
  zoom: boolean; // the view's limits
  sync: boolean; // which panels follow each other
  cursor_options: boolean; // cursor type, cuts, read every trace, together
}

export const KEEP_DEFAULTS: KeepParts = {
  panels: true,
  plot: true,
  traces: true,
  colours: true,
  limits: true,
  sliders: true,
  operations: false,
  zoom: false,
  sync: false,
  cursor_options: false,
};

/** The view to show: `saved` with each part not kept taken from `start` (the view a file opened
 * for the first time gets). Cursor positions always start afresh. A kept zoom is dropped when the
 * file changed since it was remembered (`version` differs). */
export function kept(saved: Remembered, start: Remembered, keep: KeepParts, version: string | null): Remembered {
  if (!keep.panels) return { ...start, sync: keep.sync ? saved.sync : start.sync };
  const fileChanged = !!saved.file_version && !!version && saved.file_version !== version;
  const panels = saved.panels.map((p, i): PanelState => {
    const base = start.panels[i] ?? start.panels[0];
    const spec = { ...p.spec };
    const settings = { ...p.settings };
    if (!keep.plot) {
      for (const k of ["kind", "values", "x", "y", "series", "all", "options", "complex"] as const) delete spec[k];
      Object.assign(spec, i < start.panels.length ? base.spec : { values: p.spec.values });
      delete settings.select; // other traces once the plot is another
    }
    if (!keep.sliders || !keep.plot) {
      if (i < start.panels.length && base.spec.index) spec.index = base.spec.index;
      else delete spec.index;
    }
    if (!keep.traces) delete settings.select;
    if (!keep.colours) for (const k of ["cmap", "invert", "xscale", "yscale", "cscale"] as const) delete settings[k];
    if (!keep.limits) {
      delete settings.clim;
      settings.crange = base.settings.crange;
    }
    if (!keep.operations) for (const k of ["ops", "ops_on", "equations"] as const) delete settings[k];
    const c = p.cursors;
    const cursors = keep.cursor_options
      ? { ...c, at: [], active: 0 as const, on: true }
      : { ...base.cursors, at: [], active: 0 as const, on: true };
    return {
      ...p,
      spec,
      settings,
      cursors,
      view: keep.zoom && keep.plot && !fileChanged ? p.view : null,
      ...(keep.plot ? {} : { back: undefined }),
    };
  });
  return { ...saved, panels, sync: keep.sync ? saved.sync : start.sync };
}

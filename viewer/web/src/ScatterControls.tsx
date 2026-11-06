import type { PlotKind } from "./plotKinds";

/** Scatter's row in plotKinds.ts. */
export const kindRow: PlotKind = {
  kind: "scatter",
  explore: true,
  controls: null,
  cursorTypes: ["cross"],
  strips: null,
  darkInverted: true,
  openInFigure: true,
  cursorMark: "lines",
  axes: "2d",
  syncs: true,
  findButtons: false,
};

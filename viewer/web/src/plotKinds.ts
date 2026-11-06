import type { ComponentType } from "react";
import type { CursorType, FileInfo, PlotSpec } from "./api";
import type { ViewSettings } from "./ExploreView";
import { kindRow as bars } from "./BarsControls";
import { kindRow as bars3d } from "./Bars3dControls";
import { kindRow as histogram } from "./HistogramControls";
import { kindRow as matrix } from "./MatrixControls";
import { kindRow as scatter } from "./ScatterControls";

/**
 * What the page knows about each plot type. A type's row lives in its own `*Controls.tsx`
 * (`kindRow`), so a new type edits nothing here, in ExploreTab or in FileView.
 */

export interface KindControlsProps {
  info: FileInfo;
  spec: PlotSpec; // as asked for
  resolved: PlotSpec; // with the defaults filled in
  update: (patch: PlotSpec) => void;
  settings?: ViewSettings; // Explore's view settings
  updateSettings?: (patch: ViewSettings) => void;
  page: "explore" | "figure";
}

export interface PlotKind {
  kind: string;
  explore: boolean; // Explore can show it
  controls: ComponentType<KindControlsProps> | null; // null: no controls of its own
  cursorTypes: CursorType[];
  strips: "cuts" | "histograms" | null; // beside the plot
  darkInverted: boolean; // the picture is inverted in the dark theme, as curves are
  openInFigure: boolean;
  cursorMark: "lines" | "cell"; // lines through the cursor, or the box of the chosen cell or bar
  axes: "2d" | "3d"; // 3d: no zoom box, pan or limits
  syncs: boolean; // shares its x and y with other panels
  findButtons: boolean; // Max, Min and Peak
  noAxes?: boolean; // no Horizontal axis to choose: its controls say what is shown
}

const ALL_CURSORS: CursorType[] = ["cross", "vertical", "horizontal"];
const common = { explore: true, controls: null, cursorTypes: ALL_CURSORS, openInFigure: true, cursorMark: "lines", axes: "2d", syncs: true, findButtons: true } as const;

const BUILT_IN: PlotKind[] = [
  { ...common, kind: "curve", strips: null, darkInverted: true },
  { ...common, kind: "heatmap", strips: "cuts", darkInverted: false },
];

const OWN = [matrix, bars, bars3d, histogram, scatter].filter((k): k is PlotKind => k !== null);

export const PLOT_KINDS: PlotKind[] = [...BUILT_IN.filter((k) => !OWN.some((o) => o.kind === k.kind)), ...OWN];

/** A plot type's row; a type this page doesn't know gets a curve's. */
export const kindOf = (kind: string | null | undefined): PlotKind => PLOT_KINDS.find((k) => k.kind === kind) ?? BUILT_IN[0];

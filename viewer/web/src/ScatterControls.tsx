import { AxesChoice, ChoiceAxis, startingAxes } from "./AxesChoice";
import type { FileInfo, PlotSpec, ValueInfo } from "./api";
import type { KindControlsProps, PlotKind } from "./plotKinds";

function axesOf(info: FileInfo, v: ValueInfo | undefined): ChoiceAxis[] {
  return (v?.axes ?? []).flatMap((name) => {
    const a = info.axes.find((x) => x.name === name);
    return a && !a.group ? [{ name, label: a.label || a.name, length: a.length, elements: a.elements }] : [];
  });
}

/** Where a new scatter plot starts: a complex value in the I/Q plane, then as `startingAxes`. */
function starting(info: FileInfo, v: ValueInfo | undefined): PlotSpec {
  return { ...startingAxes(axesOf(info, v)), ...(v?.complex ? { complex: "iq" } : {}) };
}

/** What a scatter plot shows besides x and y: Colour by, a slider or All per axis (Data). */
function ScatterControls({ info, resolved, update, page }: KindControlsProps) {
  const first = info.values.find((v) => v.name === resolved.values?.[0]);
  const axes = axesOf(info, first);
  const iq = resolved.complex === "iq";
  const color = resolved.color ?? "none";
  const drawn = !iq && resolved.x ? [resolved.x] : [];
  // A saved figure from before this choice has no `all`: every axis not fixed keeps all its points.
  const sliders = (resolved.slices ?? []).map((s) => s.axis);
  const all = resolved.all ?? axes.map((a) => a.name).filter((a) => a !== color && !drawn.includes(a) && !sliders.includes(a));
  // Figure also colours by another value; a saved view doing so stays shown in Explore
  const sameAxes = info.values.filter((v) => v.axes.join() === first?.axes.join());
  const values = (page === "figure" ? sameAxes : sameAxes.filter((v) => v.name === color)).map((v) => ({ name: v.name, label: `${v.label || v.name} (value)` }));
  return <AxesChoice axes={axes} color={color} all={all} drawn={drawn} values={values} onChange={update} />;
}

/** How a scatter plot looks: equal axes, histograms beside it (Display, 16.47). */
function ScatterDisplay({ resolved, update, page }: KindControlsProps) {
  const equal = resolved.options?.equal ?? resolved.complex === "iq";
  return (
    <>
      <label className="check" title="The same scale both ways, so that a circle looks like a circle">
        <input type="checkbox" checked={!!equal} onChange={(e) => update({ options: { ...(resolved.options ?? {}), equal: e.target.checked } })} />
        Equal axes
      </label>
      {page === "figure" && (
        <label className="check" title="Histograms of the points in the figure's limits, above and beside the plot">
          <input type="checkbox" checked={!!resolved.options?.sides} onChange={(e) => update({ options: { ...(resolved.options ?? {}), sides: e.target.checked } })} />
          Histograms beside the plot
        </label>
      )}
    </>
  );
}

export const kindRow: PlotKind = {
  kind: "scatter",
  explore: true,
  controls: ScatterControls,
  display: ScatterDisplay,
  cursorTypes: ["cross"],
  strips: "histograms",
  darkInverted: true,
  openInFigure: true,
  cursorMark: "lines",
  axes: "2d",
  syncs: true,
  findButtons: false,
  starting,
};

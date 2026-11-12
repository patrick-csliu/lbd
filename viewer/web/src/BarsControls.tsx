import { axisChoices, ComplexSelect } from "./KindFields";
import type { ValueInfo } from "./api";
import type { KindControlsProps, PlotKind } from "./plotKinds";

/** Bars' controls: which values, the groups and the bars in a group, grouped or stacked. */

function BarsControls({ info, resolved: r, update }: KindControlsProps) {
  const values = r.values ?? [];
  const singles = values.length > 0 && info.values.find((v) => v.name === values[0])?.shape.length === 0;
  const axes = axisChoices(info, r, [r.x, r.series]);
  const anyComplex = values.some((n) => info.values.find((v) => v.name === n)?.complex);
  // a value joins the bars when it can stand beside them: on the same groups, or a single number too
  const joins = (v: ValueInfo) => (v.shape.length === 0 ? singles : !singles && !!r.x && v.axes.includes(r.x));
  const toggle = (v: ValueInfo, on: boolean) => {
    if (on && !joins(v)) update({ values: [v.name], x: undefined, series: undefined, index: {} });
    else if (on) update({ values: [...values, v.name], series: undefined });
    else if (values.length > 1) update({ values: values.filter((n) => n !== v.name) });
  };
  const setGroups = (a: string) => update(a === r.series ? { x: a, series: r.x } : { x: a, series: undefined });
  return (
    <>
      <fieldset className="field">
        <legend>Values</legend>
        {info.values.map((v) => (
          <label key={v.name} className="check" title={joins(v) || values.includes(v.name) ? undefined : "On other axes: shown instead of what is shown now"}>
            <input type="checkbox" checked={values.includes(v.name)} onChange={(e) => toggle(v, e.target.checked)} />
            {v.label || v.name}
            {v.unit && <span className="muted small"> ({v.unit})</span>}
          </label>
        ))}
      </fieldset>
      {!singles && (
        <label className="field">
          <span>Groups</span>
          <select aria-label="Groups" value={r.x ?? ""} onChange={(e) => setGroups(e.target.value)}>
            {axes.map((a) => (
              <option key={a.name} value={a.name}>
                {a.text}
              </option>
            ))}
          </select>
        </label>
      )}
      {!singles && values.length === 1 && axes.length > 1 && (
        <label className="field">
          <span>Bars in a group</span>
          <select aria-label="Bars in a group" value={r.series ?? "none"} onChange={(e) => update({ series: e.target.value })}>
            <option value="none">(one bar)</option>
            {axes
              .filter((a) => a.name !== r.x)
              .map((a) => (
                <option key={a.name} value={a.name}>
                  {a.text}
                </option>
              ))}
          </select>
        </label>
      )}
      {anyComplex && <ComplexSelect r={r} update={update} />}
    </>
  );
}

/** Grouped or stacked, the numbers on the bars (Display, 16.47). */
function BarsDisplay({ resolved: r, update }: KindControlsProps) {
  const options = (r.options ?? {}) as { layout?: string; numbers?: boolean };
  const set = (patch: { layout?: string; numbers?: boolean }) => update({ options: { ...(r.options ?? {}), ...patch } });
  return (
    <>
      <label className="field">
        <span>Bars</span>
        <select aria-label="Bars" value={options.layout ?? "grouped"} onChange={(e) => set({ layout: e.target.value })}>
          <option value="grouped">Grouped</option>
          <option value="stacked">Stacked</option>
        </select>
      </label>
      <div className="field">
        <label className="check" title="Each bar's number at its end; left out when bars are narrower than the number">
          <input type="checkbox" checked={!!options.numbers} onChange={(e) => set({ numbers: e.target.checked })} />
          Values on the bars
        </label>
      </div>
    </>
  );
}

export const kindRow: PlotKind = {
  kind: "bars",
  explore: true,
  controls: BarsControls,
  display: BarsDisplay,
  cursorTypes: ["cross", "horizontal"],
  strips: null,
  darkInverted: true,
  openInFigure: true,
  cursorMark: "cell",
  axes: "2d",
  syncs: false,
  findButtons: false,
  ownData: true,
  scales: ["y"],
  shapeOps: true,
};

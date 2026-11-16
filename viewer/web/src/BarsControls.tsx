import { axisChoices, ComplexSelect } from "./KindFields";
import type { ValueInfo } from "./api";
import type { KindControlsProps, PlotKind } from "./plotKinds";

/** Bars' controls: which values, the groups and the bars in a group, a slider or All for every
 * other axis, and with All what a bar shows of its numbers (16.48). */

/** With All of an axis one bar stands for many numbers: what it shows of them (as `bars.STATS`). */
const STATS: [string, string][] = [
  ["mean", "Mean"],
  ["median", "Median"],
  ["max", "Max"],
  ["min", "Min"],
  ["sum", "Sum"],
];

function BarsControls({ info, resolved: r, update }: KindControlsProps) {
  const values = r.values ?? [];
  const singles = values.length > 0 && info.values.find((v) => v.name === values[0])?.shape.length === 0;
  const axes = axisChoices(info, r, [r.x, r.series]);
  const anyComplex = values.some((n) => info.values.find((v) => v.name === n)?.complex);
  // a value joins the bars when it can stand beside them: on the same groups, or a single number too
  const joins = (v: ValueInfo) => (v.shape.length === 0 ? singles : !singles && !!r.x && v.axes.includes(r.x));
  const toggle = (v: ValueInfo, on: boolean) => {
    if (on && !joins(v)) update({ values: [v.name], x: undefined, series: undefined, all: undefined, index: {} });
    else if (on) update({ values: [...values, v.name], series: undefined });
    else if (values.length > 1) update({ values: values.filter((n) => n !== v.name) });
  };
  // every axis not drawn: a slider, or All (its points all go into each bar)
  const all = r.all ?? [];
  const notDrawn = [...(r.slices ?? []).map((s) => s.axis), ...all];
  const others = info.axes.filter((a) => notDrawn.includes(a.name));
  const without = (a: string | undefined) => (all.includes(a ?? "") ? { all: all.filter((x) => x !== a) } : {});
  const setGroups = (a: string) => update(a === r.series ? { x: a, series: r.x } : { x: a, series: undefined, ...without(a) });
  const setAll = (a: string, on: boolean) => update({ all: on ? [...all, a] : all.filter((x) => x !== a) });
  const stat = String((r.options ?? {}).stat ?? "mean");
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
          <select aria-label="Bars in a group" value={r.series ?? "none"} onChange={(e) => update({ series: e.target.value, ...without(e.target.value) })}>
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
      {others.length > 0 && (
        <div className="field" role="group" aria-label="Axes not drawn">
          {others.map((a) => (
            <label key={a.name} className="check" title="All: its points all go into each bar. Otherwise a slider shows one step at a time.">
              <input type="checkbox" checked={all.includes(a.name)} onChange={(e) => setAll(a.name, e.target.checked)} />
              All of {a.label || a.name}
            </label>
          ))}
        </div>
      )}
      {all.length > 0 && (
        <label className="field" title="Each bar stands for many numbers: what it shows of them. Empty points are left out.">
          <span>Bar shows</span>
          <select aria-label="Bar shows" value={stat} onChange={(e) => update({ options: { ...(r.options ?? {}), stat: e.target.value } })}>
            {STATS.map(([v, text]) => (
              <option key={v} value={v}>
                {text}
              </option>
            ))}
          </select>
        </label>
      )}
      {anyComplex && <ComplexSelect r={r} update={update} />}
    </>
  );
}

/** Grouped or stacked, the numbers on the bars (Display, 16.47); with All, error bars (16.48). */
function BarsDisplay({ resolved: r, update }: KindControlsProps) {
  const options = (r.options ?? {}) as { layout?: string; numbers?: boolean; errors?: boolean };
  const set = (patch: { layout?: string; numbers?: boolean; errors?: boolean }) => update({ options: { ...(r.options ?? {}), ...patch } });
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
        {(r.all ?? []).length > 0 && (
          <label className="check" title="One standard deviation of each bar's numbers, up and down from its end">
            <input type="checkbox" checked={!!options.errors} onChange={(e) => set({ errors: e.target.checked })} />
            Error bars
          </label>
        )}
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

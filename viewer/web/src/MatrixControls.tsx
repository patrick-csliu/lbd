import { axisChoices, ComplexSelect, useValuesFor, ValueSelect } from "./KindFields";
import type { KindControlsProps, PlotKind } from "./plotKinds";

/** Matrix's controls: which value, rows and columns, the numbers, the colour range. */

const DIGITS = [1, 2, 3, 4, 5, 6];

function MatrixControls({ info, resolved: r, update }: KindControlsProps) {
  const names = useValuesFor(info.path, "matrix");
  const options = (r.options ?? {}) as { numbers?: boolean; digits?: number; range?: string; row_sums?: boolean };
  const set = (patch: { numbers?: boolean; digits?: number; range?: string; row_sums?: boolean }) => {
    const next = { ...(r.options ?? {}), ...patch };
    if (next.range === undefined) delete next.range;
    update({ options: next });
  };
  const axes = axisChoices(info, r, [r.y, r.x]);
  const complex = info.values.find((v) => v.name === r.values?.[0])?.complex;
  // choosing the other drawn axis swaps them
  const reIm = !!complex && r.complex === "re_im";
  const setRows = (a: string) => update(a === r.x ? { y: a, x: r.y } : { y: a });
  const setColumns = (a: string) => update(a === r.y ? { x: a, y: r.x } : { x: a });
  return (
    <>
      <ValueSelect info={info} r={r} names={names} onChoose={(name) => update({ values: [name], x: undefined, y: undefined, index: {} })} />
      <div className="field axes-field two" role="group" aria-label="Axes">
        <span>Axes</span>
        <div className="axes-grid">
          <span className="axes-name">Columns</span>
          <select aria-label="Columns" value={r.x ?? ""} onChange={(e) => setColumns(e.target.value)}>
            {axes.map((a) => (
              <option key={a.name} value={a.name}>
                {a.text}
              </option>
            ))}
          </select>
          <button className="axes-swap" title="Swap rows and columns" aria-label="Swap the axes" onClick={() => update({ x: r.y, y: r.x })}>
            ⇅
          </button>
          <span className="axes-name">Rows</span>
          <select aria-label="Rows" value={r.y ?? ""} onChange={(e) => setRows(e.target.value)}>
            {axes.map((a) => (
              <option key={a.name} value={a.name}>
                {a.text}
              </option>
            ))}
          </select>
        </div>
      </div>
      {complex && <ComplexSelect r={r} update={update} />}
      <div className="field">
        <label className="check" title="The number of each cell, in the cell; left out when a cell is too small for it">
          <input type="checkbox" checked={options.numbers !== false} onChange={(e) => set({ numbers: e.target.checked })} />
          Numbers
        </label>
      </div>
      <label className="field">
        <span>Significant digits</span>
        <select aria-label="Significant digits" value={options.digits ?? 3} disabled={options.numbers === false} onChange={(e) => set({ digits: Number(e.target.value) })}>
          {DIGITS.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
      <div className="field">
        <label className="check" title={reIm ? "Not for Re and Im: choose another complex mode" : "Each row's sum beside it, from the numbers before rounding"}>
          <input type="checkbox" checked={!!options.row_sums && !reIm} disabled={reIm} onChange={(e) => set({ row_sums: e.target.checked })} />
          Row sums
        </label>
      </div>
      <label className="field" title="Matrices are only comparable with a fixed range. From the data: 0 to 1 or −1 to 1 when the numbers have no unit and fit in it, otherwise Auto">
        <span>Colour range</span>
        <select aria-label="Colour range" value={options.range ?? ""} onChange={(e) => set({ range: e.target.value || undefined })}>
          <option value="">From the data</option>
          <option value="auto">Auto</option>
          <option value="unit">0 to 1</option>
          <option value="signed">−1 to 1</option>
        </select>
      </label>
    </>
  );
}

export const kindRow: PlotKind = {
  kind: "matrix",
  explore: true,
  controls: MatrixControls,
  cursorTypes: ["cross"],
  strips: null,
  darkInverted: false,
  openInFigure: true,
  cursorMark: "cell",
  axes: "2d",
  syncs: false,
  findButtons: false,
  ownData: true,
  scales: [],
  shapeOps: true,
};

import { MouseEvent, useState } from "react";
import { Op, OpName, OpsInfo } from "./api";
import { ContextMenu, MenuAt, MenuEntry } from "./menu";

/**
 * The Operations section of the Explore view's side panel: a list of operations on the data as
 * shown (subtract the mean, d/dx, smoothing, between traces, FFT, histogram), in any order. The
 * server runs them (operations.py) and says per row whether each applied, or why not; one that
 * can't apply is red, and the plot shows the result of the ones above it. A switch turns them all
 * off to compare with the stored data. Explore only: remembered with the view, never in the file.
 */

interface Props {
  kind: "curve" | "heatmap";
  /** The horizontal axis' name, and the traces' axis (a map's vertical axis, or one curve per …). */
  xLabel: string;
  tracesLabel: string | null;
  ops: Op[];
  on: boolean;
  info: OpsInfo | null;
  onChange: (ops: Op[]) => void;
  onOn: (on: boolean) => void;
}

const KINDS: { op: OpName; name: string; tip: string; along: ("x" | "traces")[]; n?: number; bins?: number }[] = [
  { op: "subtract_mean", name: "Subtract the mean", tip: "Each trace minus its mean (along the other axis: a background)", along: ["x", "traces"] },
  { op: "normalize", name: "Normalize", tip: "(value − mean) / standard deviation", along: ["x", "traces"] },
  { op: "derivative", name: "Derivative", tip: "d/dx, with the real steps (uneven ones too)", along: ["x", "traces"] },
  { op: "smooth", name: "Smooth", tip: "Running mean over N points (missing points skipped)", along: ["x", "traces"], n: 5 },
  { op: "subtract_first", name: "Subtract the first trace", tip: "Each trace minus the first shown one", along: ["traces"] },
  { op: "subtract_previous", name: "Subtract the previous trace", tip: "Each trace minus the one before it", along: ["traces"] },
  { op: "average", name: "Average of the traces", tip: "One curve: the mean of the shown traces", along: ["traces"] },
  { op: "std", name: "Std of the traces", tip: "One curve: the standard deviation of the shown traces", along: ["traces"] },
  { op: "fft", name: "FFT", tip: "Amplitude spectrum, positive frequencies (needs even steps)", along: ["x", "traces"] },
  { op: "histogram", name: "Histogram", tip: "Counts of the values; the value becomes the horizontal axis", along: ["x", "traces"], bins: 50 },
];
const byOp = new Map(KINDS.map((k) => [k.op, k]));

export default function Operations({ kind, xLabel, tracesLabel, ops, on, info, onChange, onOn }: Props) {
  const [menu, setMenu] = useState<MenuAt | null>(null);
  const alongText = (a: "x" | "traces") => (a === "x" ? `along ${xLabel}` : kind === "heatmap" ? `along ${tracesLabel}` : `across ${tracesLabel ?? "traces"}`);
  const set = (i: number, patch: Partial<Op>) => onChange(ops.map((o, j) => (j === i ? { ...o, ...patch } : o)));
  const move = (i: number, by: number) => {
    const next = [...ops];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    onChange(next);
  };
  const add = (e: MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const items: MenuEntry[] = KINDS.map((k) => ({
      label: k.name,
      disabled: !tracesLabel && !k.along.includes("x"), // across traces needs several traces
      onClick: () =>
        onChange([...ops, { op: k.op, along: k.along.includes("x") ? "x" : "traces", ...(k.n ? { n: k.n } : {}), ...(k.bins ? { bins: k.bins } : {}) }]),
    }));
    setMenu({ x: r.left, y: r.bottom, items });
  };

  return (
    <fieldset className="field operations">
      <legend>
        Operations{" "}
        {ops.length > 0 && (
          <label className="check inline" title="Off: the stored data again (the list is kept)">
            <input type="checkbox" checked={on} onChange={(e) => onOn(e.target.checked)} /> on
          </label>
        )}
      </legend>
      {ops.length === 0 && <p className="muted small">None: the stored data is shown. Explore only; never written into the file.</p>}
      <ol className="op-list">
        {ops.map((o, i) => {
          const k = byOp.get(o.op);
          const note = info?.notes[i] ?? null;
          const bad = on && note !== null && note !== "off";
          return (
            <li key={i} className={bad ? "bad" : o.on === false || !on ? "off" : ""}>
              <div className="op-row">
                <input type="checkbox" checked={o.on !== false} onChange={(e) => set(i, { on: e.target.checked })} aria-label={`${k?.name ?? o.op} on`} />
                <span className="op-name" title={k?.tip}>
                  {k?.name ?? o.op}
                </span>
                <span className="spacer" />
                <button className="link" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up">
                  ▲
                </button>
                <button className="link" disabled={i === ops.length - 1} onClick={() => move(i, 1)} aria-label="Move down">
                  ▼
                </button>
                <button className="link" onClick={() => onChange(ops.filter((_, j) => j !== i))} aria-label={`Remove ${k?.name ?? o.op}`}>
                  ×
                </button>
              </div>
              <div className="op-settings">
                {k && k.along.length > 1 && tracesLabel ? (
                  <select aria-label={`${k.name}: along`} value={o.along ?? "x"} onChange={(e) => set(i, { along: e.target.value as "x" | "traces" })}>
                    {k.along.map((a) => (
                      <option key={a} value={a}>
                        {alongText(a)}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="muted small">{alongText(o.along ?? k?.along[0] ?? "x")}</span>
                )}
                {o.op === "smooth" && (
                  <label className="small">
                    over{" "}
                    <input
                      type="number"
                      min={2}
                      value={o.n ?? 5}
                      aria-label="Smooth: points"
                      onChange={(e) => set(i, { n: Math.max(2, Math.round(Number(e.target.value) || 2)) })}
                    />{" "}
                    points
                  </label>
                )}
                {o.op === "histogram" && (
                  <label className="small">
                    <input
                      type="number"
                      min={2}
                      max={10000}
                      value={o.bins ?? 50}
                      aria-label="Histogram: bins"
                      onChange={(e) => set(i, { bins: Math.min(10000, Math.max(2, Math.round(Number(e.target.value) || 2))) })}
                    />{" "}
                    bins
                  </label>
                )}
              </div>
              {bad && <div className="field-error">{note}</div>}
            </li>
          );
        })}
      </ol>
      <button onClick={add}>+ Add operation ▾</button>
      {on && info?.shows && (
        <div className="small">
          The plot shows <strong>{info.shows}</strong>
          {info.unit ? ` in ${info.unit}` : ""}
          {info.one_to_one === false && <span className="muted"> (no longer stored points: cursors read the shown values only)</span>}.
        </div>
      )}
      {menu && <ContextMenu menu={menu} onClose={() => setMenu(null)} />}
    </fieldset>
  );
}

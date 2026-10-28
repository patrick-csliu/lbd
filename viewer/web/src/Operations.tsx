import { KeyboardEvent, MouseEvent, useEffect, useState } from "react";
import { Op, OpName, OpsInfo } from "./api";
import { ContextMenu, MenuAt, MenuEntry } from "./menu";

/**
 * The Operations section of the Explore view's side panel: a list of operations on the data as
 * shown (subtract the mean, d/dx, smoothing, between traces, FFT, histogram), in any order. The
 * server runs them (operations.py) and says per row whether each applied, or why not; one that
 * can't apply is red, and the plot shows the result of the ones above it. A switch turns them all
 * off to compare with the stored data. Explore only: remembered with the view, never in the file.
 *
 * For complex values, a first group works on the complex numbers before the complex mode (dB,
 * phase …): electrical delay and rotation (each with Calculate, from the data between the cursors
 * or in view), auto-rotate, and the I/Q histogram (a map of counts; the last operation).
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
  /** The plotted value is complex: the complex group is offered. */
  complexValues: boolean;
  calculate: (what: "delay" | "rotation", index: number) => Promise<number>;
}

const COMPLEX: { op: OpName; name: string; tip: string }[] = [
  { op: "delay", name: "Electrical delay", tip: "× e^(i·2π·f·τ): removes a cable's phase slope. Calculate: from the phase between the cursors (else in view)" },
  { op: "rotation", name: "Rotation", tip: "× e^(iφ). Calculate: the angle that puts the I/Q points' spread onto the real axis" },
  { op: "auto_rotate", name: "Auto-rotate each trace", tip: "Each trace turned so its I/Q spread lies on the real axis" },
  { op: "iq_histogram", name: "I/Q histogram", tip: "The complex points counted in the I/Q plane: a map (the last operation)" },
];
const isComplex = (o: Op) => COMPLEX.some((c) => c.op === o.op);

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

export default function Operations({ kind, xLabel, tracesLabel, ops, on, info, onChange, onOn, complexValues, calculate }: Props) {
  const [menu, setMenu] = useState<MenuAt | null>(null);
  const [calcNote, setCalcNote] = useState<{ i: number; text: string } | null>(null);
  const runCalc = (i: number, what: "delay" | "rotation") => {
    setCalcNote(null);
    calculate(what, i)
      .then((v) => set(i, what === "delay" ? { tau: v } : { phi: v }))
      .catch((e) => setCalcNote({ i, text: (e as Error).message }));
  };
  const alongText = (a: "x" | "traces") => (a === "x" ? `along ${xLabel}` : kind === "heatmap" ? `along ${tracesLabel}` : `across ${tracesLabel ?? "traces"}`);
  const set = (i: number, patch: Partial<Op>) => onChange(ops.map((o, j) => (j === i ? { ...o, ...patch } : o)));
  const move = (i: number, by: number) => {
    const next = [...ops];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    onChange(next);
  };
  const add = (e: MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const firstReal = ops.findIndex((o) => !isComplex(o));
    const complexItems: MenuEntry[] = complexValues
      ? [
          ...COMPLEX.map((c) => ({
            label: c.name,
            disabled: c.op === "iq_histogram" && ops.some((o) => o.op === "iq_histogram"),
            onClick: () => {
              // on the complex values: after the complex ones, before the others
              const op: Op = { op: c.op, ...(c.op === "delay" ? { tau: 0 } : c.op === "rotation" ? { phi: 0 } : c.op === "iq_histogram" ? { bins: 100 } : {}) };
              const at = firstReal < 0 ? ops.length : firstReal;
              onChange([...ops.slice(0, at), op, ...ops.slice(at)]);
            },
          })),
          "-" as const,
        ]
      : [];
    const items: MenuEntry[] = [...complexItems, ...KINDS.map((k) => ({
      label: k.name,
      disabled: !tracesLabel && !k.along.includes("x"), // across traces needs several traces
      onClick: () =>
        onChange([...ops, { op: k.op, along: k.along.includes("x") ? "x" : "traces", ...(k.n ? { n: k.n } : {}), ...(k.bins ? { bins: k.bins } : {}) }]),
    }))];
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
          if (isComplex(o)) {
            const c = COMPLEX.find((x) => x.op === o.op)!;
            const note = info?.notes[i] ?? null;
            const bad = on && note !== null && note !== "off";
            const lastComplex = i + 1 >= ops.length || !isComplex(ops[i + 1]);
            return (
              <li key={i} className={"complex" + (bad ? " bad" : o.on === false || !on ? " off" : "")}>
                <div className="op-row">
                  <input type="checkbox" checked={o.on !== false} onChange={(e) => set(i, { on: e.target.checked })} aria-label={`${c.name} on`} />
                  <span className="op-name" title={c.tip}>
                    {c.name}
                  </span>
                  <span className="spacer" />
                  <button className="link" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up">
                    ▲
                  </button>
                  <button className="link" disabled={lastComplex} onClick={() => move(i, 1)} aria-label="Move down">
                    ▼
                  </button>
                  <button className="link" onClick={() => onChange(ops.filter((_, j) => j !== i))} aria-label={`Remove ${c.name}`}>
                    ×
                  </button>
                </div>
                <div className="op-settings">
                  {o.op === "delay" && (
                    <>
                      <label className="small">
                        τ{" "}
                        <NumberBox value={(o.tau ?? 0) * 1e9} label="Delay in ns" onSet={(v) => set(i, { tau: v * 1e-9 })} /> ns
                      </label>
                      <button onClick={() => runCalc(i, "delay")} title="From the phase between the cursors (else in view)">
                        Calculate
                      </button>
                    </>
                  )}
                  {o.op === "rotation" && (
                    <>
                      <label className="small">
                        φ <NumberBox value={o.phi ?? 0} label="Rotation in degrees" onSet={(v) => set(i, { phi: v })} /> °
                      </label>
                      <button onClick={() => runCalc(i, "rotation")} title="From the I/Q points between the cursors (else in view)">
                        Calculate
                      </button>
                    </>
                  )}
                  {o.op === "iq_histogram" && (
                    <label className="small">
                      <input
                        type="number"
                        min={2}
                        max={2000}
                        value={o.bins ?? 100}
                        aria-label="I/Q histogram: bins"
                        onChange={(e) => set(i, { bins: Math.min(2000, Math.max(2, Math.round(Number(e.target.value) || 2))) })}
                      />{" "}
                      bins each way
                    </label>
                  )}
                  <span className="muted small">on the complex values</span>
                </div>
                {calcNote?.i === i && <div className="field-error">{calcNote.text}</div>}
                {bad && <div className="field-error">{note}</div>}
              </li>
            );
          }
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
                <button className="link" disabled={i === 0 || isComplex(ops[i - 1])} onClick={() => move(i, -1)} aria-label="Move up">
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

/** A number typed in a box, applied on Enter or when leaving it; a wrong entry says so. */
function NumberBox({ value, label, onSet }: { value: number; label: string; onSet: (v: number) => void }) {
  const shown = Number(value.toPrecision(7)).toString();
  const [text, setText] = useState(shown);
  const [bad, setBad] = useState(false);
  useEffect(() => {
    setText(shown);
    setBad(false);
  }, [shown]);
  const apply = () => {
    const v = Number(text.trim().replace("−", "-"));
    if (text.trim() === "" || !Number.isFinite(v)) return setBad(true);
    setBad(false);
    if (v !== value) onSet(v);
  };
  return (
    <input
      className="op-number"
      value={text}
      aria-label={label}
      aria-invalid={bad}
      title={bad ? "Not a number" : undefined}
      onChange={(e) => setText(e.target.value)}
      onBlur={apply}
      onKeyDown={(e: KeyboardEvent) => e.key === "Enter" && apply()}
    />
  );
}

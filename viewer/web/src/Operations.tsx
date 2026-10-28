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
 * Below the list, equations like Labber's: `x =`, `y =` (maps also `z =`), applied after the
 * operations, with a legend above them of what each name stands for (and in which stored unit).
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
  equations: { x?: string; y?: string; z?: string };
  onEquations: (e: { x?: string; y?: string; z?: string }) => void;
}

const EQ_FUNCTIONS = "sin cos tan arcsin arccos arctan arctan2 sinh cosh tanh exp log log10 log2 sqrt abs real imag angle conj floor ceil round clip";
const EQ_PER_TRACE = "mean median std min max";

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
  { op: "smooth", name: "Smooth", tip: "Running mean, Gaussian or median over a few points (missing points skipped)", along: ["x", "traces"], n: 5 },
  { op: "subtract_first", name: "Subtract the first trace", tip: "Each trace minus the first shown one", along: ["traces"] },
  { op: "subtract_previous", name: "Subtract the previous trace", tip: "Each trace minus the one before it", along: ["traces"] },
  { op: "average", name: "Average of the traces", tip: "One curve: the mean of the shown traces", along: ["traces"] },
  { op: "std", name: "Std of the traces", tip: "One curve: the standard deviation of the shown traces", along: ["traces"] },
  { op: "fft", name: "FFT", tip: "Amplitude spectrum, positive frequencies (needs even steps)", along: ["x", "traces"] },
  { op: "histogram", name: "Histogram", tip: "Counts of the values; the value becomes the horizontal axis", along: ["x", "traces"], bins: 50 },
];
const byOp = new Map(KINDS.map((k) => [k.op, k]));

export default function Operations({ kind, xLabel, tracesLabel, ops, on, info, onChange, onOn, complexValues, calculate, equations, onEquations }: Props) {
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
                  <select aria-label="Smooth: method" value={o.method ?? "mean"} onChange={(e) => {
                    const method = e.target.value as Op["method"];
                    const n = o.n ?? 5;
                    set(i, method === "median" && n % 2 === 0 ? { method, n: n + 1 } : { method });   // a median needs an odd window
                  }}>
                    <option value="mean">running mean</option>
                    <option value="gaussian">Gaussian</option>
                    <option value="median">median</option>
                  </select>
                )}
                {o.op === "smooth" && (o.method ?? "mean") !== "gaussian" && (
                  <label className="small" title={o.method === "median" ? "An odd number: the median of each window" : undefined}>
                    over <PointsBox value={o.n ?? 5} odd={o.method === "median"} onSet={(n) => set(i, { n })} /> points
                  </label>
                )}
                {o.op === "smooth" && o.method === "gaussian" && (
                  <label className="small" title="The Gaussian's width in points (it reaches ±3σ)">
                    σ <NumberBox value={o.sigma ?? 2} label="Smooth: σ in points" onSet={(v) => set(i, { sigma: v })} /> points
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
      <Equations
        kind={kind}
        equations={equations}
        info={info}
        on={on}
        onChange={onEquations}
      />
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

/** The number of points to smooth over. Typing is free (e.g. "1" on the way to "15"); a whole
 * number ≥ 2 (odd for a median) applies as it is typed, anything else says why when leaving the
 * box. The arrows step through allowed numbers only. */
function PointsBox({ value, odd, onSet }: { value: number; odd: boolean; onSet: (n: number) => void }) {
  const [text, setText] = useState(String(value));
  const [bad, setBad] = useState<string | null>(null);
  useEffect(() => {
    setText(String(value));
    setBad(null);
  }, [value]);
  const why = (t: string) => {
    const n = Number(t.trim());
    if (!Number.isInteger(n) || n < 2) return "A whole number of points, 2 or more";
    if (odd && n % 2 === 0) return "An odd number: the median of each window";
    return null;
  };
  return (
    <>
    <input
      type="number"
      className="op-number"
      min={odd ? 3 : 2}
      step={odd ? 2 : 1}
      value={text}
      aria-label="Smooth: points"
      aria-invalid={!!bad}
      title={bad ?? (odd ? "An odd number: the median of each window" : undefined)}
      onChange={(e) => {
        setText(e.target.value);
        if (!why(e.target.value)) {
          setBad(null);
          onSet(Number(e.target.value));
        }
      }}
      onBlur={() => setBad(why(text))}
      onKeyDown={(e: KeyboardEvent) => e.key === "Enter" && setBad(why(text))}
    />
    {bad && <span className="field-error"> {bad}</span>}
    </>
  );
}

/** The equation fields, after the operations, with the legend of names above them. */
function Equations({ kind, equations, info, on, onChange }: {
  kind: "curve" | "heatmap";
  equations: { x?: string; y?: string; z?: string };
  info: OpsInfo | null;
  on: boolean;
  onChange: (e: { x?: string; y?: string; z?: string }) => void;
}) {
  const fields = (kind === "heatmap" ? ["x", "y", "z"] : ["x", "y"]) as ("x" | "y" | "z")[];
  const names = info?.names ?? [];
  const main = names.filter((n) => fields.includes(n.name as "x" | "y" | "z"));
  const others = names.filter((n) => !fields.includes(n.name as "x" | "y" | "z"));
  return (
    <div className="equations">
      <div className="eq-title">Equations (after the operations)</div>
      <div className="eq-legend small" aria-label="What the names stand for">
        {main.map((n) => (
          <div key={n.name}>
            <code>{n.name}</code> = {n.means}
          </div>
        ))}
        {others.map((n) => (
          <div key={n.name} className="muted">
            <code>{n.name}</code> = {n.means}
          </div>
        ))}
        <div className="muted">
          in stored units · <code>pi</code> <code>e</code> · {EQ_FUNCTIONS} · per trace: {EQ_PER_TRACE}
        </div>
      </div>
      {fields.map((f) => {
        const st = info?.equations?.[f];
        return (
          <EquationBox
            key={f}
            field={f}
            value={equations[f] ?? ""}
            error={on ? st?.error : undefined}
            note={on ? st?.note : undefined}
            onSet={(v) => {
              const next = { ...equations, [f]: v || undefined };
              onChange(next);
            }}
          />
        );
      })}
    </div>
  );
}

function EquationBox({ field, value, error, note, onSet }: { field: string; value: string; error?: string; note?: string; onSet: (v: string) => void }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const apply = () => {
    if (text.trim() !== value) onSet(text.trim());
  };
  return (
    <div className={"eq-field" + (error ? " bad" : "")}>
      <label>
        <code>{field} =</code>
        <input
          value={text}
          spellCheck={false}
          placeholder={`(none: ${field} as it is)`}
          aria-label={`Equation for ${field}`}
          aria-invalid={!!error}
          onChange={(e) => setText(e.target.value)}
          onBlur={apply}
          onKeyDown={(e: KeyboardEvent) => {
            if (e.key === "Enter") apply();
            if (e.key === "Escape") setText(value);
          }}
        />
      </label>
      {error && <div className="field-error">{error}</div>}
      {note && <div className="muted small">{note}</div>}
    </div>
  );
}

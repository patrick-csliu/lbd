import { KeyboardEvent, MutableRefObject, useEffect, useState } from "react";
import { CursorRead, CursorsAnswer, CursorType, ReadItem } from "./api";
import { between, CursorsState, item, si } from "./cursors";
import { ExploreActions } from "./ExploreView";

/**
 * The Cursors section of the Explore view's side panel: the cursor type, each cursor's numbers
 * (positions can be typed), differences and means, Max · Min · Peak, the cuts of a map and
 * taking a cut out. The plot itself does the same with the mouse and keys (ExploreView).
 */

interface Props {
  kind: "curve" | "heatmap";
  cursors: CursorsState;
  onCursors: (c: CursorsState) => void;
  reading: CursorsAnswer | null;
  actions: MutableRefObject<ExploreActions | null>;
  /** Shown after "Show row / column as curve": go back to the map. */
  onBack: (() => void) | null;
}

const TYPES: [CursorType, string, string][] = [
  ["cross", "Crosshair", "A point (curves) or cell (maps)"],
  ["vertical", "Vertical", "A line at one x: every trace's value there"],
  ["horizontal", "Horizontal", "A line at one y: a level"],
];

const PREFIX: Record<string, number> = { T: 1e12, G: 1e9, M: 1e6, k: 1e3, m: 1e-3, u: 1e-6, µ: 1e-6, n: 1e-9, p: 1e-12, f: 1e-15 };

/** A typed number in a unit, with an optional SI prefix: "5.12 GHz", "5.12G", "5120000000". */
export function parseSi(text: string, unit: string): number | null {
  let t = text.trim().replace("−", "-");
  if (unit && t.endsWith(unit)) t = t.slice(0, -unit.length).trim();
  let f = 1;
  const last = t.slice(-1);
  if (last in PREFIX && !/[0-9.]/.test(last)) {
    f = PREFIX[last];
    t = t.slice(0, -1).trim();
  }
  if (!/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(t)) return null;
  return Number(t) * f;
}

/** A position box: shows the stored value; Enter or leaving it moves the cursor there. */
function PositionBox({ it, onSet }: { it: ReadItem; onSet: (v: number) => void }) {
  const shown = si(it.value, it.unit);
  const [text, setText] = useState(shown);
  const [bad, setBad] = useState<string | null>(null);
  useEffect(() => {
    setText(shown);
    setBad(null);
  }, [shown]);
  const apply = () => {
    if (text === shown) return;
    const v = parseSi(text, it.unit);
    if (v === null) {
      setBad(`Not a number${it.unit ? ` in ${it.unit}` : ""}: e.g. 5.12${it.unit ? " k" + it.unit : ""}`);
      return;
    }
    setBad(null);
    onSet(v);
  };
  return (
    <label className="cursor-field">
      <span>{it.label}</span>
      <input
        value={text}
        aria-label={`${it.label} of the cursor`}
        aria-invalid={!!bad}
        onChange={(e) => setText(e.target.value)}
        onBlur={apply}
        onKeyDown={(e: KeyboardEvent) => {
          if (e.key === "Enter") apply();
          if (e.key === "Escape") setText(shown);
        }}
      />
      {bad && <span className="field-error">{bad}</span>}
    </label>
  );
}

function CursorNumbers({ n, c, kind, type, actions }: { n: number; c: CursorRead; kind: string; type: CursorType; actions: MutableRefObject<ExploreActions | null> }) {
  const x = item(c, "x"), y = item(c, "y"), z = item(c, "z"), series = item(c, "series");
  // what can be typed: x always; y on maps and for a horizontal line; on curves y is the trace's value
  const yEditable = kind === "heatmap" || type === "horizontal";
  return (
    <div className="cursor-numbers">
      <div className="cursor-head">
        <span className={`cursor-tag c${n}`}>{n}</span>
        {c.label && kind === "curve" && <span className="small">{c.label}</span>}
        {c.free && <span className="muted small">free position</span>}
      </div>
      {x && type !== "horizontal" && <PositionBox it={x} onSet={(v) => actions.current?.typed(n - 1, "x", v)} />}
      {y && yEditable && <PositionBox it={y} onSet={(v) => actions.current?.typed(n - 1, "y", v)} />}
      {y && !yEditable && (
        <div className="cursor-value">
          {y.label} = <strong>{si(y.value, y.unit)}</strong>
        </div>
      )}
      {z && (
        <div className="cursor-value">
          {z.label} = <strong>{si(z.value, z.unit)}</strong>
        </div>
      )}
      {series && (
        <div className="cursor-value muted small">
          {series.label} = {si(series.value, series.unit)}
        </div>
      )}
      <div className="muted small">
        stored at{" "}
        {Object.entries(c.index)
          .map(([a, i]) => `${a}[${i}]`)
          .join(", ")}
      </div>
    </div>
  );
}

export default function CursorPanel({ kind, cursors, onCursors, reading, actions, onBack }: Props) {
  const list = reading?.cursors ?? [];
  const [c1, c2] = [list[0] ?? null, list[1] ?? null];
  const act = (fn: (a: ExploreActions) => void) => () => actions.current && fn(actions.current);
  return (
    <fieldset className="field cursor-panel">
      <legend>Cursors</legend>
      {onBack && (
        <button onClick={onBack} title="Back to the map this curve was taken from">
          ◂ Back to the map
        </button>
      )}
      <div className="segmented" role="radiogroup" aria-label="Cursor type">
        {TYPES.map(([t, text, tip]) => (
          <button
            key={t}
            role="radio"
            aria-checked={cursors.type === t}
            className={cursors.type === t ? "on" : ""}
            title={tip}
            onClick={() => onCursors({ ...cursors, type: t })}
          >
            {text}
          </button>
        ))}
      </div>
      {!c1 && <p className="muted small">Click the plot for cursor 1, Shift+click for cursor 2.</p>}
      {c1 && <CursorNumbers n={1} c={c1} kind={kind} type={cursors.type} actions={actions} />}
      {c2 && <CursorNumbers n={2} c={c2} kind={kind} type={cursors.type} actions={actions} />}
      {c1 && c2 && (
        <table className="cursor-between small">
          <tbody>
            {between(c1, c2).map((d) => (
              <tr key={d.role}>
                <th>{d.label}</th>
                <td>Δ {si(d.delta, d.unit)}</td>
                <td>mean {si(d.mean, d.unit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {c1?.table && (
        <div className="cursor-table small" aria-label="Every trace at the cursor">
          <table>
            <tbody>
              {c1.table.rows.map((r) => (
                <tr key={r.trace} className={r.trace === c1.trace ? "on" : ""}>
                  <th>{r.label}</th>
                  <td>{si(r.value, c1.table!.unit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {c1.table.more > 0 && <div className="muted">and {c1.table.more} more</div>}
        </div>
      )}
      <div className="row-controls">
        <button onClick={act((a) => a.find("max"))} title="Key M">
          Max
        </button>
        <button onClick={act((a) => a.find("min"))} title="Key N">
          Min
        </button>
        <button onClick={act((a) => a.find("peak"))} title="Farthest from the median, up or down (a dip or a spike). Key P">
          Peak
        </button>
        <button onClick={act((a) => a.remove())} disabled={!c1} title="Key Esc">
          Remove
        </button>
      </div>
      <div className="muted small">
        {c1 && c2 ? "Searches between the cursors" : "Searches what is in view"}
        {kind === "curve" && c1 ? `, on ${c1.label ?? "the cursor's trace"}` : ""}.
      </div>
      {kind === "heatmap" && (
        <>
          <label className="check">
            <input type="checkbox" checked={cursors.cuts} onChange={(e) => onCursors({ ...cursors, cuts: e.target.checked })} />
            Cuts beside the map (key C)
          </label>
          <div className="row-controls">
            <button disabled={!c1} onClick={act((a) => a.showCut("row"))} title="This tab then shows the row as a curve">
              Row as curve
            </button>
            <button disabled={!c1} onClick={act((a) => a.showCut("column"))} title="This tab then shows the column as a curve">
              Column as curve
            </button>
          </div>
          <div className="row-controls">
            <button disabled={!c1} onClick={act((a) => a.saveCut("row"))}>
              Save row…
            </button>
            <button disabled={!c1} onClick={act((a) => a.saveCut("column"))}>
              Save column…
            </button>
          </div>
        </>
      )}
      {kind === "curve" && (
        <button disabled={!c1} onClick={act((a) => a.saveCut("trace"))} title="The cursor's trace as a new .lbd file">
          Save trace…
        </button>
      )}
    </fieldset>
  );
}

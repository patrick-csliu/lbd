import { KeyboardEvent, MutableRefObject, useEffect, useState } from "react";
import { api, ApiError, CursorRead, CursorsAnswer, CursorType, ReadItem } from "./api";
import { between, CursorsState, item, si } from "./cursors";
import { ExploreActions } from "./ExploreView";
import { Segmented } from "./settingsUi";
import { useToast } from "./toast";

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
  /** Several panels with the cursor shared: the other panels' read-outs at the same x. */
  others?: OtherPanel[];
  /** Save the row, column or trace through cursor 1 as CSV. */
  onSaveCut: (which: "row" | "column" | "trace") => void;
  /** The data file: where the table at a cursor line says it comes from. */
  file: { path: string; name: string; id?: string | null };
}

/** A table of what a vertical or horizontal cursor reads at its line, as text and as numbers. */
function lineRows(c1: CursorRead, c2: CursorRead | null): { title: string; head: string[]; rows: { key: number; on: boolean; cells: string[]; raw: (number | string)[] }[]; more: number; about: boolean } | null {
  const about = (c1.table ?? c1.crossings)?.mode === "interpolated";
  if (c1.table) {
    const x = item(c1, "x");
    const t2 = c2?.table;
    const unit = c1.table.unit;
    return {
      title: `Every trace at ${x?.label ?? "x"} = ${si(x?.value ?? c1.table.rows[0]?.x ?? null, x?.unit ?? "")}`,
      head: t2 ? ["Trace", "Cursor 1", "Cursor 2", "Δ"] : ["Trace", c1.table.label],
      about,
      more: c1.table.more,
      rows: c1.table.rows.map((r) => {
        const u = r.unit ?? unit;
        const other = t2?.rows.find((q) => q.trace === r.trace);
        const d = other && r.value !== null && other.value !== null ? other.value - r.value : null;
        return {
          key: r.trace,
          on: r.trace === c1.trace,
          cells: t2 ? [r.label, si(r.value, u), si(other?.value ?? null, u), si(d, u)] : [r.label, si(r.value, u)],
          raw: t2 ? [r.label, r.value ?? "", other?.value ?? "", d ?? ""] : [r.label, r.value ?? ""],
        };
      }),
    };
  }
  if (c1.crossings) {
    const k = c1.crossings;
    return {
      title: `Where the traces cross ${k.label} = ${si(k.y, k.unit)}`,
      head: ["Trace", k.x_label, "Between"],
      about,
      more: k.more,
      rows: k.rows.map((r) => {
        const width = r.x.length === 2 ? Math.abs(r.x[1] - r.x[0]) : null;
        return {
          key: r.trace,
          on: r.trace === c1.trace,
          cells: [r.label, r.x.length ? r.x.map((v) => si(v, k.x_unit)).join(", ") + (r.more ? `, and ${r.more} more` : "") : "doesn't cross", width === null ? "" : `Δ ${si(width, k.x_unit)}`],
          raw: [r.label, r.x.join(" "), width ?? ""],
        };
      }),
    };
  }
  return null;
}

/** What a vertical or horizontal cursor reads on every trace, with Copy and Save as CSV. */
function LineTable({ c1, c2, file }: { c1: CursorRead; c2: CursorRead | null; file: Props["file"] }) {
  const toast = useToast();
  const t = lineRows(c1, c2);
  if (!t) return null;
  const say = t.about ? " (≈ between stored points)" : " (the nearest stored points)";
  const copy = async () => {
    const text = [t.head.join("\t"), ...t.rows.map((r) => r.raw.join("\t"))].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied: paste it into a spreadsheet or your notes.");
    } catch {
      toast("Couldn't use the clipboard here.", "error");
    }
  };
  const saveCsv = async () => {
    const quote = (v: number | string) => (typeof v === "string" && /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : String(v));
    const lines = [
      `# ${t.head.join(",")}`,
      `# LBD export: ${file.name}`,
      `# id: ${file.id ?? "none (the file has no id; LBD gives it one when it next saves the file)"}`,
      `# ${t.title}${t.about ? ", interpolated between stored points" : ", the nearest stored points"}`,
      ...t.rows.map((r) => r.raw.map(quote).join(",")),
    ];
    try {
      const { path } = await api.pickSave(file.path, `${file.name.replace(/\.lbd(\.writing)?$/i, "")} - at the cursor.csv`, "csv", "Save the traces at the cursor");
      if (path === null) return;
      await api.savePicture(path, new Blob([lines.join("\n") + "\n"], { type: "text/csv" }));
      toast(`Saved ${path}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 501) toast("This computer has no Save dialog here: use Copy.", "error");
      else toast((e as Error).message, "error");
    }
  };
  return (
    <div className="cursor-line">
      <div className="cursor-line-head small">
        <span title={t.title + say}>
          {t.title}
          {t.about ? " ≈" : ""}
        </span>
        <span className="row-controls">
          <button onClick={copy} title="Copy this table: paste it into a spreadsheet or your notes">
            Copy
          </button>
          <button onClick={saveCsv} title="Save this table as a CSV file">
            Save as CSV…
          </button>
        </span>
      </div>
      <div className="cursor-table small" aria-label={t.title}>
        <table>
          {t.head.length > 2 && (
            <thead>
              <tr>
                {t.head.map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
          )}
          <tbody>
            {t.rows.map((r) => (
              <tr key={r.key} className={r.on ? "on" : ""}>
                <th>{r.cells[0]}</th>
                {r.cells.slice(1).map((v, i) => (
                  <td key={i}>{v}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {t.more > 0 && <div className="muted">and {t.more} more</div>}
      </div>
    </div>
  );
}

/** Another panel's read-out at the shared cursor. */
export interface OtherPanel {
  n: number; // its number
  title: string;
  reading: CursorsAnswer | null;
}

/** A panel's value at a cursor: the trace's y (curves) or the cell's z (maps). */
const valueOf = (c: CursorRead | null) => (c ? item(c, "z") ?? item(c, "y") : undefined);

function OtherPanels({ others, two }: { others: OtherPanel[]; two: boolean }) {
  return (
    <div className="cursor-others small" aria-label="The other panels at the same x">
      <div className="muted">The other panels at the same x:</div>
      <table>
        <tbody>
          {others.map((o) => {
            const a = o.reading?.cursors[0] ?? null, b = o.reading?.cursors[1] ?? null;
            const va = valueOf(a), vb = valueOf(b);
            return (
              <tr key={o.n}>
                <th>
                  {o.n} {o.title}
                </th>
                <td>
                  <span className="cursor-tag c1">1</span> {va ? si(va.value, va.unit) : "—"}
                </td>
                {two && (
                  <td>
                    <span className="cursor-tag c2">2</span> {vb ? si(vb.value, vb.unit) : "—"}
                    {va && vb && va.value !== null && vb.value !== null && va.unit === vb.unit && <> · Δ {si(vb.value - va.value, va.unit)}</>}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
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
  const shown = it.text ?? si(it.value, it.unit);
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
        {n === 2 && (
          <button className="ib cursor-remove" aria-label="Remove cursor 2" title="Remove cursor 2 (cursor 1 stays)" onClick={() => actions.current?.removeSecond()}>
            ×
          </button>
        )}
      </div>
      {x && type !== "horizontal" && <PositionBox it={x} onSet={(v) => actions.current?.typed(n - 1, "x", v)} />}
      {y && yEditable && <PositionBox it={y} onSet={(v) => actions.current?.typed(n - 1, "y", v)} />}
      {y && !yEditable && (
        <div className="cursor-value">
          {y.label} = <strong>{y.text ?? si(y.value, y.unit)}</strong>
        </div>
      )}
      {z && (
        <div className="cursor-value">
          {z.label} = <strong>{z.text ?? si(z.value, z.unit)}</strong>
        </div>
      )}
      {series && (
        <div className="cursor-value muted small">
          {series.label} = {si(series.value, series.unit)}
        </div>
      )}
      {c.stored && (
        <div className="cursor-value muted small">
          stored: {c.stored.label} = {si(c.stored.value, c.stored.unit)}
        </div>
      )}
      {Object.keys(c.index).length > 0 ? (
        <div className="muted small">
          stored at{" "}
          {Object.entries(c.index)
            .map(([a, i]) => `${a}[${i}]`)
            .join(", ")}
        </div>
      ) : (
        <div className="muted small">a shown point (made by the operations), not a stored one</div>
      )}
    </div>
  );
}

export default function CursorPanel({ kind, cursors, onCursors, reading, actions, onBack, others = [], onSaveCut, file }: Props) {
  const list = reading?.cursors ?? [];
  const [c1, c2] = [list[0] ?? null, list[1] ?? null];
  const act = (fn: (a: ExploreActions) => void) => () => actions.current && fn(actions.current);
  const back = onBack && (
    <button onClick={onBack} title="Back to the map this curve was taken from">
      ◂ Back to the map
    </button>
  );
  // The type buttons are also the switch: the chosen type clicked again means no cursors (a click
  // on the plot then does nothing); choosing a type brings the same cursors back.
  const types = (
    <div className="segmented" role="group" aria-label="Cursor type">
      {TYPES.map(([t, text, tip]) => {
        const chosen = cursors.on && cursors.type === t;
        return (
          <button
            key={t}
            aria-pressed={chosen}
            className={chosen ? "on" : ""}
            title={chosen ? `${tip}. Click again for no cursors (key K)` : tip}
            onClick={() => onCursors(chosen ? { ...cursors, on: false } : { ...cursors, type: t, on: true })}
          >
            {text}
          </button>
        );
      })}
    </div>
  );
  if (!cursors.on) {
    return (
      <fieldset className="field cursor-panel">
        <legend>Cursors</legend>
        {back}
        {types}
        <p className="muted small">No cursor type chosen: a click on the plot does nothing. Choose one to read values.</p>
      </fieldset>
    );
  }
  return (
    <fieldset className="field cursor-panel">
      <legend>Cursors</legend>
      {back}
      <div className="cursor-types-row">
        {types}
        <button onClick={act((a) => a.remove())} disabled={!c1} title="Remove both cursors (key Esc); Undo in the message">
          Remove cursors
        </button>
      </div>
      {!c1 && <p className="muted small">Click the plot for cursor 1, Shift+click for cursor 2.</p>}
      {c1 && <CursorNumbers n={1} c={c1} kind={kind} type={cursors.type} actions={actions} />}
      {c2 && <CursorNumbers n={2} c={c2} kind={kind} type={cursors.type} actions={actions} />}
      {kind === "curve" && cursors.type !== "cross" && (
        <div className="cursor-line-choice">
          <label className="check" title="Mark where the line meets each visible trace, and list the numbers there">
            <input type="checkbox" checked={cursors.every !== false} onChange={(e) => onCursors({ ...cursors, every: e.target.checked })} />
            Every trace at the line
          </label>
          {cursors.every !== false && (
            <div className="field">
              <span className="small">Values at the line</span>
              <Segmented
                name="cursor-at-line"
                label="Values at the line"
                value={cursors.at_line ?? "interpolated"}
                options={[
                  ["interpolated", "Interpolated", "Worked out between a trace's two neighbouring stored points: every row at exactly the line"],
                  ["stored", "Nearest stored point", "The stored point of each trace nearest the line: numbers straight from the file, each row at its own place"],
                ]}
                onChange={(v) => onCursors({ ...cursors, at_line: v })}
              />
            </div>
          )}
        </div>
      )}
      {c1 && (c1.table || c1.crossings) && <LineTable c1={c1} c2={c2} file={file} />}
      {c2 && c2.crossings && <LineTable c1={c2} c2={null} file={file} />}
      {c1?.line_note && <p className="muted small">{c1.line_note}</p>}
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
      {c1 && others.length > 0 && <OtherPanels others={others} two={!!c2} />}
      <div className="cursor-find" role="group" aria-label="Move cursor 1 to the highest, lowest or farthest value">
        <span className="small">Move cursor 1 to:</span>
        <span className="cursor-find-buttons">
          <button onClick={act((a) => a.find("max"))} title="The highest stored value. Key M">
            Max
          </button>
          <button onClick={act((a) => a.find("min"))} title="The lowest stored value. Key N">
            Min
          </button>
          <button onClick={act((a) => a.find("peak"))} title="Farthest from the median, up or down (a dip or a spike). Key P">
            Peak
          </button>
        </span>
        <div className="muted small cursor-find-where">
          {c1 && c2 ? "Between the cursors" : "In what is in view"}
          {kind === "curve" && c1 ? `, on ${c1.label ?? "the cursor's trace"}` : ""}. Peak: farthest from the median, a dip or a spike.
        </div>
      </div>
      {kind === "heatmap" && (
        <>
          <div className="row-controls">
            <button disabled={!c1} onClick={act((a) => a.showCut("row"))} title="This tab then shows the row as a curve">
              Row as curve
            </button>
            <button disabled={!c1} onClick={act((a) => a.showCut("column"))} title="This tab then shows the column as a curve">
              Column as curve
            </button>
          </div>
          <div className="row-controls">
            <button disabled={!c1} onClick={() => onSaveCut("row")} title="The row through the cursor as a CSV file">
              Save row as CSV…
            </button>
            <button disabled={!c1} onClick={() => onSaveCut("column")} title="The column through the cursor as a CSV file">
              Save column as CSV…
            </button>
          </div>
        </>
      )}
      {kind === "curve" && (
        <button disabled={!c1} onClick={() => onSaveCut("trace")} title="The cursor's trace as a CSV file">
          Save trace as CSV…
        </button>
      )}
    </fieldset>
  );
}

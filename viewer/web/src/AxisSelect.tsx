import { MouseEvent, useEffect, useRef, useState } from "react";
import { api, AxisValues } from "./api";

/**
 * Choose positions of an axis: which curves are drawn, or which rows make a map.
 *
 * A click on a value shows only that one; Shift-click: everything from the last clicked value to
 * this one; Ctrl/⌘-click or the box: add or remove one. "All" and "None" at the top. `chosen` is
 * null when all are shown.
 */
interface Props {
  path: string;
  version: string | null;
  axis: string;
  title: string;
  chosen: number[] | null;
  onChange: (chosen: number[] | null) => void;
}

export default function AxisSelect({ path, version, axis, title, chosen, onChange }: Props) {
  const [values, setValues] = useState<AxisValues | null>(null);
  const [error, setError] = useState<string | null>(null);
  const anchor = useRef<number | null>(null);

  useEffect(() => {
    let live = true;
    api
      .axis(path, axis)
      .then((v) => live && setValues(v))
      .catch((e) => live && setError((e as Error).message));
    return () => {
      live = false;
    };
  }, [path, axis, version]);

  if (error) return <div className="field muted small">{title}: {error}</div>;
  if (!values) return <div className="field muted small">{title}: reading…</div>;
  const n = values.values.length;
  const on = new Set(chosen ?? values.values.map((_, i) => i));
  const set = (s: Set<number>) => onChange(s.size === n ? null : [...s].sort((a, b) => a - b));

  const click = (e: MouseEvent, i: number) => {
    if (e.shiftKey && anchor.current !== null) {
      const [a, b] = [anchor.current, i].sort((x, y) => x - y);
      set(new Set(Array.from({ length: b - a + 1 }, (_, k) => a + k)));
    } else if (e.ctrlKey || e.metaKey) {
      const next = new Set(on);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      set(next);
      anchor.current = i;
    } else {
      set(new Set([i]));
      anchor.current = i;
    }
  };
  const toggle = (i: number) => {
    const next = new Set(on);
    if (next.has(i)) next.delete(i);
    else next.add(i);
    set(next);
    anchor.current = i;
  };

  return (
    <fieldset className="field axis-select">
      <legend>
        {title} <span className="muted small">{on.size === n ? `all ${n}` : `${on.size} of ${n}`}</span>
      </legend>
      <div className="row-controls">
        <button onClick={() => onChange(null)} disabled={on.size === n}>
          All
        </button>
        <button onClick={() => onChange([])} disabled={on.size === 0}>
          None
        </button>
      </div>
      <ul className="axis-values" aria-label={title}>
        {values.values.map((v, i) => (
          <li key={i} className={on.has(i) ? "on" : ""}>
            <input type="checkbox" aria-label={`${values.label} ${v ?? "—"}`} checked={on.has(i)} onChange={() => toggle(i)} />
            <span onClick={(e) => click(e, i)}>
              {v === null ? "—" : Number(v.toPrecision(6))}
              {values.unit ? ` ${values.unit}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </fieldset>
  );
}

import { useEffect, useState } from "react";

/** Two number boxes, "from" and "to"; empty means automatic. A wrong entry is said at the box and
 *  the last good value is kept. */
export default function NumberRange({
  label,
  value,
  log,
  onChange,
}: {
  label: string;
  value: [number | null, number | null];
  log: boolean;
  onChange: (v: [number | null, number | null]) => void;
}) {
  const shown = (v: number | null) => (v === null ? "" : String(Number(v.toPrecision(7))));
  const [text, setText] = useState<[string, string]>([shown(value[0]), shown(value[1])]);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => setText([shown(value[0]), shown(value[1])]), [value[0], value[1]]); // eslint-disable-line react-hooks/exhaustive-deps

  const commit = () => {
    const parsed = text.map((t) => (t.trim() === "" ? null : Number(t.trim()))) as [number | null, number | null];
    if (parsed.some((v) => v !== null && !Number.isFinite(v))) return fail("Type numbers, or leave a box empty for automatic");
    if (parsed[0] !== null && parsed[1] !== null && parsed[0] >= parsed[1]) return fail("'from' must be lower than 'to'");
    if (log && parsed.some((v) => v !== null && v <= 0)) return fail("A log scale needs numbers above 0");
    setNote(null);
    if (parsed[0] !== value[0] || parsed[1] !== value[1]) onChange(parsed);
  };
  const fail = (msg: string) => {
    setNote(msg);
    setText([shown(value[0]), shown(value[1])]);
  };
  const box = (i: 0 | 1, name: string) => (
    <input
      aria-label={`${label} ${name}`}
      value={text[i]}
      placeholder="auto"
      onChange={(e) => setText(i === 0 ? [e.target.value, text[1]] : [text[0], e.target.value])}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
  return (
    <div className="field number-range">
      <span>{label}</span>
      <div className="row-controls">
        {box(0, "from")}
        <span className="muted">to</span>
        {box(1, "to")}
      </div>
      {note && <span className="muted small">{note}</span>}
    </div>
  );
}

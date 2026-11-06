import { useEffect, useState } from "react";
import { api, FileInfo, PlotSpec } from "./api";
import { COMPLEX_MODES } from "./FileView";

/** Fields shared by the plot types that show their own data choices (Matrix, Bars, 3D bars). */

/** The values this plot type can draw, from the server (it knows a data point's own axes). */
export function useValuesFor(path: string, kind: string): string[] | null {
  const [names, setNames] = useState<string[] | null>(null);
  useEffect(() => {
    let current = true;
    api.kinds(path, {}).then(
      (r) => current && setNames(r.kinds.find((k) => k.name === kind)?.values ?? []),
      () => current && setNames(null),
    );
    return () => {
      current = false;
    };
  }, [path, kind]);
  return names;
}

/** Every axis of the plotted value, drawn or with a slider, with a name to show. */
export function axisChoices(info: FileInfo, r: PlotSpec, drawn: (string | undefined)[]): { name: string; text: string }[] {
  const names = [...drawn.filter((a): a is string => !!a && a !== "none"), ...(r.slices ?? []).map((s) => s.axis)];
  const text = (name: string) => {
    const a = info.axes.find((x) => x.name === name);
    return a?.label || (r.slices ?? []).find((s) => s.axis === name)?.label || name;
  };
  return [...new Set(names)].map((name) => ({ name, text: text(name) }));
}

export function ValueSelect({ info, r, names, onChoose }: { info: FileInfo; r: PlotSpec; names: string[] | null; onChoose: (name: string) => void }) {
  const shown = names ?? r.values ?? [];
  return (
    <label className="field">
      <span>Value</span>
      <select aria-label="Value" value={r.values?.[0] ?? ""} onChange={(e) => onChoose(e.target.value)}>
        {shown.map((name) => {
          const v = info.values.find((x) => x.name === name);
          return (
            <option key={name} value={name}>
              {v?.label || name}
            </option>
          );
        })}
      </select>
    </label>
  );
}

/** The usual complex choice, with Re and Im side by side. */
export function ComplexSelect({ r, update }: { r: PlotSpec; update: (patch: PlotSpec) => void }) {
  return (
    <label className="field">
      <span>Complex values</span>
      <select aria-label="Complex values" value={r.complex ?? "abs"} onChange={(e) => update({ complex: e.target.value })}>
        <option value="re_im">Re and Im</option>
        {COMPLEX_MODES.filter(([v]) => v !== "iq").map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </label>
  );
}

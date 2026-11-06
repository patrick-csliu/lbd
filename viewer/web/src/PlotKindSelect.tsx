import { useEffect, useState } from "react";
import { api, KindInfo } from "./api";
import { PLOT_KINDS } from "./plotKinds";

/**
 * The Plot type choice of Explore and Figure: the types the server knows, for this file. A type
 * that can't be used is greyed and says why. `onChoose` also gets the values that type can draw.
 */
export function PlotKindSelect({ path, value, first, page, onChoose }: { path: string; value: string; first?: string; page: "explore" | "figure"; onChoose: (kind: string, values: string[] | null) => void }) {
  const [kinds, setKinds] = useState<KindInfo[] | null>(null);
  useEffect(() => {
    let current = true;
    api.kinds(path, first ? { values: [first] } : {}).then(
      (r) => current && setKinds(r.kinds),
      () => current && setKinds(null), // the choice still works: the server says why when asked
    );
    return () => {
      current = false;
    };
  }, [path, first]);
  const known = (name: string) => PLOT_KINDS.find((k) => k.kind === name);
  const order = page === "figure" ? ["curve", "scatter", "heatmap"] : ["curve", "heatmap"];
  const names = [...order, ...(kinds ?? []).map((k) => k.name).filter((n) => !order.includes(n) && known(n) && (page === "figure" || known(n)?.explore))];
  const title = (name: string, k?: KindInfo) => (name === "heatmap" && page === "figure" ? "Heat map" : k?.title ?? { curve: "Curves", heatmap: "Map", scatter: "Scatter" }[name] ?? name);
  return (
    <select aria-label="Plot type" value={value} onChange={(e) => onChoose(e.target.value, kinds?.find((k) => k.name === e.target.value)?.values ?? null)}>
      {names.map((name) => {
        const k = kinds?.find((x) => x.name === name);
        // Figure takes another value when this one doesn't fit; Explore shows what is chosen
        const off = !!k?.why && (page === "explore" || k.values.length === 0);
        return (
          <option key={name} value={name} disabled={off} title={off ? k?.why ?? undefined : undefined}>
            {title(name, k)}
            {off && page === "explore" ? ` (${k?.why})` : ""}
          </option>
        );
      })}
    </select>
  );
}

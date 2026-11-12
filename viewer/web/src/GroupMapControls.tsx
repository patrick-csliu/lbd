import type { KindControlsProps } from "./plotKinds";

const CELLS: [string, string, string][] = [
  ["auto", "Automatic", "Rows where each row has its own points, otherwise the nearest point"],
  ["rows", "Rows", "Each stored point owns a cell, halfway to its neighbours in its row"],
  ["nearest", "Nearest point", "Each pixel shows the nearest stored point"],
  ["smooth", "Smooth", "Shaded between the stored points: these colours are worked out, not stored"],
];

/** A map of a variable sweep: how its stored points become a picture. */
export function GroupMapDisplay({ resolved, update }: KindControlsProps) {
  if (!resolved.levels) return null;
  const cells = String(resolved.options?.cells ?? "auto");
  return (
    <label className="field" title={CELLS.find(([v]) => v === cells)?.[2]}>
      <span>Cells</span>
      <select aria-label="Cells" value={cells} onChange={(e) => update({ options: { ...(resolved.options ?? {}), cells: e.target.value } })}>
        {CELLS.map(([v, text, tip]) => (
          <option key={v} value={v} title={tip}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

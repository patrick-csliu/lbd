import { useEffect, useState } from "react";
import { AxesChoice } from "./AxesChoice";
import type { KindControlsProps, PlotKind } from "./plotKinds";

/** How many bins a histogram can have (as the server's `count_bins`). */
const MOST_BINS = 10000;

function BinsField({ bins, onBins }: { bins: unknown; onBins: (bins: number | "auto") => void }) {
  const [text, setText] = useState(bins === "auto" || bins === undefined ? "" : String(bins));
  useEffect(() => setText(bins === "auto" || bins === undefined ? "" : String(bins)), [bins]);
  const n = Number(text);
  const fine = text.trim() === "" || (Number.isInteger(n) && n >= 2 && n <= MOST_BINS);
  return (
    <label className="field">
      <span>Bins</span>
      <input
        aria-label="Bins"
        inputMode="numeric"
        placeholder="Auto"
        value={text}
        aria-invalid={!fine}
        title={`Empty: chosen from the data. Otherwise a whole number, 2 to ${MOST_BINS}.`}
        onChange={(e) => {
          const t = e.target.value;
          setText(t);
          const v = Number(t);
          if (t.trim() === "") onBins("auto");
          else if (Number.isInteger(v) && v >= 2 && v <= MOST_BINS) onBins(v);
        }}
      />
      {!fine && <span className="small export-warning">A whole number from 2 to {MOST_BINS}, or empty for Auto.</span>}
    </label>
  );
}

/** What a histogram counts (Colour by, and a slider or All per axis) and how it is drawn. */
function HistogramControls({ info, resolved, update, settings, updateSettings, page }: KindControlsProps) {
  const options = resolved.options ?? {};
  const setOption = (patch: Record<string, string | number>) => update({ options: { ...options, ...patch } });
  const values = resolved.values ?? [];
  const first = info.values.find((v) => v.name === values[0]);
  const axes = (first?.axes ?? []).flatMap((name) => {
    const a = info.axes.find((x) => x.name === name);
    return a && !a.group ? [{ name, label: a.label || a.name, length: a.length, elements: a.elements }] : [];
  });
  const color = resolved.color ?? "none";
  const steps = axes.find((a) => a.name === color)?.length ?? 1;
  const several = values.length * steps > 1;
  const log = page === "explore" ? (settings?.yscale ?? resolved.y_scale) === "log" : resolved.y_scale === "log";
  return (
    <>
      {axes.length > 0 && <AxesChoice axes={axes} color={color} all={resolved.all ?? []} onChange={update} />}
      <BinsField bins={options.bins} onBins={(bins) => setOption({ bins })} />
      <label className="field" title={several ? "Several series are always outlines, so that they can be told apart." : undefined}>
        <span>Draw</span>
        <select aria-label="Draw" value={several ? "outline" : String(options.hist_style ?? "bars")} disabled={several} onChange={(e) => setOption({ hist_style: e.target.value })}>
          <option value="bars">Bars</option>
          <option value="outline">Outline</option>
        </select>
      </label>
      <label className="field">
        <span>Vertical axis</span>
        <select aria-label="Vertical axis" value={String(options.hist_y ?? "count")} onChange={(e) => setOption({ hist_y: e.target.value })}>
          <option value="count">Count</option>
          <option value="fraction">Fraction</option>
          <option value="density">Density</option>
        </select>
      </label>
      <label className="check">
        <input
          type="checkbox"
          aria-label="Log"
          checked={log}
          onChange={(e) => {
            const scale = e.target.checked ? "log" : "linear";
            if (page === "explore") updateSettings?.({ yscale: scale });
            else update({ y_scale: scale });
          }}
        />
        Log
      </label>
    </>
  );
}

export const kindRow: PlotKind = {
  kind: "histogram",
  explore: true,
  controls: HistogramControls,
  cursorTypes: ["vertical"],
  strips: null,
  darkInverted: true,
  openInFigure: true,
  cursorMark: "lines",
  axes: "2d",
  syncs: true,
  findButtons: false,
  noAxes: true,
  scales: ["y"],
};

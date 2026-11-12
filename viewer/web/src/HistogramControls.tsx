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

function axesOf(info: KindControlsProps["info"], resolved: KindControlsProps["resolved"]) {
  const first = info.values.find((v) => v.name === resolved.values?.[0]);
  return (first?.axes ?? []).flatMap((name) => {
    const a = info.axes.find((x) => x.name === name);
    return a && !a.group ? [{ name, label: a.label || a.name, length: a.length, elements: a.elements }] : [];
  });
}

/** What a histogram counts: Colour by, and a slider or All per axis (Data). */
function HistogramControls({ info, resolved, update }: KindControlsProps) {
  const axes = axesOf(info, resolved);
  if (!axes.length) return null;
  return <AxesChoice axes={axes} color={resolved.color ?? "none"} all={resolved.all ?? []} onChange={update} />;
}

/** How a histogram is drawn: bins, bars or outlines, what the vertical axis counts (Display,
 * 16.47). Its log scale is Display's Log vertical. */
function HistogramDisplay({ info, resolved, update }: KindControlsProps) {
  const options = resolved.options ?? {};
  const setOption = (patch: Record<string, string | number>) => update({ options: { ...options, ...patch } });
  const values = resolved.values ?? [];
  const color = resolved.color ?? "none";
  const steps = axesOf(info, resolved).find((a) => a.name === color)?.length ?? 1;
  const several = values.length * steps > 1;
  return (
    <>
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
    </>
  );
}

export const kindRow: PlotKind = {
  kind: "histogram",
  explore: true,
  controls: HistogramControls,
  display: HistogramDisplay,
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

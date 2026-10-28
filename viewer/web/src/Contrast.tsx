import { PointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { Histogram } from "./api";

/**
 * The contrast of a map: a histogram of its values (all shown cells, not just the view) with two
 * limit lines. Drag a line to move that limit, drag between them to move both; "Auto" leaves out
 * the outliers (0.5 % at each end), "Full" spans every value, "Style" uses the style's own range.
 * The limits are the colour range of the view settings (plot units, like the From / To boxes).
 */

interface Props {
  /** Counts the map's values with these settings; null while the view isn't open. */
  load: () => Promise<Histogram | null>;
  /** Changes when what is counted changes (the plotted data, chosen rows, colour scale). */
  loadKey: string;
  clim: [number | null, number | null];
  onClim: (c: [number, number] | undefined) => void;
}

const H = 64;

export default function Contrast({ load, loadKey, clim, onClim }: Props) {
  const [hist, setHist] = useState<Histogram | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{ what: "lo" | "hi" | "both"; at: number; lim: [number, number] } | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    let live = true;
    loadRef
      .current()
      .then((h) => {
        if (!live) return;
        setHist(h);
        setError(null);
      })
      .catch((e) => live && setError((e as Error).message));
    return () => {
      live = false;
    };
  }, [loadKey]);

  // positions along the histogram (log colour scale: in decades)
  const f = useCallback((v: number) => (hist?.log ? Math.log10(v) : v), [hist]);
  const fi = useCallback((u: number) => (hist?.log ? 10 ** u : u), [hist]);
  const limits: [number, number] | null = hist ? [clim[0] ?? hist.lowest, clim[1] ?? hist.highest] : null;

  const toPx = useCallback(
    (v: number, w: number) => {
      if (!hist) return 0;
      const a = f(hist.edges[0]), b = f(hist.edges[hist.edges.length - 1]);
      return ((f(v) - a) / (b - a)) * w;
    },
    [hist, f],
  );
  const toVal = useCallback(
    (px: number, w: number) => {
      if (!hist) return 0;
      const a = f(hist.edges[0]), b = f(hist.edges[hist.edges.length - 1]);
      return fi(a + (px / w) * (b - a));
    },
    [hist, f, fi],
  );

  useEffect(() => {
    const c = canvas.current;
    if (!c || !hist || !limits) return;
    const dpr = window.devicePixelRatio || 1, w = c.clientWidth;
    c.width = Math.round(w * dpr);
    c.height = Math.round(H * dpr);
    const ctx = c.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, H);
    const style = getComputedStyle(c);
    // bars on a square-root scale, so small counts (the tails) still show
    const top = Math.sqrt(Math.max(...hist.counts, 1));
    ctx.fillStyle = style.color;
    ctx.globalAlpha = 0.45;
    hist.counts.forEach((n, i) => {
      const x0 = toPx(hist.edges[i], w), x1 = toPx(hist.edges[i + 1], w);
      const bh = (Math.sqrt(n) / top) * (H - 4);
      ctx.fillRect(x0, H - bh, Math.max(x1 - x0 - 0.5, 0.5), bh);
    });
    ctx.globalAlpha = 1;
    const [a, b] = limits.map((v) => toPx(v, w));
    ctx.fillStyle = "rgba(0,114,178,0.12)";
    ctx.fillRect(Math.min(a, b), 0, Math.abs(b - a), H);
    ctx.strokeStyle = "#0072b2";
    ctx.lineWidth = 2;
    for (const x of [a, b]) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, H);
      ctx.stroke();
    }
  }, [hist, limits, toPx]);

  const where = (e: PointerEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return [e.clientX - r.left, r.width] as const;
  };
  const onDown = (e: PointerEvent<HTMLCanvasElement>) => {
    if (!limits) return;
    const [x, w] = where(e);
    const a = toPx(limits[0], w), b = toPx(limits[1], w);
    const what = Math.abs(x - a) <= 6 ? "lo" : Math.abs(x - b) <= 6 ? "hi" : x > Math.min(a, b) && x < Math.max(a, b) ? "both" : null;
    if (!what) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { what, at: x, lim: limits };
  };
  const onMove = (e: PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current;
    if (!d || !hist) return;
    const [x, w] = where(e);
    let [lo, hi] = d.lim;
    if (d.what === "lo") lo = toVal(Math.min(x, toPx(hi, w) - 2), w);
    else if (d.what === "hi") hi = toVal(Math.max(x, toPx(lo, w) + 2), w);
    else {
      const dx = x - d.at;
      lo = toVal(toPx(d.lim[0], w) + dx, w);
      hi = toVal(toPx(d.lim[1], w) + dx, w);
    }
    onClim([lo, hi]);
  };

  if (error) return <div className="field-error">{error}</div>;
  if (!hist) return <div className="muted small">Counting the values…</div>;
  return (
    <div className="contrast">
      <canvas
        ref={canvas}
        className="contrast-hist"
        style={{ height: H }}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={() => (drag.current = null)}
        aria-label="Histogram of the map's values with the colour range: drag the lines or the band between them"
      />
      <div className="row-controls">
        <button onClick={() => onClim(hist.auto)} title="Leave out the outliers: 0.5 % of the cells at each end">
          Auto
        </button>
        <button onClick={() => onClim([hist.lowest, hist.highest])} title="From the lowest to the highest value">
          Full
        </button>
        <button onClick={() => onClim(undefined)} title="The colour range of the style (or of the data)">
          Style
        </button>
      </div>
    </div>
  );
}

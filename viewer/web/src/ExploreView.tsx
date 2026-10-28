import { CSSProperties, PointerEvent as ReactPointerEvent, useCallback, useEffect, useRef, useState } from "react";
import NumberRange from "./NumberRange";
import { api, ApiError, ExploreFrame, ExploreFrameMeta, ExploreOpen, ExplorePick, FileInfo, PlotSpec, ReduceStat, StoredAt } from "./api";

/**
 * The Explore view (preview): a file's plot drawn by the server's matplotlib (explore.py), made
 * interactive here.
 *
 * - The server sends a picture of a view plus the mapping between its pixels and the data.
 * - Zooming and panning move the current picture at once (a stretched preview) and ask for a sharp
 *   one; only the newest view is asked for, so the picture never lags behind a queue.
 * - Picked points, the highlighted trace and the zoom box are drawn here, on a layer over the
 *   picture, from the data positions the server gave.
 * - Values shown come from the full data (the server's pick), never from the picture.
 */

type Lim = [number, number];
/** What part of the data the view shows (its zoom). */
export interface View {
  xlim: Lim;
  ylim: Lim;
}

/** How the data is shown, never what (explore.py `apply`): kept in LBD's database, not the file. */
export interface ViewSettings {
  select?: Record<string, number[]>; // the traces drawn (curves) or making the map; absent: all
  cmap?: string;
  invert?: boolean;
  xscale?: "linear" | "log";
  yscale?: "linear" | "log";
  cscale?: "linear" | "log";
  clim?: [number | null, number | null];
}
interface Size {
  w: number;
  h: number;
}

/** A picture's geometry in CSS pixels: the plot area and the view it shows. */
interface Mapping {
  plot: [number, number, number, number]; // left, top, width, height
  view: View;
  xscale: string;
  yscale: string;
}

const fwd = (scale: string, v: number) => (scale === "log" ? Math.log10(v) : v);
const back = (scale: string, v: number) => (scale === "log" ? 10 ** v : v);

function toPx(m: Mapping, x: number, y: number): [number, number] {
  const [l, t, w, h] = m.plot;
  const x0 = fwd(m.xscale, m.view.xlim[0]), x1 = fwd(m.xscale, m.view.xlim[1]);
  const y0 = fwd(m.yscale, m.view.ylim[0]), y1 = fwd(m.yscale, m.view.ylim[1]);
  return [l + ((fwd(m.xscale, x) - x0) / (x1 - x0)) * w, t + h - ((fwd(m.yscale, y) - y0) / (y1 - y0)) * h];
}

function toData(m: Mapping, px: number, py: number): [number, number] {
  const [l, t, w, h] = m.plot;
  const x0 = fwd(m.xscale, m.view.xlim[0]), x1 = fwd(m.xscale, m.view.xlim[1]);
  const y0 = fwd(m.yscale, m.view.ylim[0]), y1 = fwd(m.yscale, m.view.ylim[1]);
  return [back(m.xscale, x0 + ((px - l) / w) * (x1 - x0)), back(m.yscale, y0 + ((t + h - py) / h) * (y1 - y0))];
}

function frameMapping(meta: ExploreFrameMeta): Mapping {
  const d = meta.dpr;
  return {
    plot: [meta.plot[0] / d, meta.plot[1] / d, meta.plot[2] / d, meta.plot[3] / d],
    view: { xlim: meta.xlim, ylim: meta.ylim },
    xscale: meta.xscale,
    yscale: meta.yscale,
  };
}

/** Zoom a range by `f` (below 1: in) around the point `at`, in the axis' own scale (log or not). */
function zoomRange(lim: Lim, at: number, f: number, scale: string): Lim {
  const a = fwd(scale, lim[0]), b = fwd(scale, lim[1]), u = fwd(scale, at);
  return [back(scale, u - (u - a) * f), back(scale, u + (b - u) * f)];
}

function shiftRange(lim: Lim, by: number, scale: string): Lim {
  return [back(scale, fwd(scale, lim[0]) + by), back(scale, fwd(scale, lim[1]) + by)];
}

const same = (a: View | null, b: View | null) =>
  !!a && !!b && a.xlim[0] === b.xlim[0] && a.xlim[1] === b.xlim[1] && a.ylim[0] === b.ylim[0] && a.ylim[1] === b.ylim[1];

/** A picked point or cell, kept in data units so it follows zooming. */
interface Picked {
  pick: ExplorePick;
  at?: [number, number];
  line?: ([number, number] | null)[];
  rect?: [number, number, number, number]; // x0, y0, x1, y1
}

interface Props {
  info: FileInfo;
  /** What to plot (values, kind, axes, slices, complex mode): changing it redraws in the same session. */
  spec: PlotSpec;
  /** The file's version on disk: a new one reads the file again. */
  version: string | null;
  /** The plot settings as the server resolved them (defaults filled in, slices described). */
  onOpened: (o: ExploreOpen) => void;
  onError: (msg: string) => void;
  /** How the data is shown: chosen traces, colour map, scales, colour range. */
  settings: ViewSettings;
  /** How a pixel shows several map cells. */
  stat: ReduceStat;
  onStat: (s: ReduceStat) => void;
  /** The zoom to start with (remembered), or null: all the data. */
  initialView: View | null;
  /** The view now (each new picture), to be remembered. */
  onView: (v: View) => void;
}

/** Two plot settings that differ only in the slider positions (the view is kept then). */
function onlySlicesDiffer(a: PlotSpec, b: PlotSpec): boolean {
  return JSON.stringify({ ...a, index: undefined }) === JSON.stringify({ ...b, index: undefined });
}

export default function ExploreView({ info, spec, version, onOpened, onError, settings, stat, onStat, initialView, onView }: Props) {
  // Pictures travel as raw pixels (fastest on this computer; "png" is the server's other choice).
  const format = "raw" as const;
  const [size, setSize] = useState<Size | null>(null);
  const sizeRef = useRef(size);
  sizeRef.current = size;
  const [opened, setOpened] = useState<ExploreOpen | null>(null);
  const [status, setStatus] = useState("Opening…");
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<ExploreFrameMeta | null>(null);
  const [timing, setTiming] = useState<string>("");
  const [picked, setPicked] = useState<Picked | null>(null);
  const [mouse, setMouse] = useState<[number, number] | null>(null);

  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;
  const onOpenedRef = useRef(onOpened);
  onOpenedRef.current = onOpened;
  const specRef = useRef(spec);
  specRef.current = spec;
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const onViewRef = useRef(onView);
  onViewRef.current = onView;
  const initialViewRef = useRef(initialView); // used by the first opening only
  const showAll = useRef(false); // the next picture shows all the data (its limits come from the server)
  const host = useRef<HTMLDivElement>(null);
  const picture = useRef<HTMLCanvasElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
  const frameCanvas = useRef<HTMLCanvasElement | null>(null); // the last picture, for previews
  const frame = useRef<ExploreFrame | null>(null);
  const session = useRef<string | null>(null);
  const wanted = useRef<View | null>(null);
  const inflight = useRef(false);
  const dirty = useRef(false); // a picture is needed although the view didn't change
  const reopen = useRef<() => void>(() => {});
  const statRef = useRef(stat);
  statRef.current = stat;
  const formatRef = useRef(format);
  formatRef.current = format;
  const pickedRef = useRef(picked);
  pickedRef.current = picked;
  const box = useRef<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const pan = useRef<{ x: number; y: number; view: View } | null>(null);
  const down = useRef<{ x: number; y: number } | null>(null);

  // The mapping of what is on screen now: the last picture's plot area, showing the wanted view.
  const current = useCallback((): Mapping | null => {
    const f = frame.current;
    if (!f) return null;
    const m = frameMapping(f.meta);
    return wanted.current ? { ...m, view: wanted.current } : m;
  }, []);

  // ---- drawing (picture: the server's picture, moved to the wanted view; overlay: our marks)

  const paintOverlay = useCallback(() => {
    const c = overlay.current, m = current();
    if (!c) return;
    const ctx = c.getContext("2d")!;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, c.width, c.height);
    if (!m) return;
    const [l, t, w, h] = m.plot;
    ctx.save();
    ctx.beginPath();
    ctx.rect(l, t, w, h);
    ctx.clip();
    const p = pickedRef.current;
    if (p?.line) {
      ctx.strokeStyle = "rgba(0,0,0,0.75)";
      ctx.lineWidth = 3;
      ctx.beginPath();
      let pen = false;
      for (const pt of p.line) {
        if (!pt) {
          pen = false;
          continue;
        }
        const [x, y] = toPx(m, pt[0], pt[1]);
        if (pen) ctx.lineTo(x, y);
        else ctx.moveTo(x, y);
        pen = true;
      }
      ctx.stroke();
    }
    ctx.strokeStyle = "#e0001b";
    ctx.lineWidth = 2;
    if (p?.at) {
      const [x, y] = toPx(m, p.at[0], p.at[1]);
      ctx.beginPath();
      ctx.arc(x, y, 7, 0, 2 * Math.PI);
      ctx.stroke();
    }
    if (p?.rect) {
      const [ax, ay] = toPx(m, p.rect[0], p.rect[1]);
      const [bx, by] = toPx(m, p.rect[2], p.rect[3]);
      const rw = Math.max(Math.abs(bx - ax), 6), rh = Math.max(Math.abs(by - ay), 6);
      ctx.strokeRect((ax + bx) / 2 - rw / 2, (ay + by) / 2 - rh / 2, rw, rh);
    }
    ctx.restore();
    const b = box.current;
    if (b) {
      ctx.strokeStyle = "#1f5fbf";
      ctx.fillStyle = "rgba(31,95,191,0.12)";
      ctx.lineWidth = 1;
      const x = Math.min(b.x0, b.x1), y = Math.min(b.y0, b.y1);
      ctx.fillRect(x, y, Math.abs(b.x1 - b.x0), Math.abs(b.y1 - b.y0));
      ctx.strokeRect(x + 0.5, y + 0.5, Math.abs(b.x1 - b.x0), Math.abs(b.y1 - b.y0));
    }
  }, [current]);

  const paint = useCallback(() => {
    const c = picture.current, f = frame.current, src = frameCanvas.current;
    if (!c || !f || !src) return;
    const ctx = c.getContext("2d")!;
    if (c.width !== f.meta.width || c.height !== f.meta.height) {
      c.width = f.meta.width;
      c.height = f.meta.height;
    }
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(src, 0, 0);
    const v = wanted.current;
    if (v && !same(v, { xlim: f.meta.xlim, ylim: f.meta.ylim })) {
      // Preview: the plot area of the last picture, stretched and moved to the wanted view.
      const m = f.meta;
      const [l, t, w, h] = m.plot;
      const a0 = fwd(m.xscale, m.xlim[0]), a1 = fwd(m.xscale, m.xlim[1]);
      const b0 = fwd(m.xscale, v.xlim[0]), b1 = fwd(m.xscale, v.xlim[1]);
      const c0 = fwd(m.yscale, m.ylim[0]), c1 = fwd(m.yscale, m.ylim[1]);
      const d0 = fwd(m.yscale, v.ylim[0]), d1 = fwd(m.yscale, v.ylim[1]);
      const dx = l + ((a0 - b0) / (b1 - b0)) * w, dw = ((a1 - a0) / (b1 - b0)) * w;
      const dy = t + ((d1 - c1) / (d1 - d0)) * h, dh = ((c1 - c0) / (d1 - d0)) * h;
      ctx.save();
      ctx.beginPath();
      ctx.rect(l, t, w, h);
      ctx.clip();
      const bg = src.getContext("2d")!.getImageData(Math.max(l - 2, 0), Math.max(t - 2, 0), 1, 1).data;
      ctx.fillStyle = `rgb(${bg[0]},${bg[1]},${bg[2]})`;
      ctx.fillRect(l, t, w, h);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(src, l, t, w, h, dx, dy, dw, dh);
      ctx.restore();
    }
    paintOverlay();
  }, [paintOverlay]);

  // ---- asking for pictures: one at a time, always the newest view

  const request = useCallback(() => {
    const sid = session.current, v = wanted.current, sz = sizeRef.current;
    if (inflight.current || !sid || (!v && !showAll.current)) return;
    inflight.current = true;
    dirty.current = false;
    const all = showAll.current;
    const sizeNow = sz ? { width: sz.w, height: sz.h, dpr: window.devicePixelRatio || 1 } : {};
    const view = all || !v ? { xlim: null, ylim: null } : { xlim: v.xlim, ylim: v.ylim };
    api
      .exploreRender(sid, { ...view, stat: statRef.current, format: formatRef.current, settings: settingsRef.current, ...sizeNow })
      .then((f) => {
        if (session.current !== sid) return;
        frame.current = f;
        if (all && showAll.current) {
          // all the data was asked for: the server said where that is
          showAll.current = false;
          wanted.current = { xlim: f.meta.xlim, ylim: f.meta.ylim };
        }
        onViewRef.current({ xlim: f.meta.xlim, ylim: f.meta.ylim });
        if (f.meta.notes?.length) onErrorRef.current(f.meta.notes.join(" "));
        let src = frameCanvas.current;
        if (!src) src = frameCanvas.current = document.createElement("canvas");
        src.width = f.meta.width;
        src.height = f.meta.height;
        const sctx = src.getContext("2d")!;
        if (f.image instanceof ImageData) sctx.putImageData(f.image, 0, 0);
        else sctx.drawImage(f.image, 0, 0);
        paint();
        setMeta(f.meta);
        setError(null);
        setStatus("");
        const ms = f.meta.ms;
        setTiming(
          `reduce ${ms.reduce} ms · draw ${ms.draw} ms · encode ${ms.encode} ms · waited ${ms.wait} ms · ` +
            `asked → shown ${Math.round(f.roundTripMs)} ms · ${f.meta.width}×${f.meta.height} px`,
        );
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404 && session.current === sid) {
          reopen.current();
          return;
        }
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        inflight.current = false;
        const f = frame.current, sz = sizeRef.current;
        const stale =
          f && (!same(wanted.current, { xlim: f.meta.xlim, ylim: f.meta.ylim }) || (sz && Math.abs(f.meta.width / f.meta.dpr - sz.w) > 1));
        if (session.current === sid && (wanted.current || showAll.current) && (stale || dirty.current || showAll.current)) request();
      });
  }, [paint]);

  /** Show this view, or all the data (null). */
  const setView = useCallback(
    (v: View | null) => {
      const full = frame.current?.meta.full;
      wanted.current = v ?? (full ? { xlim: full[0], ylim: full[1] } : null);
      paint();
      request();
    },
    [paint, request],
  );

  // ---- the session: opened for this file, plot settings and panel size; closed when they change

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let timer = 0;
    // The size now, and again (settled for a moment) whenever the panel is resized; the server
    // then draws the same view at the new size.
    const measure = () =>
      setSize((old) => {
        const w = el.clientWidth, h = el.clientHeight;
        return old && old.w === w && old.h === h ? old : { w, h };
      });
    // Measured once the layout has settled, so the first session is opened for the final size.
    const later = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(measure, 250);
    };
    later();
    const ro = new ResizeObserver(later);
    ro.observe(el);
    return () => {
      ro.disconnect();
      window.clearTimeout(timer);
    };
  }, []);

  const specKey = JSON.stringify(spec);
  const openedSpecKey = useRef<string | null>(null); // the plot settings the session shows
  const haveSize = !!size && size.w >= 50 && size.h >= 50;
  useEffect(() => {
    const size = sizeRef.current;
    if (!haveSize || !size) return;
    let cancelled = false;
    let sid: string | null = null;
    // A new version of the file: keep the zoom, or, if all the data was shown, show all of the new data.
    const f = frame.current;
    const wasAll = !!f && !!wanted.current && same(wanted.current, { xlim: f.meta.full[0], ylim: f.meta.full[1] });
    const keepView = wasAll ? null : wanted.current ?? initialViewRef.current;
    initialViewRef.current = null;
    const open = () => {
      setStatus("Opening… (large files take a moment: the data is read and prepared once)");
      const s = specRef.current;
      openedSpecKey.current = JSON.stringify(s);
      api
        .exploreOpen(info.path, s, size.w, size.h, window.devicePixelRatio || 1)
        .then((o) => {
          if (cancelled) {
            api.exploreClose(o.session).catch(() => {});
            return;
          }
          sid = o.session;
          session.current = o.session;
          setOpened(o);
          onOpenedRef.current(o);
          if (o.warnings.length) onErrorRef.current(o.warnings.join(" "));
          // the zoom to keep, else all the data as the server finds it (with the view settings applied)
          wanted.current = keepView;
          showAll.current = !keepView;
          request();
        })
        .catch((e) => {
          if (!cancelled) {
            setError(e instanceof Error ? e.message : String(e));
            setStatus("");
          }
        });
    };
    reopen.current = open;
    open();
    return () => {
      cancelled = true;
      session.current = null;
      frame.current = null;
      if (sid) api.exploreClose(sid).catch(() => {});
    };
    // The view (zoom) is kept when the file is read again (a new version on disk).
  }, [info.path, version, haveSize, request]);

  // Other plot settings: the same session draws them. Moving a slider keeps the zoom; anything
  // else (another value, kind, axis, complex mode) starts from the whole data.
  useEffect(() => {
    const sid = session.current;
    if (!sid || openedSpecKey.current === specKey) return;
    const before = JSON.parse(openedSpecKey.current ?? "{}") as PlotSpec;
    openedSpecKey.current = specKey;
    setStatus("Drawing…");
    api
      .exploreSpec(sid, specRef.current)
      .then((o) => {
        if (session.current !== sid) return;
        setOpened(o);
        onOpenedRef.current(o);
        if (o.warnings.length) onErrorRef.current(o.warnings.join(" "));
        setPicked(null);
        const keep = onlySlicesDiffer(before, specRef.current) && wanted.current;
        wanted.current = keep || { xlim: o.full[0], ylim: o.full[1] };
        dirty.current = true; // the last picture shows the old settings, even where the view is the same
        request();
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : String(e));
        setStatus("");
      });
  }, [specKey, request]);

  // Other view settings (chosen traces, colours, scales): the same session draws them. A new
  // x or y scale shows all the data (the old limits may not exist on a log axis).
  const settingsKey = JSON.stringify(settings);
  const shownSettings = useRef(settingsKey);
  useEffect(() => {
    if (shownSettings.current === settingsKey) return;
    const before = JSON.parse(shownSettings.current) as ViewSettings;
    shownSettings.current = settingsKey;
    if ((before.xscale ?? "linear") !== (settings.xscale ?? "linear") || (before.yscale ?? "linear") !== (settings.yscale ?? "linear"))
      showAll.current = true;
    dirty.current = true;
    if (session.current) request();
  }, [settingsKey, settings, request]);

  // A new panel size: the same view, drawn for it.
  useEffect(() => {
    if (session.current) request();
  }, [size, request]);

  // A new reduction or picture format: the same view again.
  useEffect(() => {
    dirty.current = true;
    if (session.current) request();
  }, [stat, format, request]);

  // ---- mouse

  const cssPoint = (e: { clientX: number; clientY: number }): [number, number] => {
    const r = overlay.current!.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };

  useEffect(() => {
    const c = overlay.current;
    if (!c) return;
    const onWheel = (e: WheelEvent) => {
      const m = current();
      if (!m || !wanted.current) return;
      e.preventDefault();
      const [px, py] = cssPoint(e);
      const [x, y] = toData(m, px, py);
      const f = Math.exp(e.deltaY * 0.0015);
      const v = wanted.current;
      setView({
        xlim: e.altKey ? v.xlim : zoomRange(v.xlim, x, f, m.xscale),
        ylim: e.shiftKey ? v.ylim : zoomRange(v.ylim, y, f, m.yscale),
      });
    };
    c.addEventListener("wheel", onWheel, { passive: false });
    return () => c.removeEventListener("wheel", onWheel);
  }, [current, setView]);

  const onPointerDown = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const [x, y] = cssPoint(e);
    (e.target as HTMLCanvasElement).setPointerCapture(e.pointerId);
    if (e.button === 0) {
      down.current = { x, y };
      box.current = { x0: x, y0: y, x1: x, y1: y };
    } else if ((e.button === 1 || e.button === 2) && wanted.current) {
      e.preventDefault();
      pan.current = { x, y, view: wanted.current };
    }
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const [x, y] = cssPoint(e);
    const m = current();
    if (m) setMouse(toData(m, x, y));
    if (box.current) {
      box.current = { ...box.current, x1: x, y1: y };
      paintOverlay();
    } else if (pan.current && m) {
      const p = pan.current, [, , w, h] = m.plot;
      const vx = fwd(m.xscale, p.view.xlim[1]) - fwd(m.xscale, p.view.xlim[0]);
      const vy = fwd(m.yscale, p.view.ylim[1]) - fwd(m.yscale, p.view.ylim[0]);
      setView({
        xlim: shiftRange(p.view.xlim, (-(x - p.x) / w) * vx, m.xscale),
        ylim: shiftRange(p.view.ylim, ((y - p.y) / h) * vy, m.yscale),
      });
    }
  };

  const doPick = (x: number, y: number) => {
    const sid = session.current, f = frame.current, m = current();
    if (!sid || !f || !m) return;
    // The server picks in its last picture's pixels: go there through the data.
    const fm = frameMapping(f.meta);
    const [dx, dy] = toData(m, x, y);
    const [fx, fy] = toPx(fm, dx, dy);
    api
      .explorePick(sid, fx * f.meta.dpr, fy * f.meta.dpr)
      .then(({ pick }) => {
        if (!pick) {
          setPicked(null);
          paintOverlay();
          return;
        }
        const d = f.meta.dpr;
        const fromFrame = (p: [number, number]) => toData(fm, p[0] / d, p[1] / d);
        const r = pick.rect;
        setPicked({
          pick,
          at: pick.at ? fromFrame(pick.at) : undefined,
          line: pick.line?.map((p) => (p ? fromFrame(p) : null)),
          rect: r ? [...fromFrame([r[0], r[1] + r[3]]), ...fromFrame([r[0] + r[2], r[1]])] : undefined,
        });
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  };

  const onPointerUp = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const [x, y] = cssPoint(e);
    const b = box.current, d = down.current, m = current();
    box.current = null;
    down.current = null;
    pan.current = null;
    if (b && d && m && wanted.current) {
      const wx = Math.abs(x - d.x), wy = Math.abs(y - d.y);
      if (wx < 4 && wy < 4) {
        paintOverlay();
        doPick(x, y);
        return;
      }
      const [ax, ay] = toData(m, Math.min(d.x, x), Math.max(d.y, y));
      const [bx, by] = toData(m, Math.max(d.x, x), Math.min(d.y, y));
      const v = wanted.current;
      // A flat box zooms one axis only.
      setView({ xlim: wx >= 4 ? [ax, bx] : v.xlim, ylim: wy >= 4 ? [ay, by] : v.ylim });
    }
    paintOverlay();
  };

  useEffect(() => paintOverlay(), [picked, paintOverlay]);

  // ---- layout

  const cssSize: CSSProperties = meta ? { width: meta.width / meta.dpr, height: meta.height / meta.dpr } : {};

  return (
    <div className="explore">
      <div className="explore-toolbar">
        {opened?.kind === "heatmap" && (
          <label title="When a screen pixel stands for several cells, what it shows">
            Several cells per pixel{" "}
            <select value={stat} onChange={(e) => onStat(e.target.value as ReduceStat)}>
              <option value="max">max (peaks stay)</option>
              <option value="min">min (dips stay)</option>
              <option value="mean">mean</option>
            </select>
          </label>
        )}
        <button onClick={() => setView(null)} title="Show all the data (or double-click the plot)">
          Reset view
        </button>
        <span className="spacer" />
        {meta && (
          <span className={"explore-note" + (meta.reduced ? " reduced" : "")} title="How the data fits the screen's pixels">
            {meta.note}
          </span>
        )}
      </div>
      {meta && (
        <div className="explore-limits">
          <NumberRange
            label="Horizontal"
            value={meta.xlim}
            log={meta.xscale === "log"}
            onChange={(v) => setView({ xlim: [v[0] ?? meta.full[0][0], v[1] ?? meta.full[0][1]], ylim: wanted.current?.ylim ?? meta.ylim })}
          />
          <NumberRange
            label="Vertical"
            value={meta.ylim}
            log={meta.yscale === "log"}
            onChange={(v) => setView({ xlim: wanted.current?.xlim ?? meta.xlim, ylim: [v[0] ?? meta.full[1][0], v[1] ?? meta.full[1][1]] })}
          />
        </div>
      )}
      {error && <div className="error-box">{error}</div>}
      <div className="explore-host" ref={host}>
        {status && <div className="explore-status muted">{status}</div>}
        <canvas ref={picture} className="explore-picture" style={cssSize} />
        <canvas
          ref={overlay}
          className="explore-overlay"
          width={meta ? Math.round((meta.width / meta.dpr) * (window.devicePixelRatio || 1)) : 0}
          height={meta ? Math.round((meta.height / meta.dpr) * (window.devicePixelRatio || 1)) : 0}
          style={cssSize}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={() => setMouse(null)}
          onDoubleClick={() => setView(null)}
          onContextMenu={(e) => e.preventDefault()}
        />
      </div>
      <div className="explore-readout">
        <div className="muted small">
          Wheel: zoom (Shift: x only, Alt: y only) · drag: zoom to a box · right or middle drag: pan · click: read a point ·
          double-click: everything
          {mouse && (
            <>
              {" "}
              · mouse at x = {fmt(mouse[0])}, y = {fmt(mouse[1])}
            </>
          )}
        </div>
        {picked ? <PickText p={picked.pick} /> : <div className="muted small">Click a point or cell to read its stored value.</div>}
        {timing && <div className="muted small mono">{timing}</div>}
      </div>
    </div>
  );
}

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return Number(v.toPrecision(7)).toString();
}

function stored(s: StoredAt): string {
  return `${s.label || s.axis} = ${fmt(s.value)}${s.unit ? " " + s.unit : ""}`;
}

/** The picked point or cell, as stored in the file. */
function PickText({ p }: { p: ExplorePick }) {
  if (p.kind === "cell") {
    return (
      <div className="explore-pick">
        <strong>
          {fmt(p.value ?? null)}
          {p.value_unit ? " " + p.value_unit : ""}
        </strong>{" "}
        at {stored(p.x)}, {stored(p.y as StoredAt)}{" "}
        <span className="muted small">
          (cell {Object.entries(p.index)
            .map(([a, i]) => `${a}[${i}]`)
            .join(", ")})
        </span>
      </div>
    );
  }
  return (
    <div className="explore-pick">
      <strong>
        {p.label}: {fmt(typeof p.y === "number" ? p.y : null)}
        {p.y_unit ? " " + p.y_unit : ""}
      </strong>{" "}
      at {stored(p.x)}
      {p.series && <>, {stored(p.series)}</>}{" "}
      <span className="muted small">
        ({p.value_name}
        {Object.entries(p.index)
          .map(([a, i]) => ` ${a}[${i}]`)
          .join(",")}
        , as plotted)
      </span>
    </div>
  );
}

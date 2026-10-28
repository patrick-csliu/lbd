import {
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  MutableRefObject,
  PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import NumberRange from "./NumberRange";
import {
  api,
  ApiError,
  CursorAsk,
  CursorRead,
  CursorsAnswer,
  Cut,
  ExploreFrame,
  ExploreFrameMeta,
  ExploreOpen,
  FileInfo,
  Histogram,
  Op,
  OpsInfo,
  PlotSpec,
  ReduceStat,
} from "./api";
import { between, CursorsState, HELP, item, readText, si } from "./cursors";
import { ConfirmDialog, ConfirmRequest, ContextMenu, MenuAt, MenuEntry } from "./menu";

/**
 * The Explore view (preview): a file's plot drawn by the server's matplotlib (explore.py), made
 * interactive here.
 *
 * - The server sends a picture of a view plus the mapping between its pixels and the data.
 * - Zooming and panning move the current picture at once (a stretched preview) and ask for a sharp
 *   one; only the newest view is asked for, so the picture never lags behind a queue.
 * - Cursors, the highlighted trace and the zoom box are drawn here, on a layer over the picture,
 *   from the data positions the server gave.
 * - Cursors sit on the stored data: the server snaps them and reads them out (reading.py), never
 *   the picture. One answer holds the positions, the numbers and (maps) the cuts through cursor
 *   1, and they are drawn together, so the cursor, its numbers and the cuts never disagree. A new
 *   picture with cuts is shown together with the cuts for its view.
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
  ops?: Op[]; // operations on the data shown (operations.py), in order
  ops_on?: boolean; // false: all of them off (the list kept)
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
  /** The cursors to show (remembered, or set in the Cursors section); snapped ones come back by onCursors. */
  cursors: CursorsState;
  onCursors: (c: CursorsState) => void;
  /** The cursors' read-outs, for the Cursors section. */
  onReading: (a: CursorsAnswer | null) => void;
  /** Filled in here: what the Cursors section and the menu can ask for. */
  actions: MutableRefObject<ExploreActions | null>;
  /** Move the first slider by one step (keys [ and ]). */
  onStepSlider: (by: number) => void;
  /** Show a map's row or column (through cursor 1) as a curve in this tab. */
  onShowCut: (which: "row" | "column", index: Record<string, number>) => void;
  /** The operations' state with each picture (which applied, what the plot shows). */
  onOpsInfo: (info: OpsInfo | null) => void;
}

/** What the Cursors section (and the menu) can ask the view to do. */
export interface ExploreActions {
  find: (what: "max" | "min" | "peak") => void;
  saveCut: (which: "row" | "column" | "trace") => void;
  showCut: (which: "row" | "column") => void;
  /** Cursor i to a typed stored value along x or y (snapped to the data). */
  typed: (i: number, axis: "x" | "y", stored: number) => void;
  remove: () => void;
  /** A map's values counted with these view settings (the contrast control). */
  histogram: (settings: ViewSettings) => Promise<Histogram | null>;
  /** Operation `index`'s delay (s) or rotation (°), from the data between the cursors (else in
   *  view), on cursor 1's trace (else all shown). */
  calculate: (what: "delay" | "rotation", index: number) => Promise<number>;
}

const CURSOR_COLORS = ["#e0001b", "#0057d9"];
const GRAB_PX = 7; // how near a cursor the mouse must be to drag it
const CUT_PX = 96; // the cuts' strips: height above the map, width beside it

const askOf = (c: CursorRead): CursorAsk => ({ x: c.x, y: c.y, ...(c.trace !== undefined ? { trace: c.trace } : {}), ...(c.free ? { free: true } : {}) });
const cursorsKey = (type: string, at: CursorAsk[], cuts: boolean, on: boolean) =>
  JSON.stringify({ type, cuts, on, at: at.map((a) => [a.x, a.y, a.trace ?? null, !!a.free]) });

/** Two plot settings that differ only in the slider positions (the view is kept then). */
function onlySlicesDiffer(a: PlotSpec, b: PlotSpec): boolean {
  return JSON.stringify({ ...a, index: undefined }) === JSON.stringify({ ...b, index: undefined });
}

export default function ExploreView({
  info,
  spec,
  version,
  onOpened,
  onError,
  settings,
  stat,
  onStat,
  initialView,
  onView,
  cursors,
  onCursors,
  onReading,
  actions,
  onStepSlider,
  onShowCut,
  onOpsInfo,
}: Props) {
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
  const [reading, setReading] = useState<CursorsAnswer | null>(null);
  const [mouse, setMouse] = useState<[number, number] | null>(null);
  const [help, setHelp] = useState(false);
  const [menu, setMenu] = useState<MenuAt | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [cutHover, setCutHover] = useState<string | null>(null);

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
  const cursorsRef = useRef(cursors);
  cursorsRef.current = cursors;
  const onCursorsRef = useRef(onCursors);
  onCursorsRef.current = onCursors;
  const onReadingRef = useRef(onReading);
  onReadingRef.current = onReading;
  const onOpsInfoRef = useRef(onOpsInfo);
  onOpsInfoRef.current = onOpsInfo;
  const kindRef = useRef<"curve" | "heatmap" | null>(null);
  kindRef.current = opened?.kind ?? null;
  const readingRef = useRef<CursorsAnswer | null>(null); // the cursors on screen: the last answer
  const answered = useRef(""); // cursorsKey of the last answer: an echo of it asks nothing
  const cursorBusy = useRef(false);
  const cursorNext = useRef<CursorAsk[] | null>(null);
  const drag = useRef<number | null>(null); // the cursor being dragged
  const topCut = useRef<HTMLCanvasElement>(null);
  const rightCut = useRef<HTMLCanvasElement>(null);
  const box = useRef<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const pan = useRef<{ x: number; y: number; view: View } | null>(null);
  const down = useRef<{ x: number; y: number } | null>(null);

  // The mapping of what is on screen: the last picture, whose axes and data always belong
  // together (pictures are shown whole, never stretched ahead of the server).
  const current = useCallback((): Mapping | null => {
    const f = frame.current;
    return f ? frameMapping(f.meta) : null;
  }, []);
  // While the user zooms or pans, pictures are drafts (data at half resolution: faster); the
  // sharp picture is asked for once the mouse rests.
  const moving = useRef(false);
  const restTimer = useRef(0);

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
    const r = readingRef.current;
    const [cl, ct] = [l, t];
    r?.cursors.forEach((c, i) => {
      if (!c?.line) return;
      ctx.strokeStyle = i === 0 ? "rgba(0,0,0,0.7)" : "rgba(0,40,120,0.55)";
      ctx.lineWidth = 3;
      ctx.beginPath();
      let pen = false;
      for (const pt of c.line) {
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
    });
    const both = r && r.cursors.length === 2 && r.cursors[0] && r.cursors[1] ? [r.cursors[0], r.cursors[1]] : null;
    if (both) {
      // the range between the two cursors
      const [ax, ay] = toPx(m, both[0].x, both[0].y);
      const [bx, by] = toPx(m, both[1].x, both[1].y);
      ctx.fillStyle = "rgba(0,87,217,0.10)";
      if (r!.type === "vertical") ctx.fillRect(Math.min(ax, bx), ct, Math.abs(bx - ax), h);
      else if (r!.type === "horizontal") ctx.fillRect(cl, Math.min(ay, by), w, Math.abs(by - ay));
      else ctx.fillRect(Math.min(ax, bx), Math.min(ay, by), Math.abs(bx - ax), Math.abs(by - ay));
    }
    r?.cursors.forEach((c, i) => {
      if (!c) return;
      const [x, y] = toPx(m, c.x, c.y);
      const color = CURSOR_COLORS[i];
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      const active = cursorsRef.current.active === i && r.cursors.length === 2;
      ctx.lineWidth = active ? 2 : 1.25;
      ctx.setLineDash(r.type === "cross" ? [5, 4] : []);
      ctx.beginPath();
      if (r.type !== "horizontal") {
        ctx.moveTo(x, ct);
        ctx.lineTo(x, ct + h);
      }
      if (r.type !== "vertical") {
        ctx.moveTo(cl, y);
        ctx.lineTo(cl + w, y);
      }
      ctx.stroke();
      ctx.setLineDash([]);
      if (c.cell && r.type === "cross") {
        const [ax, ay] = toPx(m, c.cell[0], c.cell[1]);
        const [bx, by] = toPx(m, c.cell[2], c.cell[3]);
        if (Math.abs(bx - ax) > 8 && Math.abs(by - ay) > 8) ctx.strokeRect(Math.min(ax, bx), Math.min(ay, by), Math.abs(bx - ax), Math.abs(by - ay));
      }
      if (r.type !== "horizontal" || kindRef.current === "heatmap") {
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(x, y, 6, 0, 2 * Math.PI);
        ctx.stroke();
      }
      ctx.font = "bold 11px system-ui, sans-serif";
      ctx.fillText(String(i + 1), x + 8, y - 8);
    });
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
    paintCuts(topCut.current, rightCut.current, m, readingRef.current);
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
      .exploreRender(sid, {
        ...view,
        stat: statRef.current,
        format: formatRef.current,
        settings: settingsRef.current,
        draft: moving.current,
        ...sizeNow,
      })
      .then(async (f) => {
        if (session.current !== sid) return;
        const at = cursorsRef.current.at;
        if (at.length && cursorsRef.current.on) {
          // the cursors for this picture's view: shown together with it (cuts follow the view)
          await askCursors(at, frameMapping(f.meta)).catch(() => undefined);
          if (session.current !== sid) return;
        }
        frame.current = f;
        if (all && showAll.current) {
          // all the data was asked for: the server said where that is
          showAll.current = false;
          wanted.current = { xlim: f.meta.xlim, ylim: f.meta.ylim };
        }
        onViewRef.current({ xlim: f.meta.xlim, ylim: f.meta.ylim });
        onOpsInfoRef.current(f.meta.ops ?? null);
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
          `server ${ms.total ?? "?"} ms (reduce ${ms.reduce} · draw ${ms.draw} · encode ${ms.encode} · waited ${ms.wait}) · ` +
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
          f &&
          (!same(wanted.current, { xlim: f.meta.xlim, ylim: f.meta.ylim }) ||
            (sz && Math.abs(f.meta.width / f.meta.dpr - sz.w) > 1) ||
            (f.meta.draft && !moving.current)); // a draft, and the mouse rests: the sharp picture
        if (session.current === sid && (wanted.current || showAll.current) && (stale || dirty.current || showAll.current)) request();
      });
  }, [paint]);

  // ---- cursors: asked for, snapped by the server, drawn when the answer is here

  /** Ask for these cursor positions as seen in view `m`; the answer is what is drawn. */
  const askCursors = useCallback((at: CursorAsk[], m: Mapping): Promise<void> => {
    const sid = session.current, st = cursorsRef.current;
    if (!sid || !at.length) return Promise.resolve();
    const cuts = st.cuts && kindRef.current === "heatmap";
    return api
      .exploreCursors(sid, { cursors: at, type: st.type, xlim: m.view.xlim, ylim: m.view.ylim, width: m.plot[2], height: m.plot[3], cuts })
      .then((a) => {
        if (session.current !== sid) return;
        readingRef.current = a;
        setReading(a);
        onReadingRef.current(a);
        const snapped = a.cursors.filter((c): c is CursorRead => !!c).map(askOf);
        answered.current = cursorsKey(st.type, snapped, st.cuts, st.on);
        if (cursorsKey(st.type, at, st.cuts, st.on) !== answered.current || st.at.length !== snapped.length)
          onCursorsRef.current({ ...cursorsRef.current, at: snapped, active: Math.min(cursorsRef.current.active, Math.max(snapped.length - 1, 0)) as 0 | 1 });
      });
  }, []);

  /** Move the cursors (newest wins: while one answer is on its way, only the latest wish waits). */
  const moveCursors = useCallback(
    (at: CursorAsk[]) => {
      cursorNext.current = at;
      const pump = () => {
        const m = current();
        if (cursorBusy.current || !cursorNext.current || !m) return;
        const next = cursorNext.current;
        cursorNext.current = null;
        cursorBusy.current = true;
        askCursors(next, m)
          .then(() => paintOverlay())
          .catch((e) => setError(e instanceof Error ? e.message : String(e)))
          .finally(() => {
            cursorBusy.current = false;
            pump();
          });
      };
      pump();
    },
    [askCursors, current, paintOverlay],
  );

  const clearCursors = useCallback(() => {
    cursorNext.current = null;
    readingRef.current = null;
    answered.current = cursorsKey(cursorsRef.current.type, [], cursorsRef.current.cuts, cursorsRef.current.on);
    setReading(null);
    onReadingRef.current(null);
    onCursorsRef.current({ ...cursorsRef.current, at: [], active: 0 });
    paintOverlay();
  }, [paintOverlay]);

  // A view that ends (another plot, back to the map) takes its read-outs with it.
  useEffect(() => () => onReadingRef.current(null), []);

  // Cursors set elsewhere (remembered, typed, another type, cuts or cursors on or off): ask for
  // them. Off: hidden, but kept, so they come back as they were.
  const cursorsNow = cursorsKey(cursors.type, cursors.at, cursors.cuts, cursors.on);
  const haveFrame = !!meta;
  useEffect(() => {
    if (!haveFrame || cursorsNow === answered.current) return;
    const st = cursorsRef.current;
    if (!st.on) {
      cursorNext.current = null;
      readingRef.current = null;
      answered.current = cursorsNow;
      setReading(null);
      onReadingRef.current(null);
      paintOverlay();
      return;
    }
    if (!st.at.length) {
      if (readingRef.current) clearCursors();
      return;
    }
    moveCursors(cursorsRef.current.at);
  }, [cursorsNow, haveFrame, moveCursors, clearCursors, paintOverlay]);

  /** The user is zooming or panning: drafts until the mouse rests for a moment. */
  const markMoving = useCallback(() => {
    moving.current = true;
    window.clearTimeout(restTimer.current);
    restTimer.current = window.setTimeout(() => {
      moving.current = false;
      dirty.current = true;
      request();
    }, 150);
  }, [request]);
  useEffect(() => () => window.clearTimeout(restTimer.current), []);

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
      markMoving();
      setView({
        xlim: e.altKey ? v.xlim : zoomRange(v.xlim, x, f, m.xscale),
        ylim: e.shiftKey ? v.ylim : zoomRange(v.ylim, y, f, m.yscale),
      });
    };
    c.addEventListener("wheel", onWheel, { passive: false });
    return () => c.removeEventListener("wheel", onWheel);
  }, [current, setView, markMoving]);

  /** The cursor (index) under the mouse, if any: its mark, or its line for vertical / horizontal. */
  const cursorAt = (x: number, y: number): number | null => {
    const r = readingRef.current, m = current();
    if (!r || !m) return null;
    let best: number | null = null, bestD = GRAB_PX;
    r.cursors.forEach((c, i) => {
      if (!c) return;
      const [cx, cy] = toPx(m, c.x, c.y);
      const d = r.type === "vertical" ? Math.abs(x - cx) : r.type === "horizontal" ? Math.abs(y - cy) : Math.hypot(x - cx, y - cy);
      if (d <= bestD) [best, bestD] = [i, d];
    });
    return best;
  };

  /** Cursor i to the mouse position (snapped by the server; Alt: free). Cursor 2 needs cursor 1. */
  const placeCursor = (i: number, x: number, y: number, free: boolean, keepTrace: boolean) => {
    const m = current();
    if (!m || !cursorsRef.current.on) return; // cursors off: a click does nothing
    const [dx, dy] = toData(m, x, y);
    const r = readingRef.current;
    const now = (r?.cursors ?? []).filter((c): c is CursorRead => !!c).map(askOf);
    const wish: CursorAsk = { x: dx, y: dy, ...(free ? { free: true } : {}) };
    if (keepTrace && now[i]?.trace !== undefined) wish.trace = now[i].trace;
    const at = now.length ? [...now] : [];
    if (i === 1 && !at.length) i = 0;
    at[i] = wish;
    if (i === 1) onCursorsRef.current({ ...cursorsRef.current, active: 1 });
    else if (at.length < 2) onCursorsRef.current({ ...cursorsRef.current, active: 0 });
    moveCursors(at.slice(0, 2));
  };

  const onPointerDown = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const [x, y] = cssPoint(e);
    (e.target as HTMLCanvasElement).setPointerCapture(e.pointerId);
    (e.target as HTMLCanvasElement).focus({ preventScroll: true });
    setMenu(null);
    if (e.button === 0) {
      const hit = cursorAt(x, y);
      if (hit !== null && !e.shiftKey) {
        drag.current = hit;
        onCursorsRef.current({ ...cursorsRef.current, active: hit as 0 | 1 });
        return;
      }
      down.current = { x, y };
      box.current = { x0: x, y0: y, x1: x, y1: y };
    } else if ((e.button === 1 || e.button === 2) && wanted.current) {
      e.preventDefault();
      down.current = { x, y };
      pan.current = { x, y, view: wanted.current };
    }
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const [x, y] = cssPoint(e);
    const m = current();
    if (m) setMouse(toData(m, x, y));
    if (drag.current !== null) {
      placeCursor(drag.current, x, y, e.altKey, !e.altKey);
      return;
    }
    if (!box.current && !pan.current) {
      (e.target as HTMLCanvasElement).style.cursor = cursorAt(x, y) !== null ? (readingRef.current?.type === "vertical" ? "ew-resize" : readingRef.current?.type === "horizontal" ? "ns-resize" : "move") : "crosshair";
    }
    if (box.current) {
      box.current = { ...box.current, x1: x, y1: y };
      paintOverlay();
    } else if (pan.current && m) {
      const p = pan.current, [, , w, h] = m.plot;
      const vx = fwd(m.xscale, p.view.xlim[1]) - fwd(m.xscale, p.view.xlim[0]);
      const vy = fwd(m.yscale, p.view.ylim[1]) - fwd(m.yscale, p.view.ylim[0]);
      if (Math.abs(x - p.x) < 3 && Math.abs(y - p.y) < 3) return; // not a pan yet (a right-click?)
      markMoving();
      setView({
        xlim: shiftRange(p.view.xlim, (-(x - p.x) / w) * vx, m.xscale),
        ylim: shiftRange(p.view.ylim, ((y - p.y) / h) * vy, m.yscale),
      });
    }
  };

  const onPointerUp = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const [x, y] = cssPoint(e);
    const b = box.current, d = down.current, m = current(), p = pan.current;
    box.current = null;
    down.current = null;
    pan.current = null;
    if (drag.current !== null) {
      drag.current = null;
      return;
    }
    if (p && d && Math.abs(x - d.x) < 3 && Math.abs(y - d.y) < 3 && e.button === 2) {
      openMenu(e.clientX, e.clientY, x, y);
      return;
    }
    if (b && d && m && wanted.current) {
      const wx = Math.abs(x - d.x), wy = Math.abs(y - d.y);
      if (wx < 4 && wy < 4) {
        paintOverlay();
        placeCursor(e.shiftKey ? 1 : 0, x, y, e.altKey, false);
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

  // ---- what the Cursors section, the menu and the keys ask for

  const find = useCallback(
    (what: "max" | "min" | "peak") => {
      const sid = session.current, m = current(), r = readingRef.current;
      if (!sid || !m) return;
      const [c1, c2] = r?.cursors ?? [];
      let xlim = m.view.xlim as number[], ylim = m.view.ylim as number[];
      if (c1 && c2) {
        // between the cursors: their x range (curves), the rectangle between them (maps)
        xlim = [Math.min(c1.x, c2.x), Math.max(c1.x, c2.x)];
        if (kindRef.current === "heatmap") ylim = [Math.min(c1.y, c2.y), Math.max(c1.y, c2.y)];
      }
      api
        .exploreFind(sid, what, xlim, ylim, kindRef.current === "curve" ? c1?.trace : undefined)
        .then((p) => {
          const rest = (r?.cursors ?? []).slice(1).filter((c): c is CursorRead => !!c).map(askOf);
          moveCursors([{ x: p.x, y: p.y, ...(p.trace !== undefined ? { trace: p.trace } : {}) }, ...rest]);
          onCursorsRef.current({ ...cursorsRef.current, active: 0 });
        })
        .catch((e) => setNote(e instanceof Error ? e.message : String(e)));
    },
    [current, moveCursors],
  );

  const saveCut = useCallback(
    (which: "row" | "column" | "trace") => {
      const sid = session.current, c = readingRef.current?.cursors[0];
      if (!sid || !c) return;
      api
        .exploreSaveCut(sid, which, c.index, c.trace)
        .then(({ path }) => {
          const cut = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\")) + 1;
          const dir = path.slice(0, cut), name = path.slice(cut);
          const what = which === "trace" ? "this trace" : `this ${which}`;
          setConfirm({
            title: `Save ${what} as a new file`,
            text: `The stored data of ${what}, in a new .lbd file in the same folder, with notes on where it came from. ${info.name} is not changed.`,
            action: "Save",
            input: {
              value: name,
              selectEnd: name.length - 4,
              check: (v) => (!v.trim() ? "Give the file a name." : !v.toLowerCase().endsWith(".lbd") ? "The name must end in .lbd." : /[\\/:*?"<>|]/.test(v) ? "A name can't contain \\ / : * ? \" < > |" : null),
            },
            onConfirm: async (v) => {
              const saved = await api.exploreSaveCut(sid, which, c.index, c.trace, dir + v.trim());
              setNote(`Saved ${saved.path}`);
            },
          });
        })
        .catch((e) => setNote(e instanceof Error ? e.message : String(e)));
    },
    [info.name],
  );

  actions.current = {
    find,
    saveCut,
    showCut: (which) => {
      const c = readingRef.current?.cursors[0];
      if (c) onShowCut(which, c.index);
    },
    typed: (i, axis, stored) => {
      const r = readingRef.current;
      if (!r) return;
      const now = r.cursors.filter((c): c is CursorRead => !!c).map(askOf);
      if (!now[i]) return;
      const f = r.factors[axis];
      now[i] = { ...now[i], [axis]: stored * f, free: false };
      if (axis === "y") delete now[i].trace; // another height: the nearest trace there
      moveCursors(now);
    },
    remove: clearCursors,
    histogram: (st) => (session.current ? api.exploreHistogram(session.current, st) : Promise.resolve(null)),
    calculate: async (what, index) => {
      const sid = session.current, m = current(), r = readingRef.current;
      if (!sid || !m) throw new Error("the plot isn't open yet");
      const [c1, c2] = r?.cursors ?? [];
      const xlim = c1 && c2 ? [Math.min(c1.x, c2.x), Math.max(c1.x, c2.x)] : [...m.view.xlim];
      const res = await api.exploreCalculate(sid, what, index, xlim, kindRef.current === "curve" ? c1?.trace : undefined);
      return res.value;
    },
  };

  const openMenu = (clientX: number, clientY: number, x: number, y: number) => {
    const r = readingRef.current, c1 = r?.cursors[0];
    const map = kindRef.current === "heatmap";
    const items: MenuEntry[] = [
      { label: "Cursor 1 here", onClick: () => placeCursor(0, x, y, false, false) },
      { label: "Cursor 2 here", onClick: () => placeCursor(1, x, y, false, false), disabled: !c1 },
      "-",
      { label: "Max", onClick: () => find("max") },
      { label: "Min", onClick: () => find("min") },
      { label: "Peak (farthest from the median)", onClick: () => find("peak") },
      { label: "Remove cursors", onClick: clearCursors, disabled: !c1 },
      "-",
      ...(map
        ? ([
            { label: "Show row as curve", onClick: () => c1 && onShowCut("row", c1.index), disabled: !c1 },
            { label: "Show column as curve", onClick: () => c1 && onShowCut("column", c1.index), disabled: !c1 },
            { label: "Save row as .lbd…", onClick: () => saveCut("row"), disabled: !c1 },
            { label: "Save column as .lbd…", onClick: () => saveCut("column"), disabled: !c1 },
          ] as MenuEntry[])
        : ([{ label: "Save trace as .lbd…", onClick: () => saveCut("trace"), disabled: !c1 }] as MenuEntry[])),
      "-",
      { label: "Show everything", onClick: () => setView(null) },
      { label: "Mouse and keys…", onClick: () => setHelp(true) },
    ];
    setMenu({ x: clientX, y: clientY, items });
  };

  const onKeyDown = (e: ReactKeyboardEvent<HTMLCanvasElement>) => {
    const r = readingRef.current, st = cursorsRef.current, m = current();
    const now = (r?.cursors ?? []).filter((c): c is CursorRead => !!c).map(askOf);
    const step = (dx: number, dy: number) => {
      if (!now.length) return;
      const i = Math.min(st.active, now.length - 1);
      now[i] = { ...now[i], free: false, step: [dx, dy] };
      moveCursors(now);
    };
    const k = e.key;
    if (k === "ArrowLeft" || k === "ArrowRight") step((k === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 10 : 1), 0);
    else if (k === "ArrowUp" || k === "ArrowDown") step(0, (k === "ArrowUp" ? 1 : -1) * (e.shiftKey ? 10 : 1));
    else if (k === "Tab" && now.length === 2) onCursorsRef.current({ ...st, active: st.active === 0 ? 1 : 0 });
    else if (k === "m" || k === "M") find("max");
    else if (k === "n" || k === "N") find("min");
    else if (k === "p" || k === "P") find("peak");
    else if (k === "[" || k === "]") onStepSlider(k === "[" ? -1 : 1);
    else if ((k === "+" || k === "=" || k === "-" || k === "_") && m && wanted.current) {
      const f = k === "-" || k === "_" ? 1.25 : 0.8, v = wanted.current, c = r?.cursors[0];
      const ax = c ? c.x : back(m.xscale, (fwd(m.xscale, v.xlim[0]) + fwd(m.xscale, v.xlim[1])) / 2);
      const ay = c ? c.y : back(m.yscale, (fwd(m.yscale, v.ylim[0]) + fwd(m.yscale, v.ylim[1])) / 2);
      setView({ xlim: zoomRange(v.xlim, ax, f, m.xscale), ylim: zoomRange(v.ylim, ay, f, m.yscale) });
    } else if (k === "Home" || k === "0") setView(null);
    else if ((k === "c" || k === "C") && kindRef.current === "heatmap") onCursorsRef.current({ ...st, cuts: !st.cuts });
    else if (k === "k" || k === "K") onCursorsRef.current({ ...st, on: !st.on });
    else if (k === "Escape") {
      if (box.current) {
        box.current = null;
        down.current = null;
        paintOverlay();
      } else clearCursors();
    } else if (k === "?") setHelp((h) => !h);
    else return;
    e.preventDefault();
  };

  useEffect(() => paintOverlay(), [reading, cursors.active, paintOverlay]);

  // ---- layout

  const cssSize: CSSProperties = meta ? { width: meta.width / meta.dpr, height: meta.height / meta.dpr } : {};
  const showCuts = opened?.kind === "heatmap" && cursors.cuts && cursors.on;
  const plotCss = meta ? meta.plot.map((v) => v / meta.dpr) : null;
  const c1 = reading?.cursors[0] ?? null, c2 = reading?.cursors[1] ?? null;

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
        <label className="check" title="Off: a click places no cursor (key K)">
          <input type="checkbox" checked={cursors.on} onChange={(e) => onCursorsRef.current({ ...cursorsRef.current, on: e.target.checked })} />
          Cursors
        </label>
        {opened?.kind === "heatmap" && (
          <label className="check" title="The row and column through cursor 1, beside the map (key C)">
            <input
              type="checkbox"
              checked={cursors.cuts}
              disabled={!cursors.on}
              onChange={(e) => onCursorsRef.current({ ...cursorsRef.current, cuts: e.target.checked })}
            />
            Cuts
          </label>
        )}
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
      <div className={"explore-stage" + (showCuts ? " with-cuts" : "")}>
        {showCuts && (
          <div className="explore-cut explore-cut-top">
            <canvas
              ref={topCut}
              style={plotCss ? { left: plotCss[0], width: plotCss[2], height: CUT_PX - 6 } : {}}
              onMouseMove={(e) => setCutHover(cutValue(reading?.cuts?.row, e, "x", current(), reading))}
              onMouseLeave={() => setCutHover(null)}
            />
            {!c1 && <span className="muted small">Click the map: its row shows here</span>}
          </div>
        )}
        {showCuts && <div className="explore-cut-corner" />}
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
          onKeyDown={onKeyDown}
          tabIndex={0}
          aria-label="Plot: click for a cursor, drag to zoom, ? for all mouse actions and keys"
        />
        {help && (
          <div className="explore-help" role="dialog" aria-label="Mouse and keys">
            <button className="link" onClick={() => setHelp(false)} aria-label="Close">
              ×
            </button>
            <table>
              <tbody>
                {HELP.map(([k, v]) => (
                  <tr key={k}>
                    <th>{k}</th>
                    <td>{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
        {showCuts && (
          <div className="explore-cut explore-cut-right">
            <canvas
              ref={rightCut}
              style={plotCss ? { top: plotCss[1], height: plotCss[3], width: CUT_PX - 6 } : {}}
              onMouseMove={(e) => setCutHover(cutValue(reading?.cuts?.column, e, "y", current(), reading))}
              onMouseLeave={() => setCutHover(null)}
            />
          </div>
        )}
      </div>
      <div className="explore-readout">
        <div className="muted small">
          {cursors.on ? "Click: cursor · Shift+click: second cursor · " : ""}drag: zoom · right-drag: pan ·{" "}
          <button className="link" onClick={() => setHelp((h) => !h)}>
            ? all mouse actions and keys
          </button>
          {mouse && (
            <>
              {" "}
              · mouse at x = {fmt(mouse[0])}, y = {fmt(mouse[1])}
            </>
          )}
        </div>
        {c1 ? (
          <CursorLine n={1} c={c1} />
        ) : (
          <div className="muted small">{cursors.on ? "Click the plot to read a stored value." : "Cursors are off: a click does nothing (K or Cursors above the plot turns them on)."}</div>
        )}
        {c2 && <CursorLine n={2} c={c2} />}
        {c1 && c2 && (
          <div className="explore-pick small">
            {between(c1, c2).map((d) => (
              <span key={d.role} className="range-part">
                Δ{d.label} = {si(d.delta, d.unit)} · ⟨{d.label}⟩ = {si(d.mean, d.unit)}
              </span>
            ))}
          </div>
        )}
        {cutHover && <div className="small">{cutHover}</div>}
        {note && (
          <div className="small" role="status">
            {note}{" "}
            <button className="link" onClick={() => setNote(null)}>
              OK
            </button>
          </div>
        )}
        {timing && <div className="muted small mono">{timing}</div>}
      </div>
      {menu && <ContextMenu menu={menu} onClose={() => setMenu(null)} />}
      {confirm && <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />}
    </div>
  );
}

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return Number(v.toPrecision(7)).toString();
}

/** One cursor's numbers under the plot: its value first, then where it is. */
function CursorLine({ n, c }: { n: number; c: CursorRead }) {
  const z = item(c, "z") ?? item(c, "y");
  const rest = c.items.filter((i) => i !== z);
  return (
    <div className="explore-pick">
      <span className="cursor-tag" style={{ color: CURSOR_COLORS[n - 1] }}>
        {n}
      </span>{" "}
      {z && <strong>{readText(z)}</strong>} at {rest.map(readText).join(", ")}
      {c.free && <span className="muted small"> (free position; the nearest stored value)</span>}
      {c.stored && (
        <span className="muted small">
          {" "}
          (stored: {c.stored.label} = {si(c.stored.value, c.stored.unit)})
        </span>
      )}
    </div>
  );
}

/** The value of a cut under the mouse, as text. */
function cutValue(cut: Cut | undefined, e: { clientX: number; clientY: number; currentTarget: HTMLCanvasElement }, along: "x" | "y", m: Mapping | null, r: CursorsAnswer | null): string | null {
  if (!cut || !m || !r) return null;
  const rect = e.currentTarget.getBoundingClientRect();
  const lim = along === "x" ? m.view.xlim : m.view.ylim, scale = along === "x" ? m.xscale : m.yscale;
  const f = along === "x" ? (e.clientX - rect.left) / rect.width : 1 - (e.clientY - rect.top) / rect.height;
  const at = back(scale, fwd(scale, lim[0]) + f * (fwd(scale, lim[1]) - fwd(scale, lim[0])));
  let best = -1, d = Infinity;
  cut.pos.forEach((p, i) => {
    if (Math.abs(p - at) < d && cut.z[i] !== null) [best, d] = [i, Math.abs(p - at)];
  });
  if (best < 0) return null;
  const zi = item(r.cursors[0], "z"), ai = item(r.cursors[0], along);
  if (!zi || !ai) return null;
  const zf = r.factors.z, af = r.factors[along];
  return `${along === "x" ? "Row" : "Column"}: ${zi.label} = ${si(cut.z[best]! / zf, zi.unit)} at ${ai.label} = ${si(cut.pos[best] / af, ai.unit)}`;
}

/** Draw the cuts through cursor 1: the row above the map (along x), the column beside it (along y),
 *  on exactly the map's axes. Their value axis fits the part in view. */
function paintCuts(top: HTMLCanvasElement | null, right: HTMLCanvasElement | null, m: Mapping, r: CursorsAnswer | null) {
  const dpr = window.devicePixelRatio || 1;
  const draw = (c: HTMLCanvasElement | null, cut: Cut | undefined, along: "x" | "y") => {
    if (!c) return;
    const w = c.clientWidth, h = c.clientHeight;
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
      c.width = Math.round(w * dpr);
      c.height = Math.round(h * dpr);
    }
    const ctx = c.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const style = getComputedStyle(c);
    const ink = style.color || "#222";
    ctx.strokeStyle = style.borderColor || "#ccc";
    ctx.lineWidth = 1;
    ctx.strokeRect(0.5, 0.5, w - 1, h - 1);
    if (!cut || !r) return;
    const lim = along === "x" ? m.view.xlim : m.view.ylim, scale = along === "x" ? m.xscale : m.yscale;
    const a = fwd(scale, lim[0]), b = fwd(scale, lim[1]);
    const len = along === "x" ? w : h;
    const posPx = (p: number) => ((fwd(scale, p) - a) / (b - a)) * len;
    let [lo, hi] = cut.range;
    if (lo === null || hi === null) return;
    if (lo === hi) [lo, hi] = [lo - 0.5, hi + 0.5];
    const pad = (hi - lo) * 0.08;
    const span = along === "x" ? h : w;
    const valPx = (v: number) => 3 + ((v - (lo! - pad)) / (hi! - lo! + 2 * pad)) * (span - 6);
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, w, h);
    ctx.clip();
    ctx.strokeStyle = ink;
    ctx.lineWidth = 1.25;
    ctx.beginPath();
    let pen = false;
    cut.pos.forEach((p, i) => {
      const z = cut.z[i];
      if (z === null) {
        pen = false;
        return;
      }
      const u = posPx(p), v = valPx(z);
      const [x, y] = along === "x" ? [u, h - v] : [v, h - u];
      if (pen) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
      pen = true;
    });
    ctx.stroke();
    // where the cursors are along this cut
    r.cursors.forEach((cr, i) => {
      if (!cr) return;
      const u = posPx(along === "x" ? cr.x : cr.y);
      ctx.strokeStyle = CURSOR_COLORS[i];
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      if (along === "x") {
        ctx.moveTo(u, 0);
        ctx.lineTo(u, h);
      } else {
        ctx.moveTo(0, h - u);
        ctx.lineTo(w, h - u);
      }
      ctx.stroke();
      ctx.setLineDash([]);
    });
    ctx.restore();
    // the value range in view, in the value's unit
    const zi = item(r.cursors[0], "z");
    if (zi) {
      ctx.fillStyle = ink;
      ctx.font = "10px system-ui, sans-serif";
      const t = (v: number) => si(v / r.factors.z, zi.unit, 4);
      if (along === "x") {
        ctx.fillText(t(hi), 4, 11);
        ctx.fillText(t(lo), 4, h - 4);
      } else {
        ctx.save();
        ctx.translate(w - 3, h - 4);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText(t(hi), 0, 0);
        ctx.restore();
        ctx.save();
        ctx.translate(11, h - 4);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText(t(lo), 0, 0);
        ctx.restore();
      }
    }
  };
  draw(top, r?.cuts?.row, "x");
  draw(right, r?.cuts?.column, "y");
}

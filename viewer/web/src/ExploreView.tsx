import { flushSync } from "react-dom";
import {
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  MutableRefObject,
  PointerEvent as ReactPointerEvent,
  ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import NumberRange from "./NumberRange";
import { kindOf } from "./plotKinds";
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
  SyncKeys,
} from "./api";
import { labelPlaces, between, CursorsState, HELP, item, readText, si } from "./cursors";
import { ConfirmDialog, ConfirmRequest, ContextMenu, MenuAt, MenuEntry, Popover } from "./menu";
import type { ExportSource } from "./ExportDialog";
import type { PictureWhat } from "./clipboard";
import { SummaryProgress } from "./SummaryProgress";
import { Icon } from "./icons";
import { useToast } from "./toast";

/** The timing line under the plot (server and drawing times) is for developers: ?debug in the address. */
const DEBUG = (() => {
  try {
    return new URLSearchParams(window.location.search).has("debug");
  } catch {
    return false;
  }
})();

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
  [more: string]: unknown; // what a plot type adds to a view (3D bars: the angle)
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
  equations?: { x?: string; y?: string; z?: string }; // after the operations (equations.py)
  crange?: "slice" | "all"; // a map with a slider: colours from the slice shown or from every slice (crange.py)
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

const moreOf = (v: View) => Object.fromEntries(Object.entries(v).filter(([k]) => k !== "xlim" && k !== "ylim"));
const same = (a: View | null, b: View | null) =>
  !!a && !!b && JSON.stringify(moreOf(a)) === JSON.stringify(moreOf(b)) && a.xlim[0] === b.xlim[0] && a.xlim[1] === b.xlim[1] && a.ylim[0] === b.ylim[0] && a.ylim[1] === b.ylim[1];


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
  /** Another panel's zoom to follow (several panels, synchronized); a new `seq` applies it. */
  follow?: Follow | null;
  /** The user changed the view here (zoom, pan, typed limits; null: show everything). */
  onUserView?: (v: View | null) => void;
  /** With each picture: what this view must share with another to follow its zoom, and where all its data is. */
  onSync?: (s: SyncKeys & { full: [Lim, Lim] }) => void;
  /** With each picture of a map with a slider: where its colours come from (crange.py). */
  onCrange?: (c: ExploreFrameMeta["crange"]) => void;
  /** Getting data out (plan 5): the entries of this panel's Data menu (also in the right-click menu). */
  dataItems?: () => MenuEntry[];
  /** The left of the panel's toolbar: its number and name (and what drags it). */
  title?: ReactNode;
  /** The panel being worked on (one panel: always): only it shows the "click the plot" hint. */
  active?: boolean;
  /** More entries for the panel's ⋯ menu (duplicate, remove …). */
  panelItems?: () => MenuEntry[];
  /** The plot couldn't be opened (the reason), so the controls can say so. */
  onFailed?: (msg: string) => void;
  /** What a plot Explore can't draw offers instead: Figure, or the values as curves. */
  onOpenInFigure?: () => void;
  onShowCurves?: () => void;
}

/** Limits pushed from another panel: x, y or both. */
export interface Follow {
  xlim?: Lim;
  ylim?: Lim;
  /** Everything is shown: an axis not given shows all of this panel's data. */
  all?: boolean;
  seq: number;
}

/** What the Cursors section (and the menu) can ask the view to do. */
export interface ExploreActions {
  find: (what: "max" | "min" | "peak") => void;
  saveCut: (which: "row" | "column" | "trace") => void;
  showCut: (which: "row" | "column") => void;
  /** Cursor i to a typed stored value along x or y (snapped to the data). */
  typed: (i: number, axis: "x" | "y", stored: number) => void;
  /** Remove both cursors (with Undo). */
  remove: () => void;
  /** Remove cursor 2 only (cursor 1 stays). */
  removeSecond: () => void;
  /** Show (or hide) the mouse and keys help. */
  help: () => void;
  /** A map's values counted with these view settings (the contrast control). */
  histogram: (settings: ViewSettings) => Promise<Histogram | null>;
  /** Operation `index`'s delay (s) or rotation (°), from the data between the cursors (else in
   *  view), on cursor 1's trace (else all shown). */
  calculate: (what: "delay" | "rotation", index: number) => Promise<number>;
  /** What Save as CSV needs from this panel: its session, its view now and its kind. */
  exportSource: () => ExportSource | null;
  /** The same for a cut through cursor 1 (null: no cursor here, or another kind of plot). */
  cutSource: (which: "row" | "column" | "trace") => ExportSource | null;
  /** What Copy picture takes from this panel: its canvases and the area they fill on the page
   *  ("screen": the plot with cursors and cuts; "plot": the plot alone). */
  snapshot: (what: PictureWhat) => { canvases: HTMLCanvasElement[]; area: Element } | null;
}

const CURSOR_COLORS = ["#e0001b", "#0057d9"];
const GRAB_PX = 7; // how near a cursor the mouse must be to drag it

const askOf = (c: CursorRead): CursorAsk => ({ x: c.x, y: c.y, ...(c.trace !== undefined ? { trace: c.trace } : {}), ...(c.free ? { free: true } : {}) });
const cursorsKey = (type: string, at: CursorAsk[], cuts: boolean, on: boolean, every?: boolean, atLine?: string) =>
  JSON.stringify({ type, cuts, on, every: every !== false, atLine: atLine ?? "interpolated", at: at.map((a) => [a.x, a.y, a.trace ?? null, !!a.free]) });

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
  initialView,
  onView,
  cursors,
  onCursors,
  onReading,
  actions,
  onStepSlider,
  onShowCut,
  onOpsInfo,
  follow = null,
  onUserView,
  onSync,
  onCrange,
  dataItems,
  title,
  active = true,
  panelItems,
  onFailed,
  onOpenInFigure,
  onShowCurves,
}: Props) {
  const onFailedRef = useRef(onFailed);
  onFailedRef.current = onFailed;
  const toast = useToast();
  const limitsButton = useRef<HTMLButtonElement>(null);
  const [limitsOpen, setLimitsOpen] = useState(false);
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
  // An axis that now measures something else (its equation changed, or an operation changed its
  // label or unit): the next picture shows all of it; the other axis keeps its zoom.
  const resetAxes = useRef({ x: false, y: false });
  const checkAxes = useRef(false); // view settings changed: compare the next picture's axes with the last
  const clearCursorsRef = useRef<() => void>(() => {});
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
  const followRef = useRef(follow);
  followRef.current = follow;
  const onUserViewRef = useRef(onUserView);
  onUserViewRef.current = onUserView;
  const onSyncRef = useRef(onSync);
  onSyncRef.current = onSync;
  const onCrangeRef = useRef(onCrange);
  onCrangeRef.current = onCrange;
  const crangeTimer = useRef(0);
  const kindRef = useRef<string | null>(null);
  kindRef.current = opened?.kind ?? null;
  const readingRef = useRef<CursorsAnswer | null>(null); // the cursors on screen: the last answer
  const answered = useRef(""); // cursorsKey of the last answer: an echo of it asks nothing
  const cursorBusy = useRef(false);
  const cursorNext = useRef<CursorAsk[] | null>(null);
  // Counts the times cursors were switched off or removed: an answer asked for before that
  // (with a new picture, or a move) is dropped, so it never brings them back.
  const cursorsGone = useRef(0);
  const drag = useRef<number | null>(null); // the cursor being dragged
  const dragFrom = useRef<CursorAsk[] | null>(null); // moving both: where they were when the drag began
  const stage = useRef<HTMLDivElement>(null);
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
    // every mark twice: a wider edge first, then its colour, so a cursor shows on any background
    // (a blue cursor on a blue map); the edge is solid under a dashed line
    const edge = document.documentElement.dataset.theme === "dark" && kindRef.current === "curve" ? "rgba(24,24,24,0.85)" : "rgba(255,255,255,0.85)";
    const edged = (color: string, width: number, path: () => void, dash: number[] = []) => {
      ctx.beginPath();
      path();
      ctx.setLineDash([]);
      ctx.strokeStyle = edge;
      ctx.lineWidth = width + 2;
      ctx.stroke();
      ctx.setLineDash(dash);
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.stroke();
      ctx.setLineDash([]);
    };
    const places: ([number, number] | null)[] = (r?.cursors ?? []).map((c) => (c ? (toPx(m, c.x, c.y) as [number, number]) : null));
    r?.cursors.forEach((c, i) => {
      if (!c) return;
      const [x, y] = places[i]!;
      const color = CURSOR_COLORS[i];
      const active = cursorsRef.current.active === i && r.cursors.length === 2;
      edged(
        color,
        active ? 2 : 1.25,
        () => {
          if (r.type !== "horizontal") {
            ctx.moveTo(x, ct);
            ctx.lineTo(x, ct + h);
          }
          if (r.type !== "vertical") {
            ctx.moveTo(cl, y);
            ctx.lineTo(cl + w, y);
          }
        },
        r.type === "cross" ? [5, 4] : [],
      );
      if (c.cell && r.type === "cross") {
        const [ax, ay] = toPx(m, c.cell[0], c.cell[1]);
        const [bx, by] = toPx(m, c.cell[2], c.cell[3]);
        if (Math.abs(bx - ax) > 8 && Math.abs(by - ay) > 8) edged(color, 1.25, () => ctx.rect(Math.min(ax, bx), Math.min(ay, by), Math.abs(bx - ax), Math.abs(by - ay)));
      }
      if (r.type !== "horizontal" || kindRef.current === "heatmap") edged(color, 2, () => ctx.arc(x, y, 6, 0, 2 * Math.PI));
    });
    // where a vertical or horizontal cursor meets each trace
    r?.cursors.forEach((c) =>
      c?.points?.forEach((p) => {
        const [x, y] = toPx(m, p.x, p.y);
        ctx.beginPath();
        ctx.arc(x, y, 3.5, 0, 2 * Math.PI);
        ctx.fillStyle = p.color;
        ctx.fill();
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = edge;
        ctx.stroke();
      }),
    );
    // the numbers: small badges, placed so they are never on top of each other
    const badges = labelPlaces(places, [l, t, w, h], r?.type ?? "cross");
    for (const b of badges) {
      ctx.beginPath();
      ctx.roundRect(b.x - b.w / 2, b.y - b.h / 2, b.w, b.h, b.h / 2);
      ctx.fillStyle = edge;
      ctx.lineWidth = 3;
      ctx.strokeStyle = edge;
      ctx.stroke();
      b.cursors.forEach((n, k) => {
        const part = b.w / b.cursors.length;
        ctx.save();
        ctx.beginPath();
        ctx.roundRect(b.x - b.w / 2, b.y - b.h / 2, b.w, b.h, b.h / 2);
        ctx.clip();
        ctx.fillStyle = CURSOR_COLORS[n];
        ctx.fillRect(b.x - b.w / 2 + k * part, b.y - b.h / 2, part, b.h);
        ctx.fillStyle = "#fff";
        ctx.font = "bold 11px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(n + 1), b.x - b.w / 2 + (k + 0.5) * part, b.y + 0.5);
        ctx.restore();
      });
    }
    c.dataset.badges = JSON.stringify(badges);
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
    const reset = { ...resetAxes.current };
    const check = checkAxes.current;
    checkAxes.current = false;
    const sizeNow = sz ? { width: sz.w, height: sz.h, dpr: window.devicePixelRatio || 1 } : {};
    // null: all of that axis (the server's whole range)
    const view = all || !v ? { xlim: null, ylim: null } : { xlim: reset.x ? null : v.xlim, ylim: reset.y ? null : v.ylim };
    api
      .exploreRender(sid, {
        ...view,
        ...(v ? moreOf(v) : {}),
        stat: statRef.current,
        format: formatRef.current,
        settings: settingsRef.current,
        draft: moving.current,
        ...sizeNow,
      })
      .then(async (f) => {
        if (session.current !== sid) return;
        // an operation changed what an axis measures (FFT: time → frequency, d/dx, normalize):
        // show all of that axis, and the cursors (at the old numbers) go
        const was = frame.current?.meta.sync, now = f.meta.sync;
        if (check && !all && was && now && (was.x !== now.x || was.y !== now.y)) {
          resetAxes.current = { x: resetAxes.current.x || was.x !== now.x, y: resetAxes.current.y || was.y !== now.y };
          if (cursorsRef.current.at.length) clearCursorsRef.current();
          dirty.current = true;
          return; // asked again (finally), with that axis whole
        }
        if (reset.x || reset.y) {
          resetAxes.current = { x: resetAxes.current.x && !reset.x, y: resetAxes.current.y && !reset.y };
          const w = wanted.current;
          wanted.current = { xlim: reset.x || !w ? f.meta.xlim : w.xlim, ylim: reset.y || !w ? f.meta.ylim : w.ylim };
        }
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
        if (f.meta.sync?.x !== undefined) onSyncRef.current?.({ ...(f.meta.sync as SyncKeys), full: f.meta.full });
        onCrangeRef.current?.(f.meta.crange ?? null);
        if (f.meta.crange?.state === "working" && !crangeTimer.current) {
          // every slice's colour range is being worked out: the same view again in a moment
          crangeTimer.current = window.setTimeout(() => {
            crangeTimer.current = 0;
            dirty.current = true;
            if (f.meta.crange?.from === "histogram") showAll.current = true; // the bars are growing
            if (session.current === sid) request();
          }, 700);
        }
        if (f.meta.notes?.length) onErrorRef.current(f.meta.notes.join(" "));
        let src = frameCanvas.current;
        if (!src) src = frameCanvas.current = document.createElement("canvas");
        src.width = f.meta.width;
        src.height = f.meta.height;
        const sctx = src.getContext("2d")!;
        if (f.image instanceof ImageData) sctx.putImageData(f.image, 0, 0);
        else sctx.drawImage(f.image, 0, 0);
        // the cuts coming or going: strips, box and picture change in one frame (see the cuts' effect)
        const change = cutsChange.current;
        if (change && Math.abs(f.meta.width / f.meta.dpr - change.w) <= 1 && Math.abs(f.meta.height / f.meta.dpr - change.h) <= 1) {
          window.clearTimeout(change.timer);
          cutsChange.current = null;
          flushSync(() => {
            setShownCuts(change.want);
            setMeta(f.meta);
          });
        }
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
    const sid = session.current, st = cursorsRef.current, gone = cursorsGone.current;
    if (!sid || !at.length) return Promise.resolve();
    const cuts = st.cuts && !!kindOf(kindRef.current).strips;
    return api
      .exploreCursors(sid, { cursors: at, type: st.type, xlim: m.view.xlim, ylim: m.view.ylim, width: m.plot[2], height: m.plot[3], cuts, every: st.every !== false, at_line: st.at_line ?? "interpolated", together: !!st.together })
      .then((a) => {
        if (session.current !== sid || cursorsGone.current !== gone) return;
        readingRef.current = a;
        setReading(a);
        onReadingRef.current(a);
        const snapped = a.cursors.filter((c): c is CursorRead => !!c).map(askOf);
        answered.current = cursorsKey(st.type, snapped, st.cuts, st.on, st.every, st.at_line);
        if (cursorsKey(st.type, at, st.cuts, st.on, st.every, st.at_line) !== answered.current || st.at.length !== snapped.length)
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
    cursorsGone.current++;
    cursorNext.current = null;
    readingRef.current = null;
    answered.current = cursorsKey(cursorsRef.current.type, [], cursorsRef.current.cuts, cursorsRef.current.on, cursorsRef.current.every, cursorsRef.current.at_line);
    setReading(null);
    onReadingRef.current(null);
    onCursorsRef.current({ ...cursorsRef.current, at: [], active: 0 });
    paintOverlay();
  }, [paintOverlay]);
  clearCursorsRef.current = clearCursors;

  // Pointing at a dot on a cursor line names its trace and the number read there.
  useEffect(() => {
    const c = overlay.current;
    if (!c) return;
    const move = (e: globalThis.MouseEvent) => {
      const m = current(), r = readingRef.current;
      const box = c.getBoundingClientRect();
      let text = "";
      for (const cur of r?.cursors ?? []) {
        for (const p of (m && cur?.points) || []) {
          const [x, y] = toPx(m!, p.x, p.y);
          if (Math.hypot(x - (e.clientX - box.left), y - (e.clientY - box.top)) > 6) continue;
          const row = cur!.table?.rows.find((q) => q.trace === p.trace);
          text = row ? `${p.label}: ${si(row.value, row.unit ?? cur!.table!.unit)}` : `${p.label}: ${si(p.x / (r!.factors.x || 1), cur!.crossings?.x_unit ?? "")}`;
        }
      }
      c.title = text;
    };
    c.addEventListener("mousemove", move);
    return () => c.removeEventListener("mousemove", move);
  }, [current]);

  // A view that ends (another plot, back to the map) takes its read-outs with it.
  useEffect(() => () => onReadingRef.current(null), []);

  // Cursors set elsewhere (remembered, typed, another type, cuts or cursors on or off): ask for
  // them. Off: hidden, but kept, so they come back as they were.
  const cursorsNow = cursorsKey(cursors.type, cursors.at, cursors.cuts, cursors.on, cursors.every, cursors.at_line);
  const haveFrame = !!meta;
  useEffect(() => {
    if (!haveFrame || cursorsNow === answered.current) return;
    const st = cursorsRef.current;
    if (!st.on) {
      cursorsGone.current++;
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
  const showView = useCallback(
    (v: View | null) => {
      const full = frame.current?.meta.full;
      wanted.current = v ?? (full ? { xlim: full[0], ylim: full[1] } : null);
      paint();
      request();
    },
    [paint, request],
  );
  /** The user shows this view (or all the data): panels that follow this one are told. */
  const setView = useCallback(
    (v: View | null) => {
      showView(v);
      onUserViewRef.current?.(v);
    },
    [showView],
  );

  // Another panel's zoom (synchronized panels): shown here as if moved here, never echoed back.
  const followSeq = follow?.seq;
  useEffect(() => {
    const f = followRef.current, full = frame.current?.meta.full;
    const v = f?.all && full ? { xlim: full[0], ylim: full[1] } : wanted.current;
    if (!f || !v) return;
    markMoving(); // drafts while the other panel moves, the sharp picture when it rests
    showView({ xlim: f.xlim ?? v.xlim, ylim: f.ylim ?? v.ylim });
  }, [followSeq, showView, markMoving]);

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

  // Cuts on or off: the strips take room from the plot. The picture for the new room is asked for at
  // once and the old layout stays until it is here, so everything changes together (not the strips
  // first, the picture half a second later). A picture that takes long doesn't hold it up.
  const firstValueNow = info.values.find((v) => v.name === (spec.values ?? [])[0]) ?? info.values.find((v) => v.shape.length > 0);
  const kindOfPanel = opened?.kind ?? spec.kind ?? (firstValueNow && firstValueNow.shape.filter((n) => n > 1).length >= 2 ? "heatmap" : "curve");
  const stripsNow = meta?.strips !== undefined && opened?.kind === kindOfPanel ? meta.strips : kindOf(kindOfPanel).strips;
  const wantCuts = !!stripsNow && cursors.cuts && cursors.on;
  const [shownCuts, setShownCuts] = useState(wantCuts);
  const cutsChange = useRef<{ want: boolean; w: number; h: number; timer: number } | null>(null);
  const cutsKind = useRef(kindOfPanel);
  useLayoutEffect(() => {
    const sameKind = cutsKind.current === kindOfPanel;
    cutsKind.current = kindOfPanel;
    const waiting = cutsChange.current;
    if (waiting) {
      window.clearTimeout(waiting.timer);
      cutsChange.current = null;
    }
    const box = stage.current, plot = host.current;
    if (wantCuts === shownCuts) {
      if (waiting && plot) setSize({ w: plot.clientWidth, h: plot.clientHeight }); // changed back meanwhile
      return;
    }
    if (!sameKind || !frame.current || !box) {
      setShownCuts(wantCuts);
      return;
    }
    // the strips' sizes, as in styles.css (.explore-tab .explore-stage.with-cuts)
    const W = box.clientWidth, H = box.clientHeight;
    const w = wantCuts ? W - Math.min(96, 0.22 * W) : W;
    const h = wantCuts ? H - Math.min(96, Math.max(36, 0.22 * H)) : H;
    const timer = window.setTimeout(() => {
      cutsChange.current = null;
      setShownCuts(wantCuts);
    }, 1000);
    cutsChange.current = { want: wantCuts, w: Math.round(w), h: Math.round(h), timer };
    setSize({ w: Math.round(w), h: Math.round(h) });
  }, [wantCuts, shownCuts, kindOfPanel]);
  useEffect(() => () => window.clearTimeout(cutsChange.current?.timer), []);

  const specKey = JSON.stringify(spec);
  const openedSpecKey = useRef<string | null>(null); // the plot settings the session shows
  const [opens, setOpens] = useState(0); // a session opened: plot settings changed meanwhile are sent then
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
          setOpens((k) => k + 1);
          setOpened(o);
          onOpenedRef.current(o);
          // notes about what is drawn (a variable sweep against its point number …): in the panel, not a red toast
          if (o.warnings.length) setNote(o.warnings.map((w) => w.replace(/^[^:]*\.lbd: /, "")).join(" "));
          // the zoom to keep, else all the data as the server finds it (with the view settings applied)
          wanted.current = keepView;
          showAll.current = !keepView;
          request();
        })
        .catch((e) => {
          if (!cancelled) {
            const msg = e instanceof Error ? e.message : String(e);
            setError(msg);
            setStatus("");
            onFailedRef.current?.(msg);
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
  // else (another value, kind, axis, complex mode) starts from the whole data. Settings changed
  // while the session was being opened are sent once it is open.
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
        // (a histogram's bins follow its numbers, so another slice has other limits)
        const keep = onlySlicesDiffer(before, specRef.current) && o.kind !== "histogram" && wanted.current;
        wanted.current = keep || { xlim: o.full[0], ylim: o.full[1] };
        dirty.current = true; // the last picture shows the old settings, even where the view is the same
        request();
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : String(e));
        setStatus("");
      });
  }, [specKey, request, opens]);

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
    // a new equation for x or y: that axis measures something else now (old limits mean nothing)
    const eb = before.equations ?? {}, ea = settings.equations ?? {};
    const ex = (eb.x ?? "") !== (ea.x ?? ""), ey = (eb.y ?? "") !== (ea.y ?? "");
    if (ex || ey) {
      resetAxes.current = { x: resetAxes.current.x || ex, y: resetAxes.current.y || ey };
      if (cursorsRef.current.at.length) clearCursorsRef.current();
    }
    checkAxes.current = true;
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
    const from = dragFrom.current;
    if (from?.length === 2 && cursorsRef.current.together && drag.current === i) {
      // both move: the same shift from where the drag began, stopping at the data's edge
      const [[x0, x1], [y0, y1]] = frame.current?.meta.full ?? [[-Infinity, Infinity], [-Infinity, Infinity]];
      const type = cursorsRef.current.type;
      const shift = (want: number, lo: number, hi: number, a: number, b: number) =>
        Math.min(Math.max(want, Math.max(Math.min(lo, hi) - a, Math.min(lo, hi) - b)), Math.min(Math.max(lo, hi) - a, Math.max(lo, hi) - b));
      const sx = type === "horizontal" ? 0 : shift(dx - from[i].x, x0, x1, from[0].x, from[1].x);
      const sy = type === "vertical" ? 0 : shift(dy - from[i].y, y0, y1, from[0].y, from[1].y);
      moveCursors(from.map((c) => ({ ...c, x: c.x + sx, y: c.y + sy })));
      return;
    }
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
        dragFrom.current = (readingRef.current?.cursors ?? []).filter((c): c is CursorRead => !!c).map(askOf);
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
        .then(async ({ path }) => {
          const cut = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\")) + 1;
          const dir = path.slice(0, cut), name = path.slice(cut);
          const what = which === "trace" ? "this trace" : `this ${which}`;
          try {
            // the system's Save dialog says where; only without one (501) the name is typed below
            const picked = await api.pickSave(info.path, name, "lbd", `Save ${what} as a new file`);
            if (picked.path === null) return;
            const saved = await api.exploreSaveCut(sid, which, c.index, c.trace, picked.path);
            setNote(`Saved ${saved.path}`);
            return;
          } catch (e) {
            if (!(e instanceof ApiError && e.status === 501)) throw e;
          }
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
    [info.name, info.path],
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
    remove: () => {
      const before = cursorsRef.current;
      if (!before.at.length) return;
      clearCursors();
      toast("Cursors removed.", "info", { label: "Undo", onClick: () => onCursorsRef.current(before) });
    },
    removeSecond: () => {
      const c1 = readingRef.current?.cursors[0];
      if (!c1) return;
      moveCursors([askOf(c1)]);
      onCursorsRef.current({ ...cursorsRef.current, active: 0 });
    },
    help: () => setHelp((h) => !h),
    histogram: (st) => (session.current ? api.exploreHistogram(session.current, st) : Promise.resolve(null)),
    calculate: async (what, index) => {
      const sid = session.current, m = current(), r = readingRef.current;
      if (!sid || !m) throw new Error("the plot isn't open yet");
      const [c1, c2] = r?.cursors ?? [];
      const xlim = c1 && c2 ? [Math.min(c1.x, c2.x), Math.max(c1.x, c2.x)] : [...m.view.xlim];
      const res = await api.exploreCalculate(sid, what, index, xlim, kindRef.current === "curve" ? c1?.trace : undefined);
      return res.value;
    },
    cutSource: (which) => {
      const c = readingRef.current?.cursors[0], s = actions.current?.exportSource();
      if (!c || !s || (which === "trace") !== (s.kind === "curve")) return null;
      return { ...s, cut: { which, index: c.index ?? {}, ...(c.trace !== undefined ? { trace: c.trace } : {}) } };
    },
    exportSource: () => {
      const sid = session.current, m = frame.current?.meta, kind = kindRef.current;
      return sid && kind ? { session: sid, view: m ? { xlim: [...m.xlim], ylim: [...m.ylim] } : null, kind, file: info.path } : null;
    },
    snapshot: (what) => {
      const pic = picture.current;
      if (!pic || !pic.width) return null;
      if (what === "plot" || !stage.current) return { canvases: [pic], area: pic };
      const more = [overlay.current, topCut.current, rightCut.current].filter((c): c is HTMLCanvasElement => !!c);
      return { canvases: [pic, ...more], area: stage.current };
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
      ...(dataItems ? ([...dataItems(), "-"] as MenuEntry[]) : []),
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
      // both move along x, and along y on a map (on curves up and down choose the active cursor's trace)
      const both = st.together && now.length === 2 && (kindRef.current === "heatmap" || dy === 0);
      if (both) moveCursors(now.map((c) => ({ ...c, free: false, step: [dx, dy] as [number, number] })));
      else {
        now[i] = { ...now[i], free: false, step: [dx, dy] };
        moveCursors(now);
      }
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
    else if ((k === "c" || k === "C") && stripsNow) onCursorsRef.current({ ...st, cuts: !st.cuts });
    else if (k === "k" || k === "K") onCursorsRef.current({ ...st, on: !st.on });
    else if (k === "Escape") {
      if (box.current) {
        box.current = null;
        down.current = null;
        paintOverlay();
      } else if (help) setHelp(false);
      else if (limitsOpen) setLimitsOpen(false);
      else if (document.querySelector("dialog[open], .context-menu, .popover-open")) return; // closing those, not the cursors
      else if (st.at.length) {
        const before = st;
        clearCursors();
        toast("Cursors removed.", "info", { label: "Undo", onClick: () => onCursorsRef.current(before) });
      }
    } else if (k === "?") setHelp((h) => !h);
    else return;
    e.preventDefault();
  };

  useEffect(() => paintOverlay(), [reading, cursors.active, paintOverlay]);

  // ---- layout

  const cssSize: CSSProperties = meta ? { width: meta.width / meta.dpr, height: meta.height / meta.dpr } : {};
  const showCuts = shownCuts;
  const plotCss = meta ? meta.plot.map((v) => v / meta.dpr) : null;
  const c1 = reading?.cursors[0] ?? null, c2 = reading?.cursors[1] ?? null;

  return (
    <div className="explore">
      <div className="explore-toolbar">
        {title}
        <span className="spacer" />
        {meta && (
          <span className={"explore-note" + (meta.reduced ? " reduced" : "")} title={meta.reduced
              ? `${meta.note}: more data than pixels, so each pixel shows several stored values. Zoom in to see every one; choose what a pixel shows in Display → Several cells per pixel. Cursors, Max / Min / Peak and the CSV always use the stored values.`
              : `${meta.note}: every stored value has its own pixels.`}>
            {meta.note}
          </span>
        )}
        <button className="ib" onClick={() => setView(null)} aria-label="Reset view" title="Reset view: all the data (key 0, or double-click the plot)">
          <Icon name="reset" />
        </button>
        {meta && (
          <button ref={limitsButton} className="ib" aria-label="Limits" aria-expanded={limitsOpen} aria-pressed={limitsOpen} onClick={() => setLimitsOpen((o) => !o)} title="Limits: type the range shown">
            <Icon name="limits" />
          </button>
        )}
        {opened && stripsNow && (
          <button
            className="ib"
            aria-label={stripsNow === "histograms" ? "Histograms" : "Cuts"}
            aria-pressed={cursors.cuts}
            disabled={!cursors.on}
            onClick={() => onCursorsRef.current({ ...cursorsRef.current, cuts: !cursorsRef.current.cuts })}
            title="Cuts: the rows and columns through the cursors, beside the map (key C)"
          >
            <Icon name="cuts" />
          </button>
        )}
        {dataItems && (
          <button
            className="ib"
            aria-haspopup="menu"
            aria-label="Data"
            title="Data: save the numbers shown as CSV, copy or save the picture"
            onClick={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              setMenu({ x: r.left, y: r.bottom, items: dataItems() });
            }}
          >
            <Icon name="download" />
          </button>
        )}
        <button
          className="ib"
          aria-haspopup="menu"
          aria-label="Panel menu"
          title="More: mouse and keys, panel"
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            setMenu({ x: r.right - 200, y: r.bottom, items: [{ label: "Mouse and keys… (?)", onClick: () => setHelp(true) }, ...(panelItems ? ["-" as const, ...panelItems()] : [])] });
          }}
        >
          <Icon name="more" />
        </button>
        {meta && limitsOpen && (
          <Popover className="explore-limits" label="Limits" onClose={() => setLimitsOpen(false)} opener={limitsButton}>
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
          </Popover>
        )}
      </div>
      {/* the cursors' numbers: a row per cursor, the panel's full width (the height changes only
          when cursor 2 comes or goes, never while a cursor moves); the full text in the tooltip */}
      <div className={"explore-readout" + (c2 ? " two" : "")} aria-live="polite">
        <div className="readout-row">
          {c1 ? (
            <CursorLine n={1} c={c1} />
          ) : cursors.on ? (
            active && <span className="muted small">Click the plot to read a stored value.</span>
          ) : (
            <span className="muted small">No cursor type chosen: a click does nothing (choose one in the Cursors tab, or press K).</span>
          )}
          {cutHover && <span className="small">{cutHover}</span>}
          {note && (
            <span className="small" role="status" title={note}>
              {note}{" "}
              <button className="link" onClick={() => setNote(null)}>
                OK
              </button>
            </span>
          )}
        </div>
        {c2 && (
          <div className="readout-row">
            <CursorLine n={2} c={c2} />
            {c1 && (
              <span className="explore-pick small delta" title={between(c1, c2).map((d) => `Δ${d.label} = ${si(d.delta, d.unit)}, mean ${si(d.mean, d.unit)}`).join(" · ")}>
                {between(c1, c2).map((d) => (
                  <span key={d.role} className="range-part">
                    Δ{d.label} = {si(d.delta, d.unit)}
                  </span>
                ))}
              </span>
            )}
          </div>
        )}
      </div>
      {error && (
        <div className="error-box explore-error" role="alert">
          {/scatter/i.test(error) ? (
            <>
              <strong>Explore can't show this saved scatter view.</strong> Figure draws it; or show the values here as curves.
              <div className="error-actions">
                {onOpenInFigure && <button onClick={onOpenInFigure}>Open in Figure</button>}
                {onShowCurves && <button onClick={onShowCurves}>Show as curves</button>}
              </div>
            </>
          ) : (
            <>
              <strong>This plot can't be shown.</strong>
              <details>
                <summary>Details</summary>
                <span className="small">{error.charAt(0).toUpperCase() + error.slice(1)}</span>
              </details>
            </>
          )}
        </div>
      )}
      {meta?.hidden && meta.hidden.length > 0 && (
        <div className="explore-hidden" role="status">
          {meta.hidden.map((h) => (
            <div key={h}>{h}</div>
          ))}
        </div>
      )}
      <div ref={stage} className={"explore-stage" + (showCuts ? " with-cuts" : "")}>
        {showCuts && (
          <div className="explore-cut explore-cut-top">
            <canvas
              ref={topCut}
              style={plotCss ? { left: plotCss[0], width: plotCss[2], height: "calc(100% - 6px)" } : {}}
              onMouseMove={(e) => setCutHover(cutValue("row", e, "x", current(), reading))}
              onMouseLeave={() => setCutHover(null)}
            />
            {!c1 && <span className="muted small">Click the map: its row shows here</span>}
          </div>
        )}
        {showCuts && <div className="explore-cut-corner" />}
      <div className="explore-host" ref={host}>
        {status && <div className="explore-status muted">{status}</div>}
        {status && <SummaryProgress path={info.path} />}
        {meta?.empty && !status && (
          <div className="explore-empty" role="status">
            {meta.empty}
          </div>
        )}
        <canvas ref={picture} className={"explore-picture " + (opened?.kind ?? "") + (opened && opened.kind !== "curve" && kindOf(opened.kind).darkInverted ? " curve" : "")} style={cssSize} />
        {mouse && <span className="mouse-at small">x = {fmt(mouse[0])}, y = {fmt(mouse[1])}</span>}
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
          <Popover className="explore-help" label="Mouse and keys" onClose={() => setHelp(false)}>
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
          </Popover>
        )}
      </div>
        {showCuts && (
          <div className="explore-cut explore-cut-right">
            <canvas
              ref={rightCut}
              style={plotCss ? { top: plotCss[1], height: plotCss[3], width: "calc(100% - 6px)" } : {}}
              onMouseMove={(e) => setCutHover(cutValue("column", e, "y", current(), reading))}
              onMouseLeave={() => setCutHover(null)}
            />
          </div>
        )}
      </div>
      {timing && DEBUG && <div className="muted small mono">{timing}</div>}
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
  const full = `${z ? readText(z) : ""} at ${rest.map(readText).join(", ")}`;
  return (
    <div className="explore-pick" title={full}>
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
function cutValue(which: "row" | "column", e: { clientX: number; clientY: number; currentTarget: HTMLCanvasElement }, along: "x" | "y", m: Mapping | null, r: CursorsAnswer | null): string | null {
  const cut = r?.cuts?.[which], cut2 = r?.cuts2?.[which];
  if (!cut || !m || !r || !r.cursors[0]) return null;
  const rect = e.currentTarget.getBoundingClientRect();
  const lim = along === "x" ? m.view.xlim : m.view.ylim, scale = along === "x" ? m.xscale : m.yscale;
  const f = along === "x" ? (e.clientX - rect.left) / rect.width : 1 - (e.clientY - rect.top) / rect.height;
  const at = back(scale, fwd(scale, lim[0]) + f * (fwd(scale, lim[1]) - fwd(scale, lim[0])));
  const nearest = (k: Cut) => {
    let best = -1, d = Infinity;
    k.pos.forEach((p, i) => {
      if (Math.abs(p - at) < d && k.z[i] !== null) [best, d] = [i, Math.abs(p - at)];
    });
    return best;
  };
  const best = nearest(cut);
  if (best < 0) return null;
  const zi = item(r.cursors[0], "z"), ai = item(r.cursors[0], along);
  if (!zi || !ai) return null;
  const zf = r.factors.z, af = r.factors[along];
  const value = (k: Cut, i: number) => `${zi.label} = ${si(k.z[i]! / zf, zi.unit)}`;
  const place = `at ${ai.label} = ${si(cut.pos[best] / af, ai.unit)}`;
  const name = along === "x" ? "Row" : "Column";
  if (!cut2) return `${name}: ${value(cut, best)} ${place}`;
  const best2 = nearest(cut2);
  return `${name} 1: ${value(cut, best)} · ${name} 2: ${best2 < 0 ? "empty" : value(cut2, best2)} ${place}`;
}

/** Draw the cuts through the cursors: the rows above the map (along x), the columns beside it
 *  (along y), on exactly the map's axes, in the cursors' colours when there are two. Their value
 *  axis, shared by both, fits the part in view. */
function paintCuts(top: HTMLCanvasElement | null, right: HTMLCanvasElement | null, m: Mapping, r: CursorsAnswer | null) {
  const dpr = window.devicePixelRatio || 1;
  const draw = (c: HTMLCanvasElement | null, cut: Cut | undefined, cut2: Cut | undefined, along: "x" | "y") => {
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
    const ends = [cut, ...(cut2 ? [cut2] : [])].flatMap((k) => k.range).filter((v): v is number => v !== null);
    if (!ends.length) return;
    let [lo, hi] = [Math.min(...ends), Math.max(...ends)];
    if (lo === hi) [lo, hi] = [lo - 0.5, hi + 0.5];
    const pad = (hi - lo) * 0.08;
    const span = along === "x" ? h : w;
    const valPx = (v: number) => 3 + ((v - (lo! - pad)) / (hi! - lo! + 2 * pad)) * (span - 6);
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, w, h);
    ctx.clip();
    const curve = (k: Cut, colour: string) => {
      ctx.strokeStyle = colour;
      ctx.lineWidth = 1.25;
      ctx.beginPath();
      let pen = false;
      k.pos.forEach((p, i) => {
        const z = k.z[i];
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
    };
    curve(cut, cut2 ? CURSOR_COLORS[0] : ink);
    if (cut2) curve(cut2, CURSOR_COLORS[1]);
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
  draw(top, r?.cuts?.row, r?.cuts2?.row, "x");
  draw(right, r?.cuts?.column, r?.cuts2?.column, "y");
}

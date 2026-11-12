import { CSSProperties, DragEvent, KeyboardEvent, MouseEvent, MutableRefObject, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useResizable } from "./resizable";
import NumberRange from "./NumberRange";
import { api, CursorRead, CursorsAnswer, ExploreFrameMeta, ExploreOpen, FileInfo, OpsInfo, PlotSpec, ReduceStat, SyncKeys, ValueInfo } from "./api";
import Operations from "./Operations";
import Contrast from "./Contrast";
import CursorPanel, { OtherPanel } from "./CursorPanel";
import { kindOf } from "./plotKinds";
import { PlotKindSelect } from "./PlotKindSelect";
import { CursorsState, NO_CURSORS } from "./cursors";
import ExploreView, { Angle, ExploreActions, Follow, View, ViewSettings } from "./ExploreView";
import ExportDialog, { ExportSource } from "./ExportDialog";
import { around, compose, copyPng, pageBackground, pictureChoice, rememberPictureChoice, savePng } from "./clipboard";
import type { MenuEntry } from "./menu";
import AxisSelect from "./AxisSelect";
import { COMPLEX_MODES, FileDetails, SliceControl } from "./FileView";
import { Segmented } from "./settingsUi";
import { Icon } from "./icons";
import { middle } from "./labelText";
import { copyPath } from "./fileActions";
import { useDiskVersion } from "./watch";
import { ContextMenu, MenuAt, menuAt } from "./menu";
import { useToast } from "./toast";
import { MeasuringStatus } from "./MeasuringStatus";

/**
 * One file in the Explore workspace: its header, what to plot (values, kind, axes, slices,
 * complex mode), how to show it (chosen traces, colours, scales) and the interactive view.
 *
 * Explore never writes into the file. What it shows is remembered in LBD's database instead, per
 * file: reopening the file shows the same again. Without a remembered view it starts from the
 * file's saved figure settings for what to plot (they describe the data).
 *
 * When the file changes on disk and only grew (the same axes and values, more data), the view
 * stays as it is (cursors included); anything else starts afresh, with a note saying why.
 *
 * "Use as Library picture" (the header's ⋯ menu) draws the panels as shown once, on the server, as
 * the file's picture in the Library; only the picture is kept, so later changes here don't change it.
 */

interface Props {
  path: string;
  onOpenInFigure: (spec?: PlotSpec) => void; // `spec`: what a plot type of its own shows
  onError: (msg: string) => void;
  onMenu?: (e: MouseEvent) => void;
  /** The file's title, once read (its tab shows it). */
  onTitle?: (title: string) => void;
}

/** One panel's plot, as remembered. */
export interface PanelState {
  /** Stable while the panel exists (React key, sync and cursor bookkeeping). */
  id: string;
  spec: PlotSpec;
  settings: ViewSettings;
  stat: ReduceStat;
  view: View | null;
  cursors: CursorsState;
  /** The list of traces / rows unfolded (undefined: folded while all are shown). */
  listOpen?: boolean;
  /** After "row / column as curve": the map to go back to. */
  back?: PlotSpec;
}

/** What is remembered for a file (LBD's database, never the file; catalog.py `upgrade`): its
 * panels, which one is active, the layout and what is synchronized. The server upgrades older
 * records (one plot) to this shape. */
export interface Remembered {
  version: 2;
  panels: PanelState[];
  active: number;
  layout: "side" | "stacked";
  sync: { x: boolean; y: boolean; sliders: boolean; cursors: boolean };
}

/** At most this many panels (each is a plot drawn by the server); a new file opens with up to FIRST_PANELS. */
export const MAX_PANELS = 6;
const FIRST_PANELS = 4;
// Drag and drop: a value from the side bar, a panel by its title bar.
const DRAG_VALUE = "application/x-lbd-value";
const DRAG_PANEL = "application/x-lbd-panel";

const newId = () => Math.random().toString(36).slice(2, 10);
// A new panel: a map with a slider takes its colours from every slice (plan 11); panels remembered
// from before (no `crange`) keep their slice's range.
const freshPanel = (spec: PlotSpec): PanelState => ({ id: newId(), spec, settings: { crange: "all" }, stat: "max", view: null, cursors: NO_CURSORS });

/** A file opened for the first time: panel 1 from the file's saved figure view, then one panel
 * per other value with axes (up to FIRST_PANELS), like Labber's panels for its log channels. */
function fresh(info: FileInfo): Remembered {
  const first = startSpec(info);
  const names = info.values.filter((v) => v.shape.length > 0).map((v) => v.name);
  if (names.length > 1 && !first.values) first.values = [names[0]];
  const inFirst = first.values ?? names.slice(0, 1); // the server's default: the first value with axes
  const rest = names.filter((name) => !inFirst.includes(name)).slice(0, FIRST_PANELS - 1);
  return {
    version: 2,
    panels: [freshPanel(first), ...rest.map((name) => freshPanel({ values: [name] }))],
    active: 0,
    layout: "side",
    sync: { x: true, y: false, sliders: true, cursors: true },
  };
}

/** Rows and columns of the panel grid. */
function gridOf(n: number, layout: Remembered["layout"]): [number, number] {
  if (n <= 1) return [1, 1];
  if (n <= 3) return layout === "side" ? [1, n] : [n, 1];
  if (n === 4) return [2, 2];
  return layout === "side" ? [2, 3] : [3, 2];
}

/** What a panel's view reports while it is open (not remembered). */
interface Live {
  resolved: ExploreOpen | null;
  reading: CursorsAnswer | null;
  opsInfo: OpsInfo | null;
  /** With the last picture: what it must share with another panel to follow its zoom, and where its data is. */
  sync: (SyncKeys & { full: [[number, number], [number, number]] }) | null;
  /** The panel couldn't open its plot: why (the controls say so instead of "Opening…"). */
  failed?: string | null;
  /** A map with a slider: where its colours come from, and how far every slice's range is. */
  crange?: ExploreFrameMeta["crange"];
}
const NO_LIVE: Live = { resolved: null, reading: null, opsInfo: null, sync: null, failed: null };

/** Two ranges together. */
const union = (a: [number, number], b: [number, number]): [number, number] => [Math.min(a[0], b[0]), Math.max(a[1], b[1])];

/** A remembered panel with the keys a later LBD added filled in. */
function filledPanel(st: Partial<PanelState>): PanelState {
  return {
    id: st.id ?? newId(),
    spec: st.spec ?? {},
    settings: st.settings ?? {},
    stat: st.stat ?? "max",
    view: st.view ?? null,
    cursors: { ...NO_CURSORS, ...(st.cursors ?? {}) },
    ...(st.listOpen !== undefined ? { listOpen: st.listOpen } : {}),
    ...(st.back ? { back: st.back } : {}),
  };
}

const START_KEYS = ["values", "complex", "x", "y", "series", "index", "kind"] as const;
const CMAPS = ["viridis", "plasma", "magma", "cividis", "gray", "RdBu", "twilight"];
// Plot settings after which earlier chosen traces (and cursor positions) no longer mean the same.
const RESETS_SELECTION = ["kind", "values", "x", "y", "series"];

/** What to plot first: the parts of the file's saved figure view that describe the data. */
function startSpec(info: FileInfo): PlotSpec {
  const out: PlotSpec = {};
  const saved = info.plot ?? {};
  for (const k of START_KEYS) if (saved[k] !== undefined) (out as Record<string, unknown>)[k] = saved[k];
  if (out.kind === "auto" || !kindOf(out.kind).explore) delete out.kind; // the types Explore shows
  if (out.complex === "iq" && out.kind !== "scatter") delete out.complex;
  return out;
}

/** What Open in Figure takes along: a plot type of its own and its choices (curves and maps: the file's view). */
function figureSpec(opened: ExploreOpen | null, view?: View | null): PlotSpec | undefined {
  if (!opened || opened.kind === "curve" || opened.kind === "heatmap") return undefined;
  const { kind, values, complex, x, y, series, index, options } = opened.spec;
  const angle = view?.angle as Angle | undefined; // a 3D plot's angle: in a figure, a setting
  return { kind: opened.kind ?? kind, values, complex, x, y, series, index, options: angle ? { ...options, elev: angle.elev, azim: angle.azim, zoom: angle.zoom } : options };
}

/** A file's shape, to tell data added (same names and axes, longer) from a different file. */
function grewOnly(before: FileInfo, now: FileInfo): boolean {
  const axes = new Map(now.axes.map((a) => [a.name, a.length]));
  if (before.axes.some((a) => !axes.has(a.name) || axes.get(a.name)! < a.length)) return false;
  const values = new Map(now.values.map((v) => [v.name, v]));
  return before.values.every((v) => values.get(v.name)?.axes.join() === v.axes.join() && values.get(v.name)?.dtype === v.dtype);
}

export default function ExploreTab({ path, onOpenInFigure, onError, onMenu, onTitle }: Props) {
  const [info, setInfo] = useState<FileInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [choosing, setChoosing] = useState(false); // drawing the Library preview
  const toast = useToast();
  const [updating, setUpdating] = useState<string | null>(null);
  const [rec, setRec] = useState<Remembered | null>(null); // what the view shows (remembered)
  // What each panel's view reports while it is open (not remembered), by panel id.
  const [live, setLiveMap] = useState<Record<string, Live>>({});
  const liveRef = useRef(live);
  liveRef.current = live;
  const infoRef = useRef(info);
  infoRef.current = info;
  const setLive = useCallback((id: string, patch: Partial<Live>) => setLiveMap((m) => ({ ...m, [id]: { ...(m[id] ?? NO_LIVE), ...patch } })), []);
  // Zoom pushed to panels that follow another (synchronized axes), by panel id.
  const [follows, setFollows] = useState<Record<string, Follow>>({});
  const followSeq = useRef(0);
  const [viewKey, setViewKey] = useState(0); // a new one starts every panel's view afresh
  const [panelKeys, setPanelKeys] = useState<Record<string, number>>({}); // … or one panel's
  const restart = useCallback((id: string) => setPanelKeys((k) => ({ ...k, [id]: (k[id] ?? 0) + 1 })), []);
  const actionRefs = useRef<Record<string, MutableRefObject<ExploreActions | null>>>({});
  const actionsOf = (id: string) => (actionRefs.current[id] ??= { current: null });
  const [exporting, setExporting] = useState<ExportSource[] | null>(null); // Save as CSV open: panel asked, then the others
  const [wholeCsv, setWholeCsv] = useState(false); // Save the whole file as CSV open
  const [picture, setPicture] = useState(pictureChoice); // Copy picture: what, and which panels
  const setPictureChoice = (c: typeof picture) => {
    setPicture(c);
    rememberPictureChoice(c);
  };
  /** The picture of panel `id` (or all panels, as laid out), from what is on screen now. */
  const pictureOf = (id: string): HTMLCanvasElement | null => {
    const ids = picture.all && rec ? rec.panels.map((q) => q.id) : [id];
    const shots = ids.map((i) => actionsOf(i).current?.snapshot(picture.what) ?? null).filter((x) => !!x);
    if (!shots.length) return null;
    const areas = shots.map((s) => s!.area);
    return compose(shots.flatMap((s) => s!.canvases), around(areas), pageBackground(areas[0]));
  };
  const copyPicture = async (id: string) => {
    const c = pictureOf(id);
    if (!c) return onError("The plot isn't drawn yet.");
    try {
      await copyPng(c);
      toast("Picture copied: paste it into slides, a chat or your notes.");
    } catch (e) {
      onError(`${(e as Error).message}.`);
    }
  };
  const dataItems = (id: string): MenuEntry[] => {
    const several = (rec?.panels.length ?? 0) > 1;
    const mark = (on: boolean) => (on ? "● " : "○ ");
    return [
      {
        label: "Save as CSV…",
        onClick: () => {
          const ids = [id, ...(rec?.panels ?? []).filter((q) => q.id !== id).map((q) => q.id)];
          const number = (i: string) => (rec?.panels ?? []).findIndex((q) => q.id === i) + 1;
          const sources = ids.map((i): ExportSource | null => {
            const s = actionsOf(i).current?.exportSource() ?? null;
            return s && { ...s, name: `Panel ${number(i)}` };
          });
          if (!sources[0]) return onError("The plot isn't open yet.");
          setExporting(sources.filter((x): x is ExportSource => !!x));
        },
      },
      "-",
      { label: picture.all && several ? "Copy picture of all panels" : "Copy picture", onClick: () => void copyPicture(id) },
      {
        label: "Save picture as PNG…",
        onClick: () => {
          const c = pictureOf(id);
          if (!c) return onError("The plot isn't drawn yet.");
          const name = `${infoRef.current?.name.replace(/\.lbd$/i, "") ?? "picture"}.png`;
          savePng(c, path, name)
            .then((saved) => saved && toast(`Saved ${saved}`, "info"))
            .catch((e) => onError((e as Error).message));
        },
      },
      { label: mark(picture.what === "screen") + "Picture as on screen (cursors, cuts)", onClick: () => setPictureChoice({ ...picture, what: "screen" }) },
      { label: mark(picture.what === "plot") + "Picture of the plot only", onClick: () => setPictureChoice({ ...picture, what: "plot" }) },
      ...(several
        ? ([
            { label: mark(!picture.all) + "Picture of this panel", onClick: () => setPictureChoice({ ...picture, all: false }) },
            { label: mark(picture.all) + "Picture of all panels", onClick: () => setPictureChoice({ ...picture, all: true }) },
          ] as MenuEntry[])
        : []),
    ];
  };
  const disk = useDiskVersion("file", path);
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;
  const failingSince = useRef<number | null>(null);

  // First: the file's description and what LBD remembers for it.
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const [i, r] = await Promise.all([api.file(path), api.remembered(path)]);
        if (!live) return;
        setInfo(i);
        onTitle?.(i.title || i.name);
        if (r.note) onErrorRef.current(r.note);
        // a remembered view (upgraded by the server; panels may lack later keys), else a start from the file
        const st = r.state as unknown as Remembered | null;
        setRec(
          st?.panels?.length
            ? { ...st, panels: st.panels.map(filledPanel), active: Math.min(st.active ?? 0, st.panels.length - 1) }
            : fresh(i),
        );
      } catch (e) {
        if (live) setLoadError((e as Error).message);
      }
    })();
    return () => {
      live = false;
    };
  }, [path]);

  // The file changed on disk: read its description again. Data only added: keep the view;
  // otherwise start afresh and say why. A file still being written is tried again for 10 s.
  useEffect(() => {
    if (!info || typeof disk.version !== "string" || disk.version === info.version) return;
    let live = true;
    api
      .file(path)
      .then((now) => {
        if (!live) return;
        failingSince.current = null;
        setUpdating(null);
        if (!grewOnly(info, now)) {
          onErrorRef.current(`${now.name} was rewritten with other contents, so its Explore view starts afresh.`);
          setRec(fresh(now));
          setViewKey((k) => k + 1);
        }
        setInfo(now);
      })
      .catch((e) => {
        if (!live) return;
        failingSince.current ??= Date.now();
        if (Date.now() - failingSince.current > 10_000) setUpdating(`Can't read the new version: ${(e as Error).message}`);
        else setUpdating("Updating…");
      });
    return () => {
      live = false;
    };
  }, [disk.version, info, path]);

  // Remember what is shown, a moment after the last change (and when the tab closes).
  const recRef = useRef(rec);
  recRef.current = rec;
  useEffect(() => {
    if (!rec) return;
    const t = window.setTimeout(() => api.remember(path, rec).catch(() => undefined), 1000);
    return () => window.clearTimeout(t);
  }, [rec, path]);
  useEffect(
    () => () => {
      if (recRef.current) api.remember(path, recRef.current).catch(() => undefined);
    },
    [path],
  );

  /** Change one panel (by id); the same object back means no change (nothing to remember). */
  const updatePanel = useCallback(
    (id: string, f: (p: PanelState) => PanelState) =>
      setRec((r) => {
        if (!r) return r;
        let changed = false;
        const panels = r.panels.map((p) => {
          if (p.id !== id) return p;
          const q = f(p);
          changed ||= q !== p;
          return q;
        });
        return changed ? { ...r, panels } : r;
      }),
    [],
  );

  /** With the cursors synchronized, they are shared: the active panel leads, and the panels with
   * the same x get its cursors' x (type, on, which is active); each keeps its own y or trace and
   * snaps the cursor to its own data. What the others report back changes only themselves. */
  const sharedKey = useRef("");
  const shareCursors = useCallback((id: string, c: CursorsState) => {
    const r = recRef.current, me = liveRef.current[id]?.sync;
    if (!r || r.panels.length < 2 || !r.sync.cursors || r.panels[r.active]?.id !== id || !me) return;
    const key = JSON.stringify({ id, type: c.type, on: c.on, active: c.active, xs: c.at.map((a) => a.x), ys: c.at.map((a) => a.y) });
    if (key === sharedKey.current) return;
    sharedKey.current = key;
    setRec((rr) => {
      if (!rr) return rr;
      let changed = false;
      const panels = rr.panels.map((q) => {
        const theirs = liveRef.current[q.id];
        if (q.id === id || theirs?.sync?.x !== me.x) return q;
        const own = q.cursors.at, curve = theirs.resolved?.kind !== "heatmap";
        const mid = q.view ? (q.view.ylim[0] + q.view.ylim[1]) / 2 : 0;
        // maps on the same vertical axis too (two values of one file): the same row as the leader
        const sameRow = !curve && liveRef.current[id]?.resolved?.kind === "heatmap" && !!theirs.sync?.y && theirs.sync.y === me.y;
        const at = c.at.map((a, k) => {
          const trace = own[k]?.trace ?? (curve ? 0 : undefined); // curves: on a trace, so the x is kept
          return { x: a.x, y: sameRow ? a.y : own[k]?.y ?? mid, ...(trace !== undefined ? { trace } : {}) };
        });
        changed = true;
        return { ...q, cursors: { ...q.cursors, type: c.type, on: c.on, active: c.active, at } };
      });
      return changed ? { ...rr, panels } : rr;
    });
  }, []);

  /** The other panels' sliders for the axes in `moved` go to the same positions as panel `id`'s. */
  const syncSliders = useCallback((id: string, moved: Record<string, number>) =>
          setRec((r) => {
            if (!r) return r;
            let changed = false;
            const panels = r.panels.map((q) => {
              // its sliders; until its plot is open, its values' axes (an index for a drawn axis is ignored)
              const opened = liveRef.current[q.id]?.resolved;
              const sliced = new Set(
                opened
                  ? (opened.spec.slices ?? []).map((sl) => sl.axis)
                  : (q.spec.values ?? []).flatMap((name) => infoRef.current?.values.find((v) => v.name === name)?.axes ?? []),
              );
              const same = Object.entries(moved).filter(([a, i]) => q.id !== id && sliced.has(a) && q.spec.index?.[a] !== i);
              if (!same.length) return q;
              changed = true;
              return { ...q, spec: { ...q.spec, index: { ...(q.spec.index ?? {}), ...Object.fromEntries(same) } } };
            });
            return changed ? { ...r, panels } : r;
          }),
  [],
  );

  /** What a panel's controls and view change in it. */
  const panelApi = useCallback(
    (id: string) => {
      const updateSpec = (patch: PlotSpec) => {
        updatePanel(id, (s) => {
          const reset = RESETS_SELECTION.some((k) => k in patch);
          return {
            ...s,
            spec: { ...s.spec, ...patch },
            settings: reset ? { ...s.settings, select: undefined } : s.settings,
            cursors: reset ? { ...s.cursors, at: [], active: 0 } : s.cursors,
            back: reset ? undefined : s.back,
          };
        });
        // Synchronized sliders: the same position in every panel with a slider for that axis.
        const moved = patch.index;
        if (moved && recRef.current?.sync.sliders && recRef.current.panels.length > 1) syncSliders(id, moved);
      };
      return {
        updateSpec,
        updateSettings: (patch: ViewSettings) => updatePanel(id, (s) => ({ ...s, settings: { ...s.settings, ...patch } })),
        onCursors: (cursors: CursorsState) => {
          updatePanel(id, (s) => ({ ...s, cursors }));
          shareCursors(id, cursors);
        },
        onView: (view: View) => updatePanel(id, (s) => (JSON.stringify(s.view) !== JSON.stringify(view) ? { ...s, view } : s)),
        onStat: (stat: ReduceStat) => updatePanel(id, (s) => ({ ...s, stat })),
        onListOpen: (listOpen: boolean) => updatePanel(id, (s) => ({ ...s, listOpen })),
        // Keys [ and ]: the first slider one step.
        onStepSlider: (by: number) => {
          const r = liveRef.current[id]?.resolved?.spec, sl = r?.slices?.[0];
          if (!r || !sl) return;
          const i = Math.min(Math.max(sl.index + by, 0), sl.length - 1);
          if (i !== sl.index) updateSpec({ index: { ...(r.index ?? {}), [sl.axis]: i } });
        },
        // A map's row or column through cursor 1, as a curve in this panel (the map is kept to go back to).
        onShowCut: (which: "row" | "column", cursor: CursorRead) => {
          const r = liveRef.current[id]?.resolved?.spec;
          if (!r?.x || !r.y) return;
          const fixed = which === "row" ? r.y : r.x;
          // a variable sweep's map: the curve on its real axes through that step or place (16.10)
          const along = cursor.curves?.[which];
          if (r.levels && !along) return;
          const shown = along
            ? { x: along.x, index: { ...(r.index ?? {}), ...along.index } }
            : { x: which === "row" ? r.x : r.y, index: { ...(r.index ?? {}), [fixed]: cursor.index[fixed] } };
          updatePanel(id, (s) => ({
            ...s,
            back: s.spec,
            spec: { ...s.spec, kind: "curve", ...shown, y: undefined, series: "none" },
            settings: { ...s.settings, select: undefined },
            cursors: { ...s.cursors, at: [], active: 0 },
            view: null,
          }));
          restart(id);
        },
        onBack: () => {
          updatePanel(id, (s) => (s.back ? { ...s, spec: s.back, back: undefined, cursors: { ...s.cursors, at: [], active: 0 }, view: null } : s));
          restart(id);
        },
      };
    },
    [updatePanel, restart, shareCursors, syncSliders],
  );

  // ---- the panels: add, remove, duplicate, reorder, make active

  const setActive = useCallback((i: number) => setRec((r) => (r && r.active !== i && i < r.panels.length ? { ...r, active: i } : r)), []);
  const addPanel = useCallback(
    (spec: PlotSpec) =>
      setRec((r) => (r && r.panels.length < MAX_PANELS ? { ...r, panels: [...r.panels, freshPanel(spec)], active: r.panels.length } : r)),
    [],
  );
  const removePanel = useCallback(
    (i: number) =>
      setRec((r) => {
        if (!r || r.panels.length <= 1) return r;
        const active = r.active > i ? r.active - 1 : Math.min(r.active, r.panels.length - 2);
        return { ...r, panels: r.panels.filter((_, k) => k !== i), active };
      }),
    [],
  );
  const duplicatePanel = useCallback(
    (i: number) =>
      setRec((r) => {
        if (!r || r.panels.length >= MAX_PANELS) return r;
        const copy = { ...r.panels[i], id: newId() };
        return { ...r, panels: [...r.panels.slice(0, i + 1), copy, ...r.panels.slice(i + 1)], active: i + 1 };
      }),
    [],
  );
  const movePanel = useCallback(
    (from: number, to: number) =>
      setRec((r) => {
        if (!r || from === to) return r;
        const activeId = r.panels[r.active].id;
        const panels = [...r.panels];
        const [p] = panels.splice(from, 1);
        panels.splice(to, 0, p);
        return { ...r, panels, active: panels.findIndex((q) => q.id === activeId) };
      }),
    [],
  );
  /** A value added to panel i (curves: drawn with the others; maps: shown instead). */
  const valueToPanel = useCallback(
    (name: string, i: number) => {
      const r = recRef.current, p = r?.panels[i];
      if (!p) return;
      const kind = liveRef.current[p.id]?.resolved?.kind;
      const values = liveRef.current[p.id]?.resolved?.spec.values ?? p.spec.values ?? [];
      if (values.includes(name)) return;
      panelApi(p.id).updateSpec(kind === "heatmap" || kind === "matrix" ? { values: [name], x: undefined, y: undefined } : { values: [...values, name] });
      setActive(i);
    },
    [panelApi, setActive],
  );
  const [menu, setMenu] = useState<MenuAt | null>(null);
  // the controls drawer (narrow windows) and the inspector (its tab remembered in this browser)
  const [ctlOpen, setCtlOpen] = useState(false);
  const [inspTab, setInspTabState] = useState<InspectorTab>(() => {
    try {
      const t = localStorage.getItem(INSPECTOR_KEY) as InspectorTab | null;
      return t && INSPECTOR_TABS.some(([x]) => x === t) ? t : "cursors";
    } catch {
      return "cursors";
    }
  });
  const setInspTab = (t: InspectorTab) => {
    setInspTabState(t);
    try {
      localStorage.setItem(INSPECTOR_KEY, t);
    } catch {
      /* not remembered */
    }
  };
  // The controls column and the inspector (right, or a strip below) are resized at their inner
  // edge; double-click goes back to the default (the size the layout gives, from styles.css).
  const bodyRef = useRef<HTMLDivElement>(null);
  const sizeOf = (sel: string, tall = false) => () => {
    const r = bodyRef.current?.querySelector<HTMLElement>(sel)?.getBoundingClientRect();
    return r ? (tall ? r.height : r.width) : tall ? 190 : 260;
  };
  const ctlSize = useResizable({ key: "lbd-explore-ctl-w", initial: sizeOf(".explore-controls"), min: 200, maxShare: 0.4,
                                 maxOfContainer: true, side: "left", container: bodyRef, resetOnDoubleClick: true });
  const inspWidth = useResizable({ key: "lbd-explore-insp-w", initial: sizeOf(".explore-inspector"), min: 220, maxShare: 0.45,
                                   maxOfContainer: true, side: "right", container: bodyRef, resetOnDoubleClick: true });
  const inspHeight = useResizable({ key: "lbd-explore-insp-h", initial: sizeOf(".explore-inspector .inspector-body", true), min: 100,
                                    maxShare: 0.6, maxOfContainer: true, side: "bottom", container: bodyRef, resetOnDoubleClick: true });
  const bodySizes = {
    ...(ctlSize.chosen ? { "--ctl-w": `${ctlSize.width}px` } : {}),
    ...(inspWidth.chosen ? { "--insp-w": `${inspWidth.width}px` } : {}),
    ...(inspHeight.chosen ? { "--insp-h": `${inspHeight.width}px` } : {}),
  } as CSSProperties;
  // narrow windows: the inspector strip unfolded (remembered in this browser)
  const [inspOpen, setInspOpenState] = useState(() => {
    try {
      return localStorage.getItem(INSPECTOR_KEY + "-open") === "yes";
    } catch {
      return false;
    }
  });
  const setInspOpen = (v: boolean | ((o: boolean) => boolean)) =>
    setInspOpenState((o) => {
      const next = typeof v === "function" ? v(o) : v;
      try {
        localStorage.setItem(INSPECTOR_KEY + "-open", next ? "yes" : "no");
      } catch {
        /* not remembered */
      }
      return next;
    });
  // the panels' width: side by side panels narrower than 450 px are stacked instead
  const gridRef = useRef<HTMLDivElement>(null);
  const [gridWidth, setGridWidth] = useState(0);
  useEffect(() => {
    const el = gridRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setGridWidth(el.clientWidth));
    ro.observe(el);
    setGridWidth(el.clientWidth);
    return () => ro.disconnect();
  });

  /** Panel `id`'s view changed by the user: the panels that share its x (and y, if synchronized)
   * follow. Showing everything shows all the data of the panels that follow each other. */
  const onUserView = useCallback((id: string, v: View | null) => {
    const r = recRef.current, me = liveRef.current[id]?.sync;
    if (!r || r.panels.length < 2 || !me || (!r.sync.x && !r.sync.y)) return;
    const others = r.panels.filter((q) => q.id !== id);
    const sameX = (q: PanelState) => r.sync.x && liveRef.current[q.id]?.sync?.x === me.x;
    const sameY = (q: PanelState) => r.sync.y && liveRef.current[q.id]?.sync?.y === me.y;
    const groupFull = (same: (q: PanelState) => boolean, k: 0 | 1) =>
      others.filter(same).reduce<[number, number]>((acc, q) => union(acc, liveRef.current[q.id]!.sync!.full[k]), me.full[k]);
    const next: Record<string, Follow> = {};
    for (const q of r.panels) {
      const f: Follow = { seq: ++followSeq.current, ...(v ? {} : { all: true }) };
      if (v) {
        if (q.id === id) continue;
        if (sameX(q)) f.xlim = v.xlim;
        if (sameY(q)) f.ylim = v.ylim;
      } else {
        // everything: the data of every panel that follows this one (this one included)
        if (q.id === id || sameX(q)) f.xlim = r.sync.x ? groupFull(sameX, 0) : undefined;
        if (q.id === id || sameY(q)) f.ylim = r.sync.y ? groupFull(sameY, 1) : undefined;
      }
      if (f.xlim || f.ylim) next[q.id] = f;
    }
    if (Object.keys(next).length) setFollows((old) => ({ ...old, ...next }));
  }, []);

  /** Turn a sync on or off; turned on, the other panels line up with the active one at once
   * (not only from the next zoom, slider move or click). */
  const toggleSync = (k: keyof Remembered["sync"]) => {
    const r = recRef.current;
    if (!r) return;
    const on = !r.sync[k];
    setRec((rr) => rr && { ...rr, sync: { ...rr.sync, [k]: on } });
    const act = r.panels[r.active];
    if (!on || !act) return;
    window.setTimeout(() => {                         // after the new setting is in recRef
      if (k === "x" || k === "y") onUserView(act.id, act.view);
      else if (k === "sliders") syncSliders(act.id, act.spec.index ?? {});
      else {
        sharedKey.current = "";
        shareCursors(act.id, act.cursors);
      }
    }, 0);
  };

  const chooseAsPreview = async () => {
    if (!rec) return;
    setChoosing(true);
    try {
      const panels = rec.panels.map((p) => ({ spec: p.spec, settings: p.settings, stat: p.stat, view: p.view }));
      const answer = await api.libraryPreviewChoose(path, panels, gridOf(rec.panels.length, rec.layout), null);
      toast("Library picture updated: the Library now shows these panels for this file.");
      for (const w of answer.warnings) toast(w, "warning");
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setChoosing(false);
    }
  };

  /** Start afresh; the view before can come back (Undo) while the toast shows. */
  const forget = async () => {
    if (!info || !rec) return;
    const before = rec;
    await api.forget(path).catch((e) => onError((e as Error).message));
    setRec(fresh(info));
    setViewKey((k) => k + 1);
    toast("This file's view is forgotten: it starts afresh.", "info", {
      label: "Undo",
      onClick: () => {
        setRec(before);
        setViewKey((k) => k + 1);
      },
    });
  };

  if (loadError) {
    // A file that can't be read: a plain sentence and what can be done; the details folded.
    const damaged = /truncated|eof|signature|unable to (synchronously )?open|not an hdf5|can't read/i.test(loadError);
    return (
      <div className="file-view explore-tab explore-failed">
        <div className="error-box">
          <strong>{damaged ? "This file is damaged or incomplete (it may end early)." : "Explore can't open this file."}</strong>
          <div className="error-actions">
            <button onClick={() => api.reveal(path).catch((e) => onError(e.message))}>Show in folder</button>
          </div>
          <details>
            <summary>Details</summary>
            <p className="small mono">{loadError}</p>
          </details>
        </div>
      </div>
    );
  }
  if (!info || !rec) return <div className="file-view muted pad">Loading…</div>;
  const plottable = info.values.filter((v) => v.shape.length > 0);
  const n = rec.panels.length;
  const several = n > 1;
  const act = rec.panels[rec.active] ?? rec.panels[0];
  const actLive = live[act.id] ?? NO_LIVE;
  // curves and maps start from the file's own figure; another plot type goes with its choices
  const openFigure = () => {
    const r = actLive.resolved;
    if (!r || r.kind === "curve" || r.kind === "heatmap") return onOpenInFigure();
    onOpenInFigure({ ...figureSpec(r, act.view), color: r.spec.color, all: r.spec.all, y_scale: act.settings.yscale ?? r.spec.y_scale });
  };
  const actApi = panelApi(act.id);
  const actActions = actionsOf(act.id);
  const resolved = actLive.resolved;
  // side by side would make each panel too narrow here: stacked, for this size only
  const tooNarrow = several && rec.layout === "side" && gridWidth > 0 && gridWidth / gridOf(n, "side")[1] < 450;
  const [rows, cols] = gridOf(n, tooNarrow ? "stacked" : rec.layout);
  const byName = new Map(info.values.map((v) => [v.name, v]));
  const titleOf = (p: PanelState) =>
    (live[p.id]?.resolved?.spec.values ?? p.spec.values ?? [plottable[0]?.name ?? ""])
      .map((name) => {
        const v = byName.get(name);
        return v ? `${v.label || v.name}${v.unit ? ` (${unitText(v.unit)})` : ""}` : name;
      })
      .join(", ");
  const full = n >= MAX_PANELS;
  // The other panels at the same x as the active one (their read-outs at the shared cursor).
  const othersAtX: OtherPanel[] = rec.panels
    .map((p, i) => ({ p, i }))
    .filter(({ p }) => p.id !== act.id && live[p.id]?.sync && live[p.id]?.sync?.x === live[act.id]?.sync?.x)
    .map(({ p, i }) => ({ n: i + 1, title: titleOf(p), reading: live[p.id]?.reading ?? null }));
  /** Why panel p doesn't follow the active panel's zoom, if it doesn't. */
  const notSynced = (p: PanelState): string | null => {
    const mine = live[p.id]?.sync?.x, theirs = live[act.id]?.sync?.x;
    return mine !== undefined && theirs !== undefined && mine !== theirs ? `x not synced: ${mine || "?"}, not ${theirs || "?"}` : null;
  };
  const addMenu = (e: MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setMenu({
      x: r.left,
      y: r.bottom,
      items: plottable.map((v) => ({
        label: `${v.label || v.name}${v.unit ? ` (${unitText(v.unit)})` : ""}`,
        disabled: full,
        onClick: () => addPanel({ values: [v.name] }),
      })),
    });
  };
  const panelEntries = (i: number): MenuEntry[] => [
    { label: "Duplicate panel", onClick: () => duplicatePanel(i), disabled: full },
    { label: "Remove panel", onClick: () => removePanel(i), disabled: n <= 1, danger: true },
  ];
  const panelMenu = (e: MouseEvent, i: number) => {
    e.preventDefault();
    setMenu(menuAt(e, panelEntries(i)));
  };
  const valueMenu = (e: MouseEvent, name: string) => {
    e.preventDefault();
    setMenu(
      menuAt(e, [
        { label: "Show in a new panel", onClick: () => addPanel({ values: [name] }), disabled: full },
        { label: "Show only this value here", onClick: () => actApi.updateSpec({ values: [name], x: undefined, y: undefined, series: undefined }) },
      ]),
    );
  };
  const headMenu = (e: MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setMenu({
      x: r.right - 240,
      y: r.bottom,
      items: [
        { label: choosing ? "Drawing the Library picture…" : "Use as Library picture", disabled: choosing, onClick: () => void chooseAsPreview() },
        { label: "Copy path", onClick: () => void copyPath(info.path, toast) },
        { label: "Save the whole file as CSV…", onClick: () => setWholeCsv(true) },
        "-",
        { label: "Forget this view…", onClick: () => void forget() },
      ],
    });
  };
  // Keys 1–6 make a panel active (when no box has the focus).
  const onKeyDown = (e: KeyboardEvent) => {
    const t = e.target as HTMLElement;
    if (!several || /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
    const k = Number(e.key);
    if (Number.isInteger(k) && k >= 1 && k <= n) {
      setActive(k - 1);
      (document.querySelectorAll(`[data-panel-index="${k - 1}"] .explore-overlay`)[0] as HTMLElement | undefined)?.focus();
      e.preventDefault();
    }
  };
  const dropOn = (e: DragEvent, i: number | null) => {
    const value = e.dataTransfer.getData(DRAG_VALUE), from = e.dataTransfer.getData(DRAG_PANEL);
    if (!value && from === "") return;
    e.preventDefault();
    if (value) {
      if (i === null) addPanel({ values: [value] });
      else valueToPanel(value, i);
    } else if (i !== null) movePanel(Number(from), i);
  };
  const allowDrop = (e: DragEvent) => {
    if (e.dataTransfer.types.includes(DRAG_VALUE) || e.dataTransfer.types.includes(DRAG_PANEL)) e.preventDefault();
  };
  const cursorPanel = resolved && (
    <CursorPanel
      kind={resolved.kind}
      noCutOut={resolved.spec.levels ? (actLive.reading?.cursors[0]?.cuts_why ?? "") : ""}
      cursors={act.cursors}
      onCursors={actApi.onCursors}
      reading={actLive.reading}
      actions={actActions}
      onBack={act.back ? actApi.onBack : null}
      others={rec.sync.cursors ? othersAtX : []}
      file={{ path: info.path, name: info.name, id: info.id }}
      onSaveCut={(which) => {
        // the active panel's cut first, then the other panels' (the dialog says which can join)
        const ids = [act.id, ...rec.panels.filter((q) => q.id !== act.id).map((q) => q.id)];
        const sources = ids.map((i): ExportSource | null => {
          const s = actionsOf(i).current?.cutSource(which) ?? null;
          return s && { ...s, name: `Panel ${rec.panels.findIndex((q) => q.id === i) + 1}` };
        });
        if (!sources[0]) return onError("Place cursor 1 first.");
        setExporting(sources.filter((x): x is ExportSource => !!x));
      }}
    />
  );
  const showInspector = (t: InspectorTab) => {
    setInspTab(t);
    setInspOpen(true);
  };

  return (
    <div className={"explore-tab" + (ctlOpen ? " controls-open" : "") + (inspOpen ? " inspector-open" : "")} onKeyDown={onKeyDown}>
      <div className="explore-head" onContextMenu={onMenu}>
        <h1 title={info.title || info.name}>{info.title || info.name}</h1>
        <span className="explore-path mono" title={info.path}>
          {middle(info.path, 90)}
        </span>
        <button className="ib" aria-label="Copy path" title="Copy the file's path" onClick={() => void copyPath(info.path, toast)}>
          <Icon name="copy" />
        </button>
        {/\.lbd\.writing$/i.test(info.path) && <MeasuringStatus path={info.path} />}
        <span className="explore-head-actions">
          <button className="primary" onClick={openFigure} title="Make a figure of this file: styles and export">
            Open in Figure
          </button>
          <button className="ib" aria-label="Show in folder" title="Show in folder" onClick={() => api.reveal(info.path).catch((e) => onError(e.message))}>
            <Icon name="folder" />
          </button>
          <button className="ib" aria-label="File info" title="File info: its values, axes and metadata" onClick={() => showInspector("file")}>
            <Icon name="info" />
          </button>
          <button className="ib" aria-label="More" aria-haspopup="menu" title="More: Library picture, forget this view" onClick={headMenu}>
            <Icon name="more" />
          </button>
        </span>
      </div>
      {updating && (
        <div className="disk-note" role="status">
          {updating}
        </div>
      )}
      {plottable.length === 0 ? (
        <div className="explore-body numbers">
          <div className="numbers-only" role="status">
            <p>This file has only single numbers, so there is nothing to explore:</p>
            <ul>
              {info.values.map((v) => (
                <li key={v.name}>
                  {v.label || v.name} = {v.text ?? "?"}
                </li>
              ))}
            </ul>
          </div>
          <FileDetails info={info} metaFilter layout="library" />
        </div>
      ) : (
        <div className="explore-body" ref={bodyRef} style={bodySizes}>
          <div className="explore-scrim" onClick={() => setCtlOpen(false)} />
          <div className="ex-handle ctl-handle" aria-label="Width of the controls" title="Drag to change the width · Double-click: the default" {...ctlSize.handle} />
          <div className="ex-handle insp-w-handle" aria-label="Width of the inspector" title="Drag to change the width · Double-click: the default" {...inspWidth.handle} />
          <div className="ex-handle insp-h-handle" aria-label="Height of the inspector" title="Drag to change the height · Double-click: the default" {...inspHeight.handle} />
          <aside className="explore-controls" aria-label="Controls">
            <ExploreControls
              heading={several ? `Panel ${rec.active + 1}: ${titleOf(act)}` : null}
              info={info}
              resolved={resolved}
              settings={act.settings}
              stat={act.stat}
              onStat={actApi.onStat}
              listOpen={act.listOpen}
              opsInfo={actLive.opsInfo}
              failed={actLive.failed}
              onOpenInFigure={openFigure}
              angle={act.view?.angle as Angle | undefined}
              setAngle={(a) => actActions.current?.setAngle(a)}
              calculate={(what, index) => actActions.current?.calculate(what, index) ?? Promise.reject(new Error("the plot isn't open yet"))}
              onListOpen={actApi.onListOpen}
              updateSpec={actApi.updateSpec}
              updateSettings={actApi.updateSettings}
              onValueMenu={valueMenu}
              crange={actLive.crange ?? null}
              contrast={
                resolved?.kind === "heatmap" ? (
                  <Contrast
                    load={() => actActions.current?.histogram(act.settings) ?? Promise.resolve(null)}
                    loadKey={JSON.stringify([resolved.session, resolved.spec, act.settings.select ?? null, act.settings.cscale ?? null, info.version, act.settings.crange ?? null, live[act.id]?.crange?.state ?? null])}
                    clim={act.settings.clim ?? [null, null]}
                    onClim={(c) => actApi.updateSettings({ clim: c })}
                  />
                ) : null
              }
            />
          </aside>
          <div className="panels">
            <div className="panel-bar" onDragOver={allowDrop} onDrop={(e) => dropOn(e, null)}>
              <button className="ib controls-toggle" aria-label="Controls" aria-expanded={ctlOpen} title="Controls: what to plot, display, processing" onClick={() => setCtlOpen((o) => !o)}>
                <Icon name="gear" />
              </button>
              <button onClick={addMenu} title={full ? `At most ${MAX_PANELS} panels` : "Show a value in a new panel (or drag a value here)"}>
                + Panel ▾
              </button>
              {several && (
                <span className="segmented-icons" role="radiogroup" aria-label="Layout">
                  {(["side", "stacked"] as const).map((l) => (
                    <button
                      key={l}
                      className="ib"
                      role="radio"
                      aria-checked={rec.layout === l}
                      aria-label={l === "side" ? "side by side" : "stacked"}
                      title={l === "side" ? "Side by side" : "Stacked"}
                      onClick={() => setRec((r) => r && { ...r, layout: l })}
                    >
                      <Icon name={l === "side" ? "side" : "stacked"} />
                    </button>
                  ))}
                </span>
              )}
              {several && (
                <span className="panel-sync" title="What the panels share: zoom along x or y, the sliders, the cursors">
                  {(["x", "y", "sliders", "cursors"] as const).map((k) => (
                    <button
                      key={k}
                      className="chip toggle-chip"
                      role="checkbox"
                      aria-checked={rec.sync[k]}
                      aria-label={`Sync ${k}`}
                      title={SYNC_TIPS[k]}
                      onClick={() => toggleSync(k)}
                    >
                      <Icon name="link" /> {k}
                    </button>
                  ))}
                </span>
              )}
              {tooNarrow && <span className="muted small stack-note">stacked: too narrow side by side</span>}
              <span className="spacer" />
              <button className="ib" aria-label="Mouse and keys" title="Mouse and keys (?)" onClick={() => actActions.current?.help()}>
                <Icon name="help" />
              </button>
            </div>
            <div
              ref={gridRef}
              className={"panel-grid" + (several ? " several" : "") + (rows > 1 ? " rows" : "")}
              style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gridTemplateRows: `repeat(${rows}, minmax(${rows > 2 ? 150 : 200}px, 1fr))` }}
            >
              {rec.panels.map((p, i) => {
                const pa = panelApi(p.id);
                const note = rec.sync.x && i !== rec.active ? notSynced(p) : null;
                return (
                  <section
                    key={p.id}
                    className={"panel" + (several && i === rec.active ? " active" : "")}
                    data-panel-index={i}
                    aria-label={several ? `Panel ${i + 1}` : undefined}
                    onPointerDownCapture={() => setActive(i)}
                    onDragOver={allowDrop}
                    onDrop={(e) => dropOn(e, i)}
                  >
                    <ExploreView
                      key={`${viewKey}-${panelKeys[p.id] ?? 0}`}
                      active={!several || i === rec.active}
                      info={info}
                      spec={p.spec}
                      version={info.version}
                      onOpened={(o) => setLive(p.id, { resolved: o, failed: null })}
                      onFailed={(m) => setLive(p.id, { failed: m })}
                      onError={(m) => (several ? onError(`Panel ${i + 1}: ${m}`) : onError(m))}
                      settings={p.settings}
                      stat={p.stat}
                      initialView={p.view}
                      onView={pa.onView}
                      cursors={p.cursors}
                      onCursors={pa.onCursors}
                      onReading={(a) => setLive(p.id, { reading: a })}
                      actions={actionsOf(p.id)}
                      onStepSlider={pa.onStepSlider}
                      onShowCut={pa.onShowCut}
                      onOpsInfo={(o) => setLive(p.id, { opsInfo: o })}
                      follow={follows[p.id] ?? null}
                      onUserView={(v) => onUserView(p.id, v)}
                      dataItems={() => dataItems(p.id)}
                      onOpenInFigure={openFigure}
                      panelItems={several ? () => panelEntries(i) : undefined}
                      title={
                        <div
                          className="panel-title"
                          draggable={several}
                          onDragStart={(e) => e.dataTransfer.setData(DRAG_PANEL, String(i))}
                          onContextMenu={several ? (e) => panelMenu(e, i) : undefined}
                          title={several ? "Drag to move this panel; right-click for more" : titleOf(p)}
                        >
                          {several && <span className="panel-num">{i + 1}</span>}
                          <span className="panel-name">{titleOf(p)}</span>
                          {note && <span className="panel-note muted small" title={note}>{note}</span>}
                          {several && (
                            <button className="ib panel-remove" aria-label={`Remove panel ${i + 1}`} title="Remove this panel" onClick={() => removePanel(i)}>
                              <Icon name="close" />
                            </button>
                          )}
                        </div>
                      }
                      onSync={(sy) => {
                        const old = liveRef.current[p.id]?.sync;
                        if (!old || JSON.stringify(old) !== JSON.stringify(sy)) setLive(p.id, { sync: sy });
                      }}
                      onCrange={(c) => {
                        if (JSON.stringify(liveRef.current[p.id]?.crange ?? null) !== JSON.stringify(c ?? null)) setLive(p.id, { crange: c });
                      }}
                    />
                  </section>
                );
              })}
            </div>
          </div>
          <aside className="explore-inspector" aria-label="Inspector">
            <div className="inspector-tabs" role="tablist" aria-label="Inspector">
              {INSPECTOR_TABS.map(([t, label]) => (
                <button
                  key={t}
                  role="tab"
                  aria-selected={inspTab === t}
                  className={inspTab === t ? "on" : ""}
                  onClick={() => (inspTab === t && inspOpen ? setInspOpen(false) : showInspector(t))}
                >
                  {label}
                </button>
              ))}
              <button className="ib inspector-fold" aria-label={inspOpen ? "Fold the inspector" : "Unfold the inspector"} aria-expanded={inspOpen} onClick={() => setInspOpen((o) => !o)}>
                {inspOpen ? "▾" : "▴"}
              </button>
            </div>
            <div className="inspector-body" role="tabpanel" aria-label={INSPECTOR_TABS.find(([t]) => t === inspTab)![1]}>
              {inspTab === "cursors" && (cursorPanel ?? <p className="muted small">Opening…</p>)}
              {inspTab === "file" && <FileDetails info={info} layout="library" part="tables" />}
              {inspTab === "meta" && <FileDetails info={info} metaFilter layout="library" part="meta" />}
            </div>
          </aside>
        </div>
      )}
      {menu && <ContextMenu menu={menu} onClose={() => setMenu(null)} />}
      {exporting && (
        <ExportDialog
          sources={exporting}
          onClose={() => setExporting(null)}
          onSaved={(paths) => toast(`Saved ${paths.join(", ")}`)}
        />
      )}
      {wholeCsv && <ExportDialog sources={[]} file={path} onClose={() => setWholeCsv(false)} onSaved={(paths) => toast(`Saved ${paths.join(", ")}`)} />}
    </div>
  );
}

type InspectorTab = "cursors" | "file" | "meta";
const INSPECTOR_TABS: [InspectorTab, string][] = [
  ["cursors", "Cursors"],
  ["file", "Values & axes"],
  ["meta", "Metadata"],
];
/** The panel bar's sync chips: what each shares between panels. */
const SYNC_TIPS = {
  x: "x: panels with the same horizontal axis (label and unit) zoom and pan together along it; their vertical axes stay their own",
  y: "y: panels with the same vertical axis zoom and pan together along it (curves: the same unit; maps: the same axis)",
  sliders:
    "sliders: a slider chooses the step of an axis that isn't drawn. " +
    "Panels with a slider of the same axis show the same step: moving one moves the others (by stored step)",
  cursors: "cursors: panels with the same horizontal axis share the cursors' positions (each reads its own value there)",
} as const;
const INSPECTOR_KEY = "lbd-explore-inspector";

/** Units as written for people: V^2 → V², Hz^-1 → Hz⁻¹. */
export function unitText(unit: string): string {
  const sup: Record<string, string> = { "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹", "-": "⁻" };
  return unit.replace(/\^(-?\d+)/g, (_, p: string) => [...p].map((c) => sup[c] ?? c).join(""));
}

// ---- what to plot, and how ------------------------------------------------------------------------

interface ControlsProps {
  /** "Panel 2: Q" when there are several panels. */
  heading: string | null;
  /** A map with a slider: where its colours come from, and how far every slice's range is. */
  crange?: ExploreFrameMeta["crange"];
  info: FileInfo;
  resolved: ExploreOpen | null;
  settings: ViewSettings;
  updateSpec: (patch: PlotSpec) => void;
  updateSettings: (patch: ViewSettings) => void;
  children?: ReactNode;
  /** The contrast control (maps), in the Colour section. */
  contrast?: ReactNode;
  listOpen?: boolean;
  onListOpen: (open: boolean) => void;
  opsInfo: OpsInfo | null;
  calculate: (what: "delay" | "rotation", index: number) => Promise<number>;
  /** A value's right-click menu (new panel, only this value). */
  onValueMenu: (e: MouseEvent, name: string) => void;
  /** How a pixel shows several map cells (Display). */
  stat: ReduceStat;
  onStat: (s: ReduceStat) => void;
  /** The plot couldn't be opened: why. */
  failed?: string | null;
  onOpenInFigure: () => void;
  angle?: Angle;
  setAngle: (a: Partial<Angle> | null) => void;
}

/** The sections of the controls that are open (this browser); Data is open at first. */
const SECTIONS_KEY = "lbd-explore-sections";
function useSections(): [Record<string, boolean>, (name: string, open: boolean) => void] {
  const [open, setOpen] = useState<Record<string, boolean>>(() => {
    try {
      return { data: true, ...JSON.parse(localStorage.getItem(SECTIONS_KEY) ?? "{}") };
    } catch {
      return { data: true };
    }
  });
  const set = (name: string, on: boolean) =>
    setOpen((o) => {
      const next = { ...o, [name]: on };
      try {
        localStorage.setItem(SECTIONS_KEY, JSON.stringify(next));
      } catch {
        /* not remembered */
      }
      return next;
    });
  return [open, set];
}

/** One folding section of the controls. */
function Section({ name, title, badge, open, onToggle, children }: { name: string; title: string; badge?: ReactNode; open: boolean; onToggle: (name: string, open: boolean) => void; children: ReactNode }) {
  return (
    <details className="controls-section" open={open} onToggle={(e) => onToggle(name, (e.currentTarget as HTMLDetailsElement).open)}>
      <summary>
        {title}
        {badge && <span className="section-badge">{badge}</span>}
      </summary>
      <div className="section-body">{children}</div>
    </details>
  );
}

function ExploreControls({ heading, info, resolved, settings, updateSpec, updateSettings, children, contrast, listOpen, onListOpen, opsInfo, calculate, onValueMenu, stat, onStat, failed, onOpenInFigure, crange, angle, setAngle }: ControlsProps) {
  const [sections, setSection] = useSections();
  if (!resolved)
    return failed ? (
      <div className="controls">
        {heading && <h2 className="panel-heading">{heading}</h2>}
        <p className="small">This plot can't be shown here: see the panel.</p>
        <button onClick={onOpenInFigure}>Open in Figure</button>
      </div>
    ) : (
      <div className="controls muted small">Opening…</div>
    );
  const r = resolved.spec;
  const kind = resolved.kind;
  const Controls = kindOf(kind).controls;
  const values = r.values ?? [];
  const first = info.values.find((v) => v.name === values[0]);
  const byName = new Map(info.values.map((v) => [v.name, v]));
  // a variable sweep's curves: the axes and values as drawn, on their real axes (16.41)
  const real = r.real_axes;
  const axesOf = (v: ValueInfo) => real?.values[v.name] ?? v.axes;
  const label = (name: string) => {
    const a = real?.axes.find((x) => x.name === name) ?? info.axes.find((x) => x.name === name) ?? byName.get(name);
    return a ? (a.label || a.name).replace(/ \(point number\)$/, r.levels || real ? "" : " (point number)") : name;
  };
  const plottable = info.values.filter((v) => v.shape.length > 0);
  const anyComplex = values.some((n) => byName.get(n)?.complex);
  // a value's unit as plotted (complex values: as the complex mode makes it)
  const unitOf = (v: ValueInfo) => (v.complex ? `${r.complex ?? "abs"} of ${v.unit}` : v.unit);
  const units = new Set(values.map((n) => byName.get(n)).filter((v): v is ValueInfo => !!v).map(unitOf));
  // x: an axis of the plotted value, or (curves) a real value with the same axes
  // a variable sweep's curves: its real coordinates first, the position inside a step last
  const inStep = (a: string) => !!real?.axes.find((x) => x.name === a)?.in_step;
  const firstAxes = first ? (r.levels?.slice(-2) ?? axesOf(first)) : [];
  const xChoices = first
    ? [
        ...(real?.coordinates ?? []).map((c) => ({ name: c, text: label(c) })),
        ...[...firstAxes.filter((a) => !inStep(a)), ...firstAxes.filter(inStep)].map((a) => ({ name: a, text: label(a) })),
        ...(kind === "curve" || kind === "scatter"
          ? info.values
              .filter((v) => !values.includes(v.name) && !v.complex && v.shape.length > 0 && axesOf(v).join() === firstAxes.join())
              .map((v) => ({ name: v.name, text: `${v.label || v.name} (value)` }))
          : []),
      ]
    : [];
  const along = (r as PlotSpec & { along?: string }).along ?? r.x;
  // a variable sweep's map: its two inner levels
  const others = firstAxes.filter((a) => a !== along);
  // the traces that can be chosen: one per position of the series axis (curves) or map row
  const traceAxis = kind === "curve" ? r.series : kind === "heatmap" ? r.y : undefined;
  const row = kindOf(kind);
  const scales = row.scales ?? ["x", "y"];
  const clim = settings.clim ?? [null, null];

  const opsCount = (settings.ops ?? []).length + Object.values(settings.equations ?? {}).filter(Boolean).length;
  return (
    <div className="controls">
      {heading && <h2 className="panel-heading">{heading}</h2>}
      <Section name="data" title="Data" open={!!sections.data} onToggle={setSection}>
      <label className="field">
        <span>Plot</span>
        <PlotKindSelect path={info.path} value={kind} first={first?.name} page="explore" onChoose={(k, fit) => updateSpec({ kind: k, x: undefined, y: undefined, series: undefined, color: undefined, all: undefined, options: undefined, ...(r.complex === "iq" || r.complex === "re_im" ? { complex: undefined } : {}), ...(fit?.length && first && !fit.includes(first.name) ? { values: [fit[0]] } : {}), ...kindOf(k).starting?.(info, first) })} />
      </label>

      {!row.ownData && (
      <fieldset className="field">
        <legend>{kind === "heatmap" ? "Value" : "Values"}</legend>
        {plottable.map((v) => {
          const on = values.includes(v.name);
          // a histogram overlays values of one unit
          const fits = !first || v.name === first.name || (kind === "curve" && axesOf(v).includes(along ?? "")) || (kind === "histogram" && unitOf(v) === unitOf(first)) || (kind === "scatter" && r.complex !== "iq" && v.axes.join() === first.axes.join());
          // a panel shows two units (left and right axis); a third goes in another panel
          const third = kind === "curve" && !on && units.size >= 2 && !units.has(unitOf(v));
          return (
            <label
              key={v.name}
              className="check"
              draggable
              onDragStart={(e) => e.dataTransfer.setData(DRAG_VALUE, v.name)}
              onContextMenu={(e) => onValueMenu(e, v.name)}
              title={
                kind === "curve" && third
                  ? "A third unit: clicking shows it here instead (or right-click: in another panel)"
                  : kind === "curve" && !fits && !on
                    ? "Different axis: clicking shows it here instead (or right-click: in another panel)"
                    : "Drag onto a panel to show it there; right-click for more"
              }
            >
              <input
                type={kind === "heatmap" ? "radio" : "checkbox"}
                name="explore-values"
                checked={on}
                // never locked (16.46): a value that can't join the plot replaces it, as on Histogram and Scatter
                onChange={() => {
                  if (kind === "heatmap") updateSpec({ values: [v.name], x: undefined, y: undefined });
                  else if (kind === "curve" && !on && (!fits || third)) updateSpec({ values: [v.name], x: undefined, y: undefined, series: undefined });
                  else if (kind === "histogram" && !fits) updateSpec({ values: [v.name], color: undefined, all: undefined, index: undefined });
                  else if (kind === "scatter" && !fits) updateSpec({ values: [v.name], x: undefined, color: undefined, all: undefined, index: undefined, complex: undefined, ...kindOf(kind).starting?.(info, v) });
                  else if (on && values.length > 1) updateSpec({ values: values.filter((n) => n !== v.name) });
                  else if (!on) updateSpec({ values: [...values, v.name] });
                }}
              />
              {v.label || v.name}
              {v.unit && <span className="muted small"> ({v.unit})</span>}
            </label>
          );
        })}
      </fieldset>
      )}

      {/* the axes as one block: the same drop-downs in the same place for curves and maps */}
      {!row.ownData && !row.noAxes && r.complex !== "iq" && (
      <div className={"field axes-field" + (kind === "heatmap" ? " two" : "")} role="group" aria-label="Axes">
        <span>Axes</span>
        <div className="axes-grid">
          <span className="axes-name">Horizontal</span>
          <select aria-label="Horizontal axis" value={r.x ?? ""} onChange={(e) => updateSpec({ x: e.target.value, y: undefined, series: undefined })}>
            {xChoices.map((c) => (
              <option key={c.name} value={c.name}>
                {c.text}
              </option>
            ))}
          </select>
          {kind === "heatmap" && (
            <>
              <button className="axes-swap" title="Swap the horizontal and vertical axes" aria-label="Swap the axes" onClick={() => updateSpec({ x: r.y, y: r.x })}>
                ⇅
              </button>
              <span className="axes-name">Vertical</span>
              <select aria-label="Vertical axis" value={r.y ?? ""} onChange={(e) => updateSpec({ y: e.target.value })}>
                {others.map((a) => (
                  <option key={a} value={a}>
                    {label(a)}
                  </option>
                ))}
              </select>
            </>
          )}
        </div>
      </div>
      )}

      {Controls && <Controls info={info} spec={r} resolved={r} update={updateSpec} settings={settings} updateSettings={updateSettings} page="explore" angle={angle} setAngle={setAngle} />}
      {(crange?.from === "histogram" || crange?.from === "scatter") && crange.state === "working" && <p className="small muted">Counting… {Math.round((crange.fraction ?? 0) * 100)} %</p>}

      {kind === "curve" && values.length === 1 && others.length > 0 && (
        <label className="field">
          <span>One curve per</span>
          <select aria-label="One curve per" value={r.series ?? "none"} onChange={(e) => updateSpec({ series: e.target.value })}>
            <option value="none">(one curve)</option>
            {others.map((a) => (
              <option key={a} value={a}>
                {label(a)}
              </option>
            ))}
          </select>
        </label>
      )}

      {(anyComplex || r.complex === "iq") && !row.ownData && (
        <label className="field">
          <span>Complex values</span>
          <select aria-label="Complex values" value={r.complex ?? "abs"} onChange={(e) => updateSpec({ complex: e.target.value })}>
            {COMPLEX_MODES.filter(([v]) => v !== "iq" || kind === "scatter").map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
      )}

      {(r.slices ?? []).map((s) => (
        <SliceControl
          key={s.axis}
          path={info.path}
          version={info.version}
          slice={s}
          onIndex={(i) => updateSpec({ index: { ...(r.index ?? {}), [s.axis]: i } })}
        />
      ))}

      {traceAxis && traceAxis !== "none" && (
        <AxisSelect
          path={info.path}
          version={info.version}
          axis={traceAxis}
          title={kind === "curve" ? `Curves shown (${label(traceAxis)})` : `Rows in the map (${label(traceAxis)})`}
          chosen={settings.select?.[traceAxis] ?? null}
          onChange={(chosen) => updateSettings({ select: chosen === null ? undefined : { [traceAxis]: chosen } })}
          open={listOpen}
          onOpen={onListOpen}
        />
      )}

      </Section>

      {(scales.length > 0 || kind === "heatmap") && (
      <Section name="display" title="Display" open={!!sections.display} onToggle={setSection}
               badge={settings.xscale === "log" || settings.yscale === "log" || settings.cscale === "log" ? "log" : undefined}>
      <fieldset className="field">
        <legend>Scales</legend>
        {scales.includes("x") && (
        <label className="check">
          <input type="checkbox" checked={settings.xscale === "log"} onChange={(e) => updateSettings({ xscale: e.target.checked ? "log" : "linear" })} />
          Log horizontal
        </label>
        )}
        {scales.includes("y") && (
        <label className="check">
          <input type="checkbox" checked={settings.yscale === "log"} onChange={(e) => updateSettings({ yscale: e.target.checked ? "log" : "linear" })} />
          Log vertical
        </label>
        )}
        {kind === "heatmap" && (
          <label className="check">
            <input type="checkbox" checked={settings.cscale === "log"} onChange={(e) => updateSettings({ cscale: e.target.checked ? "log" : "linear" })} />
            Log colour
          </label>
        )}
      </fieldset>
            {kind === "heatmap" && (
        <fieldset className="field">
          <legend>Colour</legend>
          <div className="row-controls">
            <select aria-label="Colour map" value={settings.cmap ?? ""} onChange={(e) => updateSettings({ cmap: e.target.value || undefined })}>
              <option value="">(the style's)</option>
              {CMAPS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <label className="check">
              <input type="checkbox" checked={!!settings.invert} onChange={(e) => updateSettings({ invert: e.target.checked })} />
              Invert
            </label>
          </div>
          {(r.slices ?? []).length > 0 && (
            <div className="field crange-field">
              <span>Colour range over</span>
              <Segmented
                name="crange"
                label="Colour range over"
                value={settings.crange ?? "slice"}
                options={[
                  ["slice", "This slice", "Each slider position has its own colour range: every step shows its full contrast, but a colour means another number at each step"],
                  ["all", "All slices", "The range of every slider position: a colour means the same number at every step, so moving the slider shows the change"],
                ]}
                onChange={(v) => updateSettings({ crange: v })}
              />
              {crange?.state === "working" && (
                <span className="muted small" role="status">
                  Working out every slice's range: {Math.round((crange.fraction ?? 0) * 100)} % of {crange.slices} slices; until then this slice's.
                </span>
              )}
              {crange?.state === "failed" && <span className="small export-warning">{crange.error}</span>}
            </div>
          )}
          <NumberRange
            label="Colour range"
            value={clim}
            log={settings.cscale === "log"}
            onChange={(v) => updateSettings({ clim: v[0] === null && v[1] === null ? undefined : v })}
          />
          {contrast}
        </fieldset>
      )}
      {kind === "heatmap" && !r.levels && (
        <label className="field" title="When a screen pixel stands for several cells, what it shows">
          <span>Several cells per pixel</span>
          <select aria-label="Several cells per pixel" value={stat} onChange={(e) => onStat(e.target.value as ReduceStat)}>
            <option value="max">max (peaks stay)</option>
            <option value="min">min (dips stay)</option>
            <option value="mean">mean</option>
          </select>
        </label>
      )}
      </Section>
      )}

      <Section name="processing" title="Processing" open={!!sections.processing} onToggle={setSection}
               badge={opsCount ? `${opsCount} on` : undefined}>
      {kind === "scatter" ? <p className="muted small">Operations aren't available on a scatter plot yet.</p> : <Operations
        kind={kind}
        xLabel={label(along ?? r.x ?? "x")}
        tracesLabel={r.y ? label(r.y) : traceAxis && traceAxis !== "none" && values.length === 1 ? label(traceAxis) : null}
        shapeOnly={row.shapeOps}
        ops={settings.ops ?? []}
        on={settings.ops_on !== false}
        info={opsInfo}
        onChange={(ops) => updateSettings({ ops: ops.length ? ops : undefined, ...(ops.length ? {} : { ops_on: undefined }) })}
        onOn={(on) => updateSettings({ ops_on: on ? undefined : false })}
        complexValues={anyComplex}
        calculate={calculate}
        equations={settings.equations ?? {}}
        onEquations={(e) =>
          updateSettings({
            equations: e.x || e.y || e.z ? e : undefined,
            // a new z equation: typed colour limits are in the old numbers, so the colours follow the new values
            ...((e.z ?? "") !== (settings.equations?.z ?? "") ? { clim: undefined } : {}),
          })
        }
      />}

      </Section>
      {children}
    </div>
  );
}

import { DragEvent, KeyboardEvent, MouseEvent, MutableRefObject, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import NumberRange from "./NumberRange";
import { api, CursorsAnswer, ExploreOpen, FileInfo, OpsInfo, PlotSpec, ReduceStat, SyncKeys, ValueInfo } from "./api";
import Operations from "./Operations";
import Contrast from "./Contrast";
import CursorPanel, { OtherPanel } from "./CursorPanel";
import { CursorsState, NO_CURSORS } from "./cursors";
import ExploreView, { ExploreActions, Follow, View, ViewSettings } from "./ExploreView";
import AxisSelect from "./AxisSelect";
import { COMPLEX_MODES, SliceControl } from "./FileView";
import { useDiskVersion } from "./watch";
import { ContextMenu, MenuAt, menuAt } from "./menu";

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
 */

interface Props {
  path: string;
  onOpenInFigure: () => void;
  onError: (msg: string) => void;
  onMenu?: (e: MouseEvent) => void;
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
  sync: { x: boolean; y: boolean; sliders: boolean };
}

/** At most this many panels (each is a plot drawn by the server); a new file opens with up to FIRST_PANELS. */
export const MAX_PANELS = 6;
const FIRST_PANELS = 4;
// Drag and drop: a value from the side bar, a panel by its title bar.
const DRAG_VALUE = "application/x-lbd-value";
const DRAG_PANEL = "application/x-lbd-panel";

const newId = () => Math.random().toString(36).slice(2, 10);
const freshPanel = (spec: PlotSpec): PanelState => ({ id: newId(), spec, settings: {}, stat: "max", view: null, cursors: NO_CURSORS });

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
    sync: { x: true, y: false, sliders: true },
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
}
const NO_LIVE: Live = { resolved: null, reading: null, opsInfo: null, sync: null };

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
  if (out.kind === "scatter" || out.kind === "auto") delete out.kind; // Explore shows curves and maps
  if (out.complex === "iq") delete out.complex;
  return out;
}

/** A file's shape, to tell data added (same names and axes, longer) from a different file. */
function grewOnly(before: FileInfo, now: FileInfo): boolean {
  const axes = new Map(now.axes.map((a) => [a.name, a.length]));
  if (before.axes.some((a) => !axes.has(a.name) || axes.get(a.name)! < a.length)) return false;
  const values = new Map(now.values.map((v) => [v.name, v]));
  return before.values.every((v) => values.get(v.name)?.axes.join() === v.axes.join() && values.get(v.name)?.dtype === v.dtype);
}

export default function ExploreTab({ path, onOpenInFigure, onError, onMenu }: Props) {
  const [info, setInfo] = useState<FileInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
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

  /** With x synchronized, the cursors are shared: the active panel leads, and the panels with
   * the same x get its cursors' x (type, on, which is active); each keeps its own y or trace and
   * snaps the cursor to its own data. What the others report back changes only themselves. */
  const sharedKey = useRef("");
  const shareCursors = useCallback((id: string, c: CursorsState) => {
    const r = recRef.current, me = liveRef.current[id]?.sync;
    if (!r || r.panels.length < 2 || !r.sync.x || r.panels[r.active]?.id !== id || !me) return;
    const key = JSON.stringify({ id, type: c.type, on: c.on, active: c.active, xs: c.at.map((a) => a.x) });
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
        const at = c.at.map((a, k) => {
          const trace = own[k]?.trace ?? (curve ? 0 : undefined); // curves: on a trace, so the x is kept
          return { x: a.x, y: own[k]?.y ?? mid, ...(trace !== undefined ? { trace } : {}) };
        });
        changed = true;
        return { ...q, cursors: { ...q.cursors, type: c.type, on: c.on, active: c.active, at } };
      });
      return changed ? { ...rr, panels } : rr;
    });
  }, []);

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
        if (moved && recRef.current?.sync.sliders && recRef.current.panels.length > 1)
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
          });
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
        onShowCut: (which: "row" | "column", index: Record<string, number>) => {
          const r = liveRef.current[id]?.resolved?.spec;
          if (!r?.x || !r.y) return;
          const fixed = which === "row" ? r.y : r.x;
          updatePanel(id, (s) => ({
            ...s,
            back: s.spec,
            spec: { ...s.spec, kind: "curve", x: which === "row" ? r.x : r.y, y: undefined, series: "none", index: { ...(r.index ?? {}), [fixed]: index[fixed] } },
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
    [updatePanel, restart, shareCursors],
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
      panelApi(p.id).updateSpec(kind === "heatmap" ? { values: [name], x: undefined, y: undefined } : { values: [...values, name] });
      setActive(i);
    },
    [panelApi, setActive],
  );
  const [menu, setMenu] = useState<MenuAt | null>(null);

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

  const forget = async () => {
    if (!info) return;
    await api.forget(path).catch((e) => onError((e as Error).message));
    setRec(fresh(info));
    setViewKey((k) => k + 1);
  };

  if (loadError) {
    return (
      <div className="file-view">
        <div className="error-box">
          <strong>Can't open this file.</strong> {loadError}
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
  const actApi = panelApi(act.id);
  const actActions = actionsOf(act.id);
  const resolved = actLive.resolved;
  const [rows, cols] = gridOf(n, rec.layout);
  const byName = new Map(info.values.map((v) => [v.name, v]));
  const titleOf = (p: PanelState) =>
    (live[p.id]?.resolved?.spec.values ?? p.spec.values ?? [plottable[0]?.name ?? ""])
      .map((name) => {
        const v = byName.get(name);
        return v ? `${v.label || v.name}${v.unit ? ` (${v.unit})` : ""}` : name;
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
        label: `${v.label || v.name}${v.unit ? ` (${v.unit})` : ""}`,
        disabled: full,
        onClick: () => addPanel({ values: [v.name] }),
      })),
    });
  };
  const panelMenu = (e: MouseEvent, i: number) => {
    e.preventDefault();
    setMenu(
      menuAt(e, [
        { label: "Duplicate panel", onClick: () => duplicatePanel(i), disabled: full },
        { label: "Remove panel", onClick: () => removePanel(i), disabled: n <= 1, danger: true },
      ]),
    );
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

  return (
    <div className="file-view explore-tab" onKeyDown={onKeyDown}>
      <div className="file-head" onContextMenu={onMenu}>
        <div>
          <h1>{info.title || info.name}</h1>
          <div className="muted small path" title={info.path}>
            {info.path}
          </div>
        </div>
        <div className="actions">
          <button onClick={onOpenInFigure} title="Make a figure of this file: styles and export">
            Open in Figure
          </button>
          <button onClick={forget} title="LBD remembers this view on this computer (not in the file); start afresh">
            Forget this view
          </button>
          <button onClick={() => api.reveal(info.path).catch((e) => onError(e.message))}>Show in folder</button>
        </div>
      </div>
      {updating && (
        <div className="disk-note" role="status">
          {updating}
        </div>
      )}
      {plottable.length === 0 ? (
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
      ) : (
        <div className="plot-area">
          <ExploreControls
            heading={several ? `Panel ${rec.active + 1}: ${titleOf(act)}` : null}
            info={info}
            resolved={resolved}
            settings={act.settings}
            listOpen={act.listOpen}
            opsInfo={actLive.opsInfo}
            calculate={(what, index) => actActions.current?.calculate(what, index) ?? Promise.reject(new Error("the plot isn't open yet"))}
            onListOpen={actApi.onListOpen}
            updateSpec={actApi.updateSpec}
            updateSettings={actApi.updateSettings}
            onValueMenu={valueMenu}
            contrast={
              resolved?.kind === "heatmap" ? (
                <Contrast
                  load={() => actActions.current?.histogram(act.settings) ?? Promise.resolve(null)}
                  loadKey={JSON.stringify([resolved.session, resolved.spec, act.settings.select ?? null, act.settings.cscale ?? null, info.version])}
                  clim={act.settings.clim ?? [null, null]}
                  onClim={(c) => actApi.updateSettings({ clim: c })}
                />
              ) : null
            }
          >
            {resolved && (
              <CursorPanel
                kind={resolved.kind}
                cursors={act.cursors}
                onCursors={actApi.onCursors}
                reading={actLive.reading}
                actions={actActions}
                onBack={act.back ? actApi.onBack : null}
                others={rec.sync.x ? othersAtX : []}
              />
            )}
          </ExploreControls>
          <div className="panels">
            <div className="panel-bar" onDragOver={allowDrop} onDrop={(e) => dropOn(e, null)}>
              <button onClick={addMenu} title={full ? `At most ${MAX_PANELS} panels` : "Show a value in a new panel (or drag a value here)"}>
                + Panel ▾
              </button>
              {several && (
                <span className="panel-layout" role="radiogroup" aria-label="Layout">
                  {(["side", "stacked"] as const).map((l) => (
                    <label key={l} className="check">
                      <input type="radio" name={`layout-${path}`} checked={rec.layout === l} onChange={() => setRec((r) => r && { ...r, layout: l })} />
                      {l === "side" ? "side by side" : "stacked"}
                    </label>
                  ))}
                </span>
              )}
              {several && (
                <span className="panel-sync" title="Panels with the same axis zoom together; sliders of the same axis move together">
                  Sync:
                  {(["x", "y", "sliders"] as const).map((k) => (
                    <label key={k} className="check">
                      <input
                        type="checkbox"
                        checked={rec.sync[k]}
                        aria-label={`Sync ${k}`}
                        onChange={(e) => setRec((r) => r && { ...r, sync: { ...r.sync, [k]: e.target.checked } })}
                      />
                      {k}
                    </label>
                  ))}
                </span>
              )}
            </div>
            <div className={"panel-grid" + (several ? " several" : "")} style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, ["--rows" as string]: rows }}>
              {rec.panels.map((p, i) => {
                const pa = panelApi(p.id);
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
                    {several && (
                      <div
                        className="panel-title"
                        draggable
                        onDragStart={(e) => e.dataTransfer.setData(DRAG_PANEL, String(i))}
                        onContextMenu={(e) => panelMenu(e, i)}
                        title="Drag to move this panel; right-click for more"
                      >
                        <span className="panel-num">{i + 1}</span>
                        <span className="panel-name">{titleOf(p)}</span>
                        {rec.sync.x && i !== rec.active && notSynced(p) && <span className="panel-note muted small">{notSynced(p)}</span>}
                        <span className="spacer" />
                        <button className="link" aria-label={`Remove panel ${i + 1}`} title="Remove this panel" onClick={() => removePanel(i)}>
                          ×
                        </button>
                      </div>
                    )}
                    <ExploreView
                      key={`${viewKey}-${panelKeys[p.id] ?? 0}`}
                      compact={several}
                      info={info}
                      spec={p.spec}
                      version={info.version}
                      onOpened={(o) => setLive(p.id, { resolved: o })}
                      onError={(m) => onError(several ? `Panel ${i + 1}: ${m}` : m)}
                      settings={p.settings}
                      stat={p.stat}
                      onStat={pa.onStat}
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
                      onSync={(sy) => {
                        const old = liveRef.current[p.id]?.sync;
                        if (!old || JSON.stringify(old) !== JSON.stringify(sy)) setLive(p.id, { sync: sy });
                      }}
                    />
                  </section>
                );
              })}
            </div>
          </div>
        </div>
      )}
      {menu && <ContextMenu menu={menu} onClose={() => setMenu(null)} />}
    </div>
  );
}

// ---- what to plot, and how ------------------------------------------------------------------------

interface ControlsProps {
  /** "Panel 2: Q" when there are several panels. */
  heading: string | null;
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
}

/** Axes of a value with more than one point (the ones that can be drawn along). */
const swept = (info: FileInfo, v: ValueInfo) => v.axes.filter((a, i) => v.shape[i] > 1 && info.axes.some((x) => x.name === a));

function ExploreControls({ heading, info, resolved, settings, updateSpec, updateSettings, children, contrast, listOpen, onListOpen, opsInfo, calculate, onValueMenu }: ControlsProps) {
  if (!resolved) return <div className="controls muted small">Opening…</div>;
  const r = resolved.spec;
  const kind = resolved.kind;
  const values = r.values ?? [];
  const first = info.values.find((v) => v.name === values[0]);
  const byName = new Map(info.values.map((v) => [v.name, v]));
  const label = (name: string) => {
    const a = info.axes.find((x) => x.name === name) ?? byName.get(name);
    return a ? a.label || a.name : name;
  };
  const plottable = info.values.filter((v) => v.shape.length > 0);
  const canMap = !!first && swept(info, first).length >= 2;
  const anyComplex = values.some((n) => byName.get(n)?.complex);
  // a value's unit as plotted (complex values: as the complex mode makes it)
  const unitOf = (v: ValueInfo) => (v.complex ? `${r.complex ?? "abs"} of ${v.unit}` : v.unit);
  const units = new Set(values.map((n) => byName.get(n)).filter((v): v is ValueInfo => !!v).map(unitOf));
  // x: an axis of the plotted value, or (curves) a real value with the same axes
  const xChoices = first
    ? [
        ...first.axes.map((a) => ({ name: a, text: label(a) })),
        ...(kind === "curve"
          ? info.values
              .filter((v) => !values.includes(v.name) && !v.complex && v.shape.length > 0 && v.axes.join() === first.axes.join())
              .map((v) => ({ name: v.name, text: `${v.label || v.name} (value)` }))
          : []),
      ]
    : [];
  const along = (r as PlotSpec & { along?: string }).along ?? r.x;
  const others = first ? first.axes.filter((a) => a !== along) : [];
  // the traces that can be chosen: one per position of the series axis (curves) or map row
  const traceAxis = kind === "curve" ? r.series : r.y;
  const clim = settings.clim ?? [null, null];

  return (
    <div className="controls">
      {heading && <h2 className="panel-heading">{heading}</h2>}
      <label className="field">
        <span>Plot</span>
        <select aria-label="Plot type" value={kind} onChange={(e) => updateSpec({ kind: e.target.value as PlotSpec["kind"], x: undefined, y: undefined, series: undefined })}>
          <option value="curve">Curves</option>
          <option value="heatmap" disabled={!canMap}>
            Map{canMap ? "" : " (needs 2 swept axes)"}
          </option>
        </select>
      </label>

      <fieldset className="field">
        <legend>{kind === "heatmap" ? "Value" : "Values"}</legend>
        {plottable.map((v) => {
          const on = values.includes(v.name);
          const fits = !first || v.name === first.name || (kind === "curve" && v.axes.includes(along ?? ""));
          // a panel shows two units (left and right axis); a third goes in another panel
          const third = kind === "curve" && !on && units.size >= 2 && !units.has(unitOf(v));
          return (
            <label
              key={v.name}
              className="check"
              draggable
              onDragStart={(e) => e.dataTransfer.setData(DRAG_VALUE, v.name)}
              onContextMenu={(e) => onValueMenu(e, v.name)}
              title={third ? "A third unit: show it in another panel (right-click)" : "Drag onto a panel to show it there; right-click for more"}
            >
              <input
                type={kind === "heatmap" ? "radio" : "checkbox"}
                name="explore-values"
                checked={on}
                disabled={(!fits && !on) || third}
                onChange={() => {
                  if (kind === "heatmap") updateSpec({ values: [v.name], x: undefined, y: undefined });
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

      <label className="field">
        <span>Horizontal axis</span>
        <select aria-label="Horizontal axis" value={r.x ?? ""} onChange={(e) => updateSpec({ x: e.target.value, y: undefined, series: undefined })}>
          {xChoices.map((c) => (
            <option key={c.name} value={c.name}>
              {c.text}
            </option>
          ))}
        </select>
      </label>

      {kind === "heatmap" && (
        <div className="field">
          <span>Vertical axis</span>
          <div className="row-controls">
            <select aria-label="Vertical axis" value={r.y ?? ""} onChange={(e) => updateSpec({ y: e.target.value })}>
              {others.map((a) => (
                <option key={a} value={a}>
                  {label(a)}
                </option>
              ))}
            </select>
            <button title="Swap the horizontal and vertical axes" aria-label="Swap the axes" onClick={() => updateSpec({ x: r.y, y: r.x })}>
              ⇄
            </button>
          </div>
        </div>
      )}

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

      {anyComplex && (
        <label className="field">
          <span>Complex values</span>
          <select aria-label="Complex values" value={r.complex ?? "abs"} onChange={(e) => updateSpec({ complex: e.target.value })}>
            {COMPLEX_MODES.filter(([v]) => v !== "iq").map(([v, l]) => (
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

      <Operations
        kind={kind}
        xLabel={label(along ?? r.x ?? "x")}
        tracesLabel={kind === "heatmap" ? label(r.y ?? "") : traceAxis && traceAxis !== "none" && values.length === 1 ? label(traceAxis) : null}
        ops={settings.ops ?? []}
        on={settings.ops_on !== false}
        info={opsInfo}
        onChange={(ops) => updateSettings({ ops: ops.length ? ops : undefined, ...(ops.length ? {} : { ops_on: undefined }) })}
        onOn={(on) => updateSettings({ ops_on: on ? undefined : false })}
        complexValues={anyComplex}
        calculate={calculate}
        equations={settings.equations ?? {}}
        onEquations={(e) => updateSettings({ equations: e.x || e.y || e.z ? e : undefined })}
      />

      <fieldset className="field">
        <legend>Scales</legend>
        <label className="check">
          <input type="checkbox" checked={settings.xscale === "log"} onChange={(e) => updateSettings({ xscale: e.target.checked ? "log" : "linear" })} />
          Log horizontal
        </label>
        <label className="check">
          <input type="checkbox" checked={settings.yscale === "log"} onChange={(e) => updateSettings({ yscale: e.target.checked ? "log" : "linear" })} />
          Log vertical
        </label>
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
          <NumberRange
            label="Colour range"
            value={clim}
            log={settings.cscale === "log"}
            onChange={(v) => updateSettings({ clim: v[0] === null && v[1] === null ? undefined : v })}
          />
          {contrast}
        </fieldset>
      )}
      {children}
    </div>
  );
}

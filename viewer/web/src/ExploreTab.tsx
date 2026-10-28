import { MouseEvent, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import NumberRange from "./NumberRange";
import { api, CursorsAnswer, ExploreOpen, FileInfo, PlotSpec, ReduceStat, ValueInfo } from "./api";
import Contrast from "./Contrast";
import CursorPanel from "./CursorPanel";
import { CursorsState, NO_CURSORS } from "./cursors";
import ExploreView, { ExploreActions, View, ViewSettings } from "./ExploreView";
import AxisSelect from "./AxisSelect";
import { COMPLEX_MODES, SliceControl } from "./FileView";
import { useDiskVersion } from "./watch";

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

/** What is remembered for a file (LBD's database; see catalog.py). */
interface Remembered {
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

const fresh = (info: FileInfo): Remembered => ({ spec: startSpec(info), settings: {}, stat: "max", view: null, cursors: NO_CURSORS });

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
  const [shown, setShown] = useState<Remembered | null>(null); // what the view shows (remembered)
  const [resolved, setResolved] = useState<ExploreOpen | null>(null);
  const [viewKey, setViewKey] = useState(0); // a new one starts the view afresh
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
        // a remembered view (older ones may lack later keys), else a start from the file
        const st = r.state as unknown as Partial<Remembered> | null;
        setShown(
          st?.spec
            ? {
                spec: st.spec,
                settings: st.settings ?? {},
                stat: st.stat ?? "max",
                view: st.view ?? null,
                cursors: { ...NO_CURSORS, ...(st.cursors ?? {}) },
                ...(st.listOpen !== undefined ? { listOpen: st.listOpen } : {}),
                ...(st.back ? { back: st.back } : {}),
              }
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
          setShown(fresh(now));
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
  const shownRef = useRef(shown);
  shownRef.current = shown;
  useEffect(() => {
    if (!shown) return;
    const t = window.setTimeout(() => api.remember(path, shown).catch(() => undefined), 1000);
    return () => window.clearTimeout(t);
  }, [shown, path]);
  useEffect(
    () => () => {
      if (shownRef.current) api.remember(path, shownRef.current).catch(() => undefined);
    },
    [path],
  );

  const updateSpec = useCallback(
    (patch: PlotSpec) =>
      setShown((s) => {
        if (!s) return s;
        const spec = { ...s.spec, ...patch };
        const reset = RESETS_SELECTION.some((k) => k in patch);
        return {
          ...s,
          spec,
          settings: reset ? { ...s.settings, select: undefined } : s.settings,
          cursors: reset ? { ...s.cursors, at: [], active: 0 } : s.cursors,
          back: reset ? undefined : s.back,
        };
      }),
    [],
  );
  const onCursors = useCallback((cursors: CursorsState) => setShown((s) => s && { ...s, cursors }), []);
  const [reading, setReading] = useState<CursorsAnswer | null>(null);
  const actions = useRef<ExploreActions | null>(null);
  const resolvedRef = useRef(resolved);
  resolvedRef.current = resolved;
  // Keys [ and ]: the first slider one step.
  const onStepSlider = useCallback(
    (by: number) => {
      const r = resolvedRef.current?.spec, sl = r?.slices?.[0];
      if (!r || !sl) return;
      const i = Math.min(Math.max(sl.index + by, 0), sl.length - 1);
      if (i !== sl.index) updateSpec({ index: { ...(r.index ?? {}), [sl.axis]: i } });
    },
    [updateSpec],
  );
  // A map's row or column through cursor 1, as a curve in this tab (the map is kept to go back to).
  const onShowCut = useCallback((which: "row" | "column", index: Record<string, number>) => {
    const r = resolvedRef.current?.spec;
    if (!r?.x || !r.y) return;
    const fixed = which === "row" ? r.y : r.x;
    setShown((s) =>
      s && {
        ...s,
        back: s.spec,
        spec: { ...s.spec, kind: "curve", x: which === "row" ? r.x : r.y, y: undefined, series: "none", index: { ...(r.index ?? {}), [fixed]: index[fixed] } },
        settings: { ...s.settings, select: undefined },
        cursors: { ...s.cursors, at: [], active: 0 },
        view: null,
      },
    );
    setViewKey((k) => k + 1);
  }, []);
  const onBack = useCallback(() => {
    setShown((s) => (s?.back ? { ...s, spec: s.back, back: undefined, cursors: { ...s.cursors, at: [], active: 0 }, view: null } : s));
    setViewKey((k) => k + 1);
  }, []);
  const updateSettings = useCallback((patch: ViewSettings) => setShown((s) => s && { ...s, settings: { ...s.settings, ...patch } }), []);
  const onView = useCallback((view: View) => setShown((s) => (s && JSON.stringify(s.view) !== JSON.stringify(view) ? { ...s, view } : s)), []);
  const onStat = useCallback((stat: ReduceStat) => setShown((s) => s && { ...s, stat }), []);

  const forget = async () => {
    if (!info) return;
    await api.forget(path).catch((e) => onError((e as Error).message));
    setShown(fresh(info));
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
  if (!info || !shown) return <div className="file-view muted pad">Loading…</div>;
  const plottable = info.values.filter((v) => v.shape.length > 0);

  return (
    <div className="file-view explore-tab">
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
            info={info}
            resolved={resolved}
            settings={shown.settings}
            listOpen={shown.listOpen}
            onListOpen={(listOpen) => setShown((s) => s && { ...s, listOpen })}
            updateSpec={updateSpec}
            updateSettings={updateSettings}
            contrast={
              resolved?.kind === "heatmap" ? (
                <Contrast
                  load={() => actions.current?.histogram(shown.settings) ?? Promise.resolve(null)}
                  loadKey={JSON.stringify([resolved.session, resolved.spec, shown.settings.select ?? null, shown.settings.cscale ?? null, info.version])}
                  clim={shown.settings.clim ?? [null, null]}
                  onClim={(c) => updateSettings({ clim: c })}
                />
              ) : null
            }
          >
            {resolved && (
              <CursorPanel
                kind={resolved.kind}
                cursors={shown.cursors}
                onCursors={onCursors}
                reading={reading}
                actions={actions}
                onBack={shown.back ? onBack : null}
              />
            )}
          </ExploreControls>
          <ExploreView
            key={viewKey}
            info={info}
            spec={shown.spec}
            version={info.version}
            onOpened={setResolved}
            onError={onError}
            settings={shown.settings}
            stat={shown.stat}
            onStat={onStat}
            initialView={shown.view}
            onView={onView}
            cursors={shown.cursors}
            onCursors={onCursors}
            onReading={setReading}
            actions={actions}
            onStepSlider={onStepSlider}
            onShowCut={onShowCut}
          />
        </div>
      )}
    </div>
  );
}

// ---- what to plot, and how ------------------------------------------------------------------------

interface ControlsProps {
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
}

/** Axes of a value with more than one point (the ones that can be drawn along). */
const swept = (info: FileInfo, v: ValueInfo) => v.axes.filter((a, i) => v.shape[i] > 1 && info.axes.some((x) => x.name === a));

function ExploreControls({ info, resolved, settings, updateSpec, updateSettings, children, contrast, listOpen, onListOpen }: ControlsProps) {
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
          return (
            <label key={v.name} className="check">
              <input
                type={kind === "heatmap" ? "radio" : "checkbox"}
                name="explore-values"
                checked={on}
                disabled={!fits && !on}
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

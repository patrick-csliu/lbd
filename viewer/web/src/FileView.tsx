import { MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, AxisValues, baseName, FileInfo, formatBytes, Json, JsonObject, lastDownloadWarnings, PlotSpec, RenderResult, Slice, TabState, ValueInfo } from "./api";
import { deepMerge, isEmptyObject } from "./util";
import { ConfirmDialog, ConfirmRequest } from "./menu";
import { useToast } from "./toast";
import { HelpLink } from "./help";
import { useDiskVersion } from "./watch";

interface Props {
  path: string;
  plotted: boolean;
  onPlot: () => void;
  styles: string[];
  defaultStyle: string;
  styleRevision: number;
  onError: (msg: string) => void;
  /** Unsaved settings this tab starts with (it was moved here from another page). */
  initialState?: TabState;
  /** Reports the unsaved settings, so they can travel when the tab moves to another page. */
  onStateChange?: (state: TabState) => void;
  /** Why this tab can't be saved right now (being moved, or open in another page), or null. */
  locked?: string | null;
  /** Right-click on the file's header: the same menu as its tab. */
  onMenu?: (e: MouseEvent) => void;
}

const COMPLEX_MODES: [string, string][] = [
  ["abs", "Magnitude"],
  ["db", "Magnitude (dB)"],
  ["phase", "Phase (rad)"],
  ["phase_deg", "Phase (°)"],
  ["real", "Real part"],
  ["imag", "Imaginary part"],
  ["iq", "I/Q plane (real vs imaginary)"],
];

const ZOOMS: [string, string][] = [
  ["fit", "Fit"],
  ["1", "100% (print size)"],
  ["1.5", "150%"],
  ["2", "200%"],
];

const MM_TO_PX = 96 / 25.4;
// A changed file that can't be read (still being written) is tried again for this long.
const GIVE_UP_AFTER = 10_000;

export default function FileView(props: Props) {
  const { path, plotted, onPlot, styles, defaultStyle, styleRevision, onError, initialState, onStateChange, locked, onMenu } = props;
  const toast = useToast();
  const [info, setInfo] = useState<FileInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [spec, setSpec] = useState<PlotSpec>(initialState?.spec ?? {});
  const [preset, setPreset] = useState<string | null>(initialState?.preset ?? null);
  const [override, setOverride] = useState<JsonObject>(initialState?.override ?? {});
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);

  // Keep the App informed of the unsaved settings and the file version they were made on (they
  // move along with the tab).
  const onStateChangeRef = useRef(onStateChange);
  onStateChangeRef.current = onStateChange;
  const shownVersion = info ? info.version : initialState?.version;
  useEffect(() => {
    onStateChangeRef.current?.({ spec, preset, override, version: shownVersion });
  }, [spec, preset, override, shownVersion]);
  // The settings as they are now, for code that runs later (a reload after a change on disk).
  const unsavedRef = useRef({ spec, preset, override });
  unsavedRef.current = { spec, preset, override };
  const [result, setResult] = useState<RenderResult | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [zoom, setZoom] = useState("fit");
  const [showInfo, setShowInfo] = useState(true);
  const renderSeq = useRef(0);

  const loadInfo = useCallback(async () => {
    try {
      setInfo(await api.file(path));
      setLoadError(null);
    } catch (e) {
      setLoadError((e as Error).message);
    }
  }, [path]);

  useEffect(() => {
    loadInfo();
  }, [loadInfo]);

  // ---- the file changed on disk (another program rewrote it; see watch.ts)
  // The tab shows the new data by itself. Unsaved settings are dropped (they were made for the
  // data before), with a message. Reading can fail while the file is being written: the
  // previous version stays shown and it tries again, for up to GIVE_UP_AFTER.
  const disk = useDiskVersion("file", path);
  const saving = useRef(false); // our own Save view / Remove saved view: not a change from outside
  const [diskNote, setDiskNote] = useState<{ kind: "updated" | "updating" | "gone" | "failed"; text: string } | null>(null);
  const failing = useRef<{ version: string; since: number } | null>(null);
  const [retry, setRetry] = useState(0);
  // Every version this tab has shown. A check that ran before our own save answers with the
  // version before it; that is old news, not a change.
  const shownVersions = useRef(new Set<string>());
  if (info?.version) shownVersions.current.add(info.version);

  const dropUnsaved = useCallback(
    (shown: FileInfo, why: string) => {
      const { spec, preset, override } = unsavedRef.current;
      const unsaved = Object.keys(spec).length > 0 || !isEmptyObject(override) || (preset !== null && preset !== (shown.style_name ?? null));
      if (!unsaved) return;
      setSpec({});
      setPreset(null);
      setOverride({});
      toast(`${baseName(path)} ${why}, so your unsaved plot settings were dropped.`, "warning");
    },
    [path, toast],
  );

  useEffect(() => {
    if (!info || saving.current) return;
    if (disk.error) {
      setDiskNote({ kind: "failed", text: `Can't check this file for changes: ${disk.error}` });
      return;
    }
    if (disk.version === undefined) return; // not checked yet
    if (disk.version === null) {
      setDiskNote({ kind: "gone", text: "The file is gone (deleted, moved, or being written again). This shows it as it was, and updates when it is back." });
      return;
    }
    if (shownVersions.current.has(disk.version)) {
      setDiskNote((n) => (n && n.kind !== "updated" ? null : n));
      return;
    }
    const version = disk.version;
    if (failing.current?.version !== version) failing.current = null;
    let cancelled = false;
    let again: number | undefined;
    api.file(path).then(
      (fresh) => {
        if (cancelled) return;
        failing.current = null;
        dropUnsaved(info, "was changed on disk and has been reloaded");
        setInfo(fresh);
        setDiskNote({ kind: "updated", text: `Updated ${new Date().toLocaleTimeString()}: the file was changed on disk.` });
      },
      (e) => {
        if (cancelled) return;
        failing.current ??= { version, since: Date.now() };
        if (Date.now() - failing.current.since < GIVE_UP_AFTER) {
          setDiskNote({ kind: "updating", text: "The file was changed on disk; reading the new version…" });
          again = window.setTimeout(() => setRetry((n) => n + 1), 1000);
        } else {
          setDiskNote({
            kind: "failed",
            text: `The file was changed on disk, but the new version can't be read: ${(e as Error).message} ` +
              "This shows the previous version; it updates when the file is written again.",
          });
        }
      },
    );
    return () => {
      cancelled = true;
      window.clearTimeout(again);
    };
  }, [disk, info, retry, path, dropUnsaved]);

  // A file that couldn't be opened (e.g. it was half written) is tried again when it changes.
  useEffect(() => {
    if (loadError && typeof disk.version === "string") loadInfo();
  }, [disk.version]); // eslint-disable-line react-hooks/exhaustive-deps

  // A tab moved here from another page brings its unsaved settings; if the file changed since
  // they were made, they no longer fit and are dropped.
  const checkedMoved = useRef(false);
  useEffect(() => {
    if (!info || checkedMoved.current) return;
    checkedMoved.current = true;
    const madeOn = initialState?.version;
    if (madeOn && info.version && madeOn !== info.version) dropUnsaved(info, "was changed on disk while this tab was being moved");
  }, [info, initialState, dropUnsaved]);

  // Re-render whenever the view settings change (debounced; stale responses are dropped).
  // Single numbers (values without axes) aren't plotted; a file with nothing else shows a list.
  const onlyNumbers = !!info && info.values.every((v) => v.axes.length === 0);

  useEffect(() => {
    if (!plotted || !info || onlyNumbers) return;
    const seq = ++renderSeq.current;
    const id = window.setTimeout(async () => {
      setBusy(true);
      try {
        const r = await api.render(path, spec, preset, isEmptyObject(override) ? null : override);
        if (seq === renderSeq.current) {
          setResult(r);
          setRenderError(null);
        }
      } catch (e) {
        if (seq === renderSeq.current) setRenderError((e as Error).message);
      } finally {
        if (seq === renderSeq.current) setBusy(false);
      }
    }, 120);
    return () => window.clearTimeout(id);
  }, [plotted, info, onlyNumbers, path, spec, preset, override, styleRevision]);

  const imgUrl = useMemo(() => {
    if (!result) return null;
    return URL.createObjectURL(new Blob([result.svg], { type: "image/svg+xml" }));
  }, [result]);
  useEffect(() => () => {
    if (imgUrl) URL.revokeObjectURL(imgUrl);
  }, [imgUrl]);

  const update = (patch: PlotSpec) => setSpec((s) => ({ ...s, ...patch }));

  // Export: the system's "Save as" dialog; where there is none (501), a browser download.
  const doExport = async (fmt: string) => {
    const style = isEmptyObject(override) ? null : override;
    try {
      let saved: string;
      let warnings: string[];
      try {
        const r = await api.saveFigure(path, spec, preset, style, fmt);
        if (r.path === null) return; // cancelled
        saved = r.path;
        warnings = r.warnings;
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 501)) throw e;
        toast(`${e.message}.`);
        saved = await api.exportFigure(path, spec, preset, style, fmt);
        warnings = lastDownloadWarnings;
      }
      if (fmt === "jpg")
        toast(`Saved ${saved}. JPG compresses with loss: thin lines and small text get blurred edges. ` +
              "For papers use PDF; for Word or slides use PNG.", "warning");
      else toast(`Saved ${saved}`);
      warnings.forEach((w) => toast(w, "error"));
    } catch (e) {
      onError((e as Error).message);
    }
  };

  // Save the view into the file. `overwrite`: even if the file changed since this tab loaded it.
  const saveToFile = async (overwrite = false) => {
    if (!result || !info) return;
    const { slices: _slices, ...savedSpec } = result.spec;
    void _slices;
    const newStyle = deepMerge(info.style ?? {}, override);
    saving.current = true;
    try {
      const updated = await api.saveFilePlot(path, {
        spec: savedSpec,
        style: isEmptyObject(newStyle) ? null : newStyle,
        style_name: preset ?? info.style_name ?? null,
        if_version: overwrite ? null : info.version,
      });
      setInfo(updated);
      setOverride({});
      setSpec({});
      toast("Saved this view into the file. It opens like this from now on, on any computer.");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.message.includes("changed since you opened it")) {
        setConfirm({
          title: "The file was changed",
          text:
            `${baseName(path)} was changed since this tab opened it, in another page or another program. ` +
            "Overwrite replaces its saved view with yours. Reload shows the file as it is now (your unsaved " +
            "changes here are dropped). Cancel keeps your changes here, unsaved.",
          action: "Overwrite",
          danger: true,
          onConfirm: () => saveToFile(true),
          secondary: {
            label: "Reload",
            onClick: async () => {
              setSpec({});
              setPreset(null);
              setOverride({});
              await loadInfo();
            },
          },
        });
      } else {
        onError((e as Error).message);
      }
    } finally {
      saving.current = false;
    }
  };

  const clearSaved = async () => {
    saving.current = true;
    try {
      setInfo(await api.saveFilePlot(path, { spec: null, style: null, style_name: null }));
      setSpec({});
      setPreset(null);
      setOverride({});
      toast("Removed the saved view from the file.");
    } catch (e) {
      onError((e as Error).message);
    } finally {
      saving.current = false;
    }
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
  if (!info) return <div className="file-view muted pad">Loading…</div>;

  const resolved = result?.spec;
  const hasSaved = !!(info.plot || info.style || info.style_name);

  return (
    <div className="file-view">
      {locked && (
        <div className="warn-box" role="status">
          🔒 {locked}
        </div>
      )}
      <div className="file-head" onContextMenu={onMenu}>
        <div>
          <h1>{info.title || info.name}</h1>
          <div className="muted small path" title={info.path}>
            {info.path}
          </div>
        </div>
        <div className="actions">
          {!plotted && (
            <button className="primary" onClick={onPlot}>
              Plot
            </button>
          )}
          <button onClick={() => api.reveal(info.path).catch((e) => onError(e.message))}>Show in folder</button>
        </div>
      </div>
      {diskNote && (
        <div className={`disk-note ${diskNote.kind}`} role="status">
          {diskNote.text}
        </div>
      )}

      {plotted && onlyNumbers && (
        <div className="numbers-only" role="status">
          <p>This file has only single numbers, so there is nothing to plot:</p>
          <ul>
            {info.values.map((v) => (
              <li key={v.name}>
                {v.label || v.name} = {v.text ?? "?"}
              </li>
            ))}
          </ul>
        </div>
      )}

      {plotted && !onlyNumbers && (
        <div className="plot-area">
          <PlotControls
            info={info}
            resolved={resolved}
            update={update}
            styles={styles}
            defaultStyle={defaultStyle}
            preset={result?.preset ?? preset}
            setPreset={setPreset}
            override={override}
            setOverride={setOverride}
          />
          <div className="figure-col">
            <div className="figure-toolbar">
              <label>
                Zoom{" "}
                <select value={zoom} onChange={(e) => setZoom(e.target.value)}>
                  {ZOOMS.map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
              {result && (
                <span className="muted small">
                  {result.size_mm[0]} × {result.size_mm[1]} mm
                </span>
              )}
              {busy && <span className="muted small">Rendering…</span>}
              <span className="spacer" />
              <span className="muted small">Export:</span>
              <button onClick={() => doExport("pdf")}>PDF</button>
              <button onClick={() => doExport("svg")}>SVG</button>
              <button onClick={() => doExport("png")}>PNG</button>
              <button onClick={() => doExport("jpg")} title="Blurs thin lines and text a little; prefer PDF or PNG">JPG</button>
            </div>
            {renderError && <div className="error-box">{renderError}</div>}
            {(() => {
              const notes = [...(info.warnings ?? []), ...(!renderError && result ? result.warnings : [])];
              return notes.length ? (
                <ul className="warn-box" aria-label="Notes about this plot">
                  {notes.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              ) : null;
            })()}
            <div className={"figure" + (zoom === "fit" ? " fit" : "")}>
              {imgUrl && result && (
                <img
                  src={imgUrl}
                  alt={`Plot of ${(resolved?.values ?? []).join(", ")} from ${info.name}`}
                  style={zoom === "fit" ? undefined : { width: result.size_mm[0] * MM_TO_PX * Number(zoom) }}
                />
              )}
            </div>
            <div className="save-row">
              <button
                onClick={() => saveToFile()}
                disabled={!result || !!locked}
                title={locked ?? "Store the plot settings and style changes inside the .lbd file"}
              >
                Save this view to the file
              </button>
              <button
                onClick={() => {
                  setSpec({});
                  setPreset(null);
                  setOverride({});
                }}
              >
                Reset
              </button>
              {hasSaved && (
                <button className="subtle" onClick={clearSaved}>
                  Remove saved view
                </button>
              )}
              {hasSaved && <span className="muted small">This file has a saved view.</span>}
            </div>
          </div>
        </div>
      )}

      <div className="info-toggle">
        <button className="link" onClick={() => setShowInfo((s) => !s)} aria-expanded={showInfo}>
          {showInfo ? "▾" : "▸"} File contents
        </button>
      </div>
      {showInfo && <FileDetails info={info} />}
      {confirm && <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />}
    </div>
  );
}

// ---- controls -------------------------------------------------------------------------

interface ControlsProps {
  info: FileInfo;
  resolved: PlotSpec | undefined;
  update: (p: PlotSpec) => void;
  styles: string[];
  defaultStyle: string;
  preset: string | null;
  setPreset: (p: string | null) => void;
  override: JsonObject;
  setOverride: (o: JsonObject) => void;
}

function PlotControls({ info, resolved, update, styles, defaultStyle, preset, setPreset, override, setOverride }: ControlsProps) {
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [showStyle, setShowStyle] = useState(false);
  const [showLabels, setShowLabels] = useState(false);
  const [showAnn, setShowAnn] = useState(false);
  const [annText, setAnnText] = useState("");
  const [annError, setAnnError] = useState<string | null>(null);
  const annotations = resolved?.annotations;

  useEffect(() => {
    setJsonText(isEmptyObject(override) ? "" : JSON.stringify(override, null, 2));
  }, [override]);

  useEffect(() => {
    setAnnText(annotations && annotations.length ? JSON.stringify(annotations, null, 2) : "");
  }, [JSON.stringify(annotations ?? [])]);

  if (!resolved) return <div className="controls muted small">Preparing…</div>;

  const kind = resolved.kind ?? "auto";
  const valuesByName = Object.fromEntries(info.values.map((v) => [v.name, v]));
  const selected = resolved.values ?? [];
  const first = valuesByName[selected[0]];
  const firstAxes = first?.axes ?? [];
  const anyComplex = selected.some((n) => valuesByName[n]?.complex);
  // values with exactly the same axes as the first one: usable point by point in scatter plots
  const sameShape = info.values.filter((v) => v.axes.length > 0 && v.axes.join(",") === firstAxes.join(","));
  const axisLabel = (name: string) => {
    const a = info.axes.find((x) => x.name === name);
    return a ? `${a.label}${a.unit ? ` (${a.unit})` : ""}` : name;
  };

  const toggleValue = (name: string, checked: boolean) => {
    const next = checked ? [...selected, name] : selected.filter((v) => v !== name);
    if (next.length) update({ values: next });
  };

  // Axes with one point are fixed parameters (not swept): they don't count as dimensions.
  const lengthOf = (axis: string) => info.axes.find((a) => a.name === axis)?.length ?? 0;
  const sweptAxes = (v: ValueInfo) => v.axes.filter((a) => lengthOf(a) > 1);
  /** Whether a value can be drawn as plot kind k (the same rule as the renderer). */
  const fits = (v: ValueInfo, k: string) => (k === "heatmap" ? sweptAxes(v).length >= 2 : v.axes.length > 0);
  const numbers = info.values.filter((v) => v.axes.length === 0);
  const withAxes = info.values.filter((v) => v.axes.length > 0);
  // Values that can join the plot: they share its horizontal axis (scatter: or its exact axes).
  const x = resolved.x;
  const joins = (v: ValueInfo) =>
    kind === "scatter" && !(x && firstAxes.includes(x)) ? v.axes.join(",") === firstAxes.join(",") : !!x && v.axes.includes(x);
  const here = withAxes.filter(joins);
  const elsewhere = withAxes.filter((v) => !joins(v));
  // Another value on its own: it brings its own axes, so the axis choices start afresh.
  const fresh: PlotSpec = { x: undefined, y: undefined, series: undefined, color: undefined, index: {} };
  const switchTo = (name: string) => update({ ...fresh, values: [name] });
  const chooseKind = (k: string) => {
    const now = valuesByName[selected[0]];
    const value = now && fits(now, k) ? undefined : info.values.find((v) => fits(v, k));
    update(value ? { ...fresh, kind: k as PlotSpec["kind"], values: [value.name] } : { kind: k as PlotSpec["kind"] });
  };
  const axisName = (v: ValueInfo) => v.axes.filter((a) => lengthOf(a) > 1).map((a) => info.axes.find((x) => x.name === a)?.label || a).join(" × ") || v.axes.join(", ");

  const figure = (override.figure ?? {}) as JsonObject;
  const setFigure = (key: string, val: string) => {
    const f = { ...figure };
    if (val === "") delete f[key];
    else f[key] = Number(val);
    const o = { ...override, figure: f };
    if (isEmptyObject(f)) delete (o as JsonObject).figure;
    setOverride(o);
  };

  const applyAnnotations = () => {
    if (!annText.trim()) {
      update({ annotations: [] });
      setAnnError(null);
      return;
    }
    try {
      const v = JSON.parse(annText);
      if (!Array.isArray(v) || v.some((x) => typeof x !== "object" || x === null || Array.isArray(x)))
        throw new Error('must be a JSON list of objects, e.g. [{"method": "axvline", "args": [7.0]}]');
      update({ annotations: v });
      setAnnError(null);
    } catch (e) {
      setAnnError((e as Error).message);
    }
  };

  const applyJson = () => {
    if (!jsonText.trim()) {
      setOverride({});
      setJsonError(null);
      return;
    }
    try {
      const v = JSON.parse(jsonText);
      if (typeof v !== "object" || v === null || Array.isArray(v)) throw new Error("must be a JSON object");
      setOverride(v);
      setJsonError(null);
    } catch (e) {
      setJsonError((e as Error).message);
    }
  };

  return (
    <div className="controls">
      <fieldset>
        <legend>
          Data <HelpLink page="viewer/plotting.html" topic="plot controls" />
        </legend>
        <label className="field">
          <span>Plot type</span>
          <select value={kind} onChange={(e) => chooseKind(e.target.value)}>
            <option value="curve">Curves</option>
            <option value="scatter">Scatter</option>
            <option value="heatmap">Heat map</option>
          </select>
        </label>

        {kind === "curve" || (kind === "scatter" && resolved.complex !== "iq") ? (
          <div className="field">
            <span>Values</span>
            <div className="checks">
              {here.map((v) => (
                <label key={v.name} className="check">
                  <input type="checkbox" checked={selected.includes(v.name)} onChange={(e) => toggleValue(v.name, e.target.checked)} />
                  {v.label}
                  <span className="muted small"> ({v.axes.join(", ")})</span>
                </label>
              ))}
            </div>
            {elsewhere.length > 0 && (
              <div className="value-group" aria-label="Values on other axes">
                <span className="muted small">On other axes (shown on their own):</span>
                {elsewhere.map((v) => (
                  <button key={v.name} className="link value-switch" onClick={() => switchTo(v.name)} title={`Plot ${v.label} instead`}>
                    {v.label} <span className="muted small">({axisName(v)})</span>
                  </button>
                ))}
              </div>
            )}
            {numbers.length > 0 && (
              <div className="value-group" aria-label="Single numbers">
                <span className="muted small">Numbers:</span>
                {numbers.map((v) => (
                  <span key={v.name} className="value-number">
                    {v.label || v.name} = {v.text ?? "?"}
                  </span>
                ))}
              </div>
            )}
          </div>
        ) : (
          <label className="field">
            <span>Value</span>
            <select value={selected[0] ?? ""} onChange={(e) => update({ values: [e.target.value] })}>
              {info.values
                .filter((v) => (kind === "heatmap" ? fits(v, "heatmap") : kind === "scatter" ? v.complex : fits(v, kind)))
                .map((v) => (
                  <option key={v.name} value={v.name}>
                    {v.label} ({v.axes.join(", ")})
                  </option>
                ))}
            </select>
          </label>
        )}

        {anyComplex && (
          <label className="field">
            <span>Complex data as</span>
            <select value={resolved.complex ?? "abs"} onChange={(e) => update({ complex: e.target.value })}>
              {COMPLEX_MODES.filter(([v]) => v !== "iq" || kind === "scatter").map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
        )}

        {kind === "scatter" && resolved.complex !== "iq" && (
          <label className="field">
            <span>Horizontal axis</span>
            <select value={resolved.x ?? ""} onChange={(e) => update({ x: e.target.value, index: {} })}>
              <optgroup label="Axes">
                {firstAxes.map((a) => (
                  <option key={a} value={a}>
                    {axisLabel(a)}
                  </option>
                ))}
              </optgroup>
              {sameShape.length > 0 && (
                <optgroup label="Values (point by point)">
                  {sameShape.map((v) => (
                    <option key={v.name} value={v.name}>
                      {v.label}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </label>
        )}
        {kind === "scatter" && (
          <label className="field">
            <span>Colour by</span>
            <select value={resolved.color ?? "none"} onChange={(e) => update({ color: e.target.value })}>
              <option value="none">— (series colours)</option>
              <optgroup label="Axes">
                {firstAxes.map((a) => (
                  <option key={a} value={a}>
                    {axisLabel(a)}
                  </option>
                ))}
              </optgroup>
              {sameShape.length > 0 && (
                <optgroup label="Values">
                  {sameShape.map((v) => (
                    <option key={v.name} value={v.name}>
                      {v.label}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </label>
        )}
        {kind !== "scatter" && firstAxes.length > 0 && (
          <label className="field">
            <span>Horizontal axis</span>
            <select value={resolved.x ?? ""} onChange={(e) => update({ x: e.target.value, y: undefined, series: undefined, index: {} })}>
              {firstAxes.map((a) => (
                <option key={a} value={a}>
                  {axisLabel(a)}
                </option>
              ))}
            </select>
          </label>
        )}
        {kind === "heatmap" && (
          <label className="field">
            <span>Vertical axis</span>
            <select value={resolved.y ?? ""} onChange={(e) => update({ y: e.target.value, index: {} })}>
              {firstAxes
                .filter((a) => a !== resolved.x)
                .map((a) => (
                  <option key={a} value={a}>
                    {axisLabel(a)}
                  </option>
                ))}
            </select>
          </label>
        )}
        {kind === "curve" && selected.length === 1 && firstAxes.some((a) => a !== resolved.x && lengthOf(a) > 1) && (
          <label className="field">
            <span>One curve per</span>
            <select value={resolved.series ?? "none"} onChange={(e) => update({ series: e.target.value, index: {} })}>
              <option value="none">— (single curve)</option>
              {firstAxes
                .filter((a) => a !== resolved.x && lengthOf(a) > 1) // a single-point axis would give one curve
                .map((a) => (
                  <option key={a} value={a}>
                    {axisLabel(a)}
                  </option>
                ))}
            </select>
          </label>
        )}

        {(resolved.slices ?? []).map((s) =>
          s.length === 1 ? (
            // a parameter that wasn't swept: nothing to choose
            <div key={s.axis} className="field">
              <span>
                {s.label} = {s.value ?? "?"} {s.unit} <span className="muted small">(fixed)</span>
              </span>
            </div>
          ) : (
            <SliceControl
              key={s.axis}
              path={info.path}
              version={info.version}
              slice={s}
              onIndex={(i) => update({ index: { ...(resolved.index ?? {}), [s.axis]: i } })}
            />
          ),
        )}

        <div className="field inline">
          <label className="check">
            <input type="checkbox" checked={resolved.x_scale === "log"} onChange={(e) => update({ x_scale: e.target.checked ? "log" : "linear" })} />
            Log x
          </label>
          <label className="check">
            <input type="checkbox" checked={resolved.y_scale === "log"} onChange={(e) => update({ y_scale: e.target.checked ? "log" : "linear" })} />
            Log y
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>
          <button className="link" onClick={() => setShowLabels((s) => !s)} aria-expanded={showLabels}>
            {showLabels ? "▾" : "▸"} Labels
          </button>
        </legend>
        {showLabels && (
          <>
            {(
              [
                ["title", "Title"],
                ["x_label", "Horizontal axis label"],
                ["y_label", "Vertical axis label"],
                ...(kind === "heatmap" || (kind === "scatter" && resolved.color) ? [["z_label", "Colour bar label"]] : []),
              ] as [keyof PlotSpec, string][]
            ).map(([key, label]) => (
              // keyed on the current value so Reset refreshes the uncontrolled input
              <label key={`${key}:${(resolved[key] as string | undefined) ?? ""}`} className="field">
                <span>{label}</span>
                <input
                  defaultValue={(resolved[key] as string | undefined) ?? ""}
                  placeholder="automatic"
                  onBlur={(e) => update({ [key]: e.target.value || undefined } as PlotSpec)}
                  onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
                />
              </label>
            ))}
            <p className="muted small">Units are added automatically.</p>
          </>
        )}
      </fieldset>

      <fieldset>
        <legend>
          Style <HelpLink page="styles/settings.html" topic="style settings" />
        </legend>
        <label className="field">
          <span>Preset</span>
          <select value={preset ?? defaultStyle} onChange={(e) => setPreset(e.target.value)}>
            {styles.map((s) => (
              <option key={s} value={s}>
                {s}
                {s === defaultStyle ? " (default)" : ""}
                {s === info.style_name ? " (file)" : ""}
              </option>
            ))}
          </select>
        </label>
        <div className="field inline">
          <label className="mini">
            Width mm
            <input type="number" min={10} max={1000} value={(figure.width_mm as number | undefined) ?? ""} placeholder="preset" onChange={(e) => setFigure("width_mm", e.target.value)} />
          </label>
          <label className="mini">
            Height mm
            <input type="number" min={10} max={1000} value={(figure.height_mm as number | undefined) ?? ""} placeholder="preset" onChange={(e) => setFigure("height_mm", e.target.value)} />
          </label>
          <label className="mini" title="Resolution of PNG and JPG exports (the preview is unaffected)">
            DPI (PNG/JPG)
            <input type="number" min={50} max={2400} step={50} value={(figure.dpi as number | undefined) ?? ""} placeholder="preset" onChange={(e) => setFigure("dpi", e.target.value)} />
          </label>
        </div>
        <button className="link" onClick={() => setShowStyle((s) => !s)} aria-expanded={showStyle}>
          {showStyle ? "▾" : "▸"} Style changes for this file (JSON)
        </button>
        {showStyle && (
          <div className="json-edit">
            <textarea
              value={jsonText}
              onChange={(e) => setJsonText(e.target.value)}
              rows={8}
              spellCheck={false}
              placeholder={'{\n  "figure": {"font": {"size_pt": 9}},\n  "quantities": {"S21.db": {"vmin": -20, "vmax": 0}}\n}'}
            />
            {jsonError && <div className="error-text small">{jsonError}</div>}
            <div className="row">
              <button onClick={applyJson}>Apply</button>
              <span className="muted small">Same keys as on the Styles page. Applied on top of the preset.</span>
            </div>
          </div>
        )}
        <button className="link" onClick={() => setShowAnn((s) => !s)} aria-expanded={showAnn}>
          {showAnn ? "▾" : "▸"} Annotations (JSON list){annotations && annotations.length ? ` · ${annotations.length}` : ""}
        </button>
        {showAnn && (
          <div className="json-edit">
            <textarea
              value={annText}
              onChange={(e) => setAnnText(e.target.value)}
              rows={8}
              spellCheck={false}
              placeholder={'[\n  {"method": "axvline", "args": [7.0], "kwargs": {"ls": ":"}},\n  {"method": "annotate", "args": ["dip"],\n   "kwargs": {"xy": [7.0, -15], "xytext": [0.6, 0.3], "textcoords": "axes fraction",\n              "arrowprops": {"arrowstyle": "->"}}},\n  {"patch": "Rectangle", "args": [[6.99, -20], 0.02, 10], "kwargs": {"fill": false}}\n]'}
            />
            {annError && <div className="error-text small">{annError}</div>}
            <div className="row">
              <button onClick={applyAnnotations}>Apply</button>
              <span className="muted small">
                matplotlib Axes methods or patches, in the units shown on the axes. <HelpLink page="styles/plot-settings.html" anchor="annotations" topic="annotations" />
              </span>
            </div>
          </div>
        )}
      </fieldset>
    </div>
  );
}

// ---- file details ---------------------------------------------------------------------------

// Axis values, fetched once per file version and axis (to find the point nearest a typed value).
const axisCache = new Map<string, Promise<AxisValues>>();
function axisValues(path: string, version: string | null, axis: string): Promise<AxisValues> {
  const key = `${path}\n${version}\n${axis}`;
  if (!axisCache.has(key)) {
    const p = api.axis(path, axis);
    p.catch(() => axisCache.delete(key)); // a failure is retried next time
    axisCache.set(key, p);
  }
  return axisCache.get(key)!;
}

/** The position on an axis that isn't drawn: a slider, and a box to type the axis value. A typed
 *  value goes to the nearest measured point; the box then shows that point's exact value. */
function SliceControl({ path, version, slice: s, onIndex }: { path: string; version: string | null; slice: Slice; onIndex: (i: number) => void }) {
  const shown = s.value === null ? "" : String(s.value);
  const [text, setText] = useState(shown);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => setText(shown), [shown]);

  const commit = async () => {
    if (text.trim() === shown) return;
    const wanted = Number(text.trim());
    if (text.trim() === "" || !Number.isFinite(wanted)) {
      setNote("Type a number");
      setText(shown);
      return;
    }
    try {
      const { values } = await axisValues(path, version, s.axis);
      let best = -1;
      values.forEach((v, i) => {
        if (v !== null && (best < 0 || Math.abs(v - wanted) < Math.abs((values[best] as number) - wanted))) best = i;
      });
      if (best < 0) return setNote("This axis has no numbers");
      const finite = values.filter((v): v is number => v !== null);
      const outside = wanted < Math.min(...finite) || wanted > Math.max(...finite);
      setNote(outside ? `${wanted} is outside the axis (${Math.min(...finite)} … ${Math.max(...finite)}): nearest end` : null);
      setText(String(values[best]));
      if (best !== s.index) onIndex(best);
    } catch (e) {
      setNote((e as Error).message);
      setText(shown);
    }
  };

  return (
    <div className="field">
      <label className="slice-head">
        <span>
          {s.label}
          <span className="muted small"> (point {s.index + 1} of {s.length})</span>
        </span>
        <span className="slice-value">
          <input
            aria-label={`${s.label} value`}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          />
          {s.unit}
        </span>
      </label>
      <input
        type="range"
        aria-label={`${s.label} position`}
        min={0}
        max={s.length - 1}
        value={s.index}
        onChange={(e) => {
          setNote(null);
          onIndex(Number(e.target.value));
        }}
      />
      {note && <span className="muted small">{note}</span>}
    </div>
  );
}

function FileDetails({ info }: { info: FileInfo }) {
  return (
    <div className="details">
      {info.description && <p>{info.description}</p>}
      <dl className="props">
        <dt>Created</dt>
        <dd>{info.created ?? "—"}</dd>
        <dt>Written by</dt>
        <dd>{info.writer ?? "—"}</dd>
        <dt>Size</dt>
        <dd>{formatBytes(info.size)}</dd>
        <dt>Format</dt>
        <dd>LBD {info.lbd_version}</dd>
        {info.matplotlib && (
          <>
            <dt>View saved with</dt>
            <dd>matplotlib {info.matplotlib}</dd>
          </>
        )}
      </dl>

      <h3>Values</h3>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Label</th>
            <th>Unit</th>
            <th>Axes</th>
            <th>Shape</th>
            <th>Type</th>
          </tr>
        </thead>
        <tbody>
          {info.values.map((v) => (
            <tr key={v.name}>
              <td><code>{v.name}</code></td>
              <td>{v.label}</td>
              <td>{v.unit}</td>
              <td>{v.axes.join(", ") || "—"}</td>
              <td className="num">{v.shape.length ? v.shape.join(" × ") : `single number: ${v.text ?? "?"}`}</td>
              <td>{v.dtype}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Axes</h3>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Label</th>
            <th>Unit</th>
            <th>Points</th>
            <th>From</th>
            <th>To</th>
          </tr>
        </thead>
        <tbody>
          {info.axes.map((a) => (
            <tr key={a.name}>
              <td><code>{a.name}</code></td>
              <td>{a.label}</td>
              <td>{a.unit}</td>
              <td className="num">{a.length}</td>
              <td className="num">{fmt(a.min)}</td>
              <td className="num">{fmt(a.max)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Metadata</h3>
      {isEmptyObject(info.meta) ? <p className="muted">None</p> : <MetaTree value={info.meta} />}
    </div>
  );
}

function fmt(x: number | null): string {
  if (x == null) return "—";
  return Math.abs(x) >= 1e5 || (x !== 0 && Math.abs(x) < 1e-3) ? x.toExponential(4) : String(Number(x.toPrecision(6)));
}

function MetaTree({ value }: { value: JsonObject }) {
  return (
    <ul className="meta">
      {Object.entries(value).map(([k, v]) => (
        <li key={k}>
          <span className="meta-key">{k}</span>
          {isObject(v) && !(v as JsonObject).array ? <MetaTree value={v as JsonObject} /> : <span className="meta-val">{metaText(v)}</span>}
        </li>
      ))}
    </ul>
  );
}

function isObject(v: Json): boolean {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function metaText(v: Json): string {
  if (isObject(v) && (v as JsonObject).array) {
    const o = v as JsonObject;
    return `array ${(o.shape as number[]).join(" × ")} (${o.dtype}): ${JSON.stringify(o.preview)} …`;
  }
  return typeof v === "string" ? v : JSON.stringify(v);
}

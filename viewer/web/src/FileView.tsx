import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, FileInfo, formatBytes, Json, JsonObject, lastDownloadWarnings, PlotSpec, RenderResult } from "./api";
import { deepMerge, isEmptyObject } from "./util";
import { useToast } from "./toast";
import { HelpLink } from "./help";

interface Props {
  path: string;
  plotted: boolean;
  onPlot: () => void;
  styles: string[];
  defaultStyle: string;
  styleRevision: number;
  onError: (msg: string) => void;
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

export default function FileView({ path, plotted, onPlot, styles, defaultStyle, styleRevision, onError }: Props) {
  const toast = useToast();
  const [info, setInfo] = useState<FileInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [spec, setSpec] = useState<PlotSpec>({});
  const [preset, setPreset] = useState<string | null>(null);
  const [override, setOverride] = useState<JsonObject>({});
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

  // Re-render whenever the view settings change (debounced; stale responses are dropped).
  useEffect(() => {
    if (!plotted || !info) return;
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
  }, [plotted, info, path, spec, preset, override, styleRevision]);

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

  const saveToFile = async () => {
    if (!result || !info) return;
    const { slices: _slices, ...savedSpec } = result.spec;
    void _slices;
    const newStyle = deepMerge(info.style ?? {}, override);
    try {
      const updated = await api.saveFilePlot(path, {
        spec: savedSpec,
        style: isEmptyObject(newStyle) ? null : newStyle,
        style_name: preset ?? info.style_name ?? null,
      });
      setInfo(updated);
      setOverride({});
      setSpec({});
      toast("Saved this view into the file. It opens like this from now on, on any computer.");
    } catch (e) {
      onError((e as Error).message);
    }
  };

  const clearSaved = async () => {
    try {
      setInfo(await api.saveFilePlot(path, { spec: null, style: null, style_name: null }));
      setSpec({});
      setPreset(null);
      setOverride({});
      toast("Removed the saved view from the file.");
    } catch (e) {
      onError((e as Error).message);
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
      <div className="file-head">
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

      {plotted && (
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
              <button onClick={saveToFile} disabled={!result} title="Store the plot settings and style changes inside the .lbd file">
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
          <select value={kind} onChange={(e) => update({ kind: e.target.value as PlotSpec["kind"] })}>
            {kind === "scalar" && <option value="scalar">Single number</option>}
            <option value="curve">Curves</option>
            <option value="scatter">Scatter</option>
            <option value="heatmap">Heat map</option>
          </select>
        </label>

        {kind === "curve" || (kind === "scatter" && resolved.complex !== "iq") ? (
          <div className="field">
            <span>Values</span>
            <div className="checks">
              {info.values
                .filter((v) => v.axes.length > 0)
                .map((v) => (
                  <label key={v.name} className="check">
                    <input type="checkbox" checked={selected.includes(v.name)} onChange={(e) => toggleValue(v.name, e.target.checked)} />
                    {v.label}
                    <span className="muted small"> ({v.axes.join(", ")})</span>
                  </label>
                ))}
            </div>
          </div>
        ) : (
          <label className="field">
            <span>Value</span>
            <select value={selected[0] ?? ""} onChange={(e) => update({ values: [e.target.value] })}>
              {info.values
                .filter((v) => (kind === "heatmap" ? v.axes.length >= 2 : kind === "scatter" ? v.complex : true))
                .map((v) => (
                  <option key={v.name} value={v.name}>
                    {v.label} ({v.axes.join(", ") || "scalar"})
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
        {kind !== "scalar" && kind !== "scatter" && firstAxes.length > 0 && (
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
        {kind === "curve" && selected.length === 1 && firstAxes.length >= 2 && (
          <label className="field">
            <span>One curve per</span>
            <select value={resolved.series ?? "none"} onChange={(e) => update({ series: e.target.value, index: {} })}>
              <option value="none">— (single curve)</option>
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

        {(resolved.slices ?? []).map((s) => (
          <label key={s.axis} className="field">
            <span>
              {s.label} = {s.value ?? "?"} {s.unit}
              <span className="muted small"> ({s.index + 1}/{s.length})</span>
            </span>
            <input
              type="range"
              min={0}
              max={s.length - 1}
              value={s.index}
              onChange={(e) => update({ index: { ...(resolved.index ?? {}), [s.axis]: Number(e.target.value) } })}
            />
          </label>
        ))}

        {kind !== "scalar" && (
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
        )}
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
              <td className="num">{v.shape.length ? v.shape.join(" × ") : "scalar"}</td>
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

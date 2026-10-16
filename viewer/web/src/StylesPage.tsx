import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, baseName, Json, JsonObject, StyleEntry } from "./api";
import { deepDiff, deepMerge } from "./util";
import { useToast } from "./toast";
import { HelpLink } from "./help";

interface Props {
  previewPath: string | null;
  onChanged: () => void | Promise<void>;
}

interface SchemaNode {
  type?: string;
  enum?: string[];
  description?: string;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  anyOf?: SchemaNode[];
  $ref?: string;
  properties?: Record<string, SchemaNode>;
  items?: SchemaNode;
  additionalProperties?: unknown;
  default?: Json;
  title?: string;
}

// Section and field names shown in the form (the keys follow matplotlib's object tree).
const TITLES: Record<string, string> = {
  figure: "Figure",
  font: "Font",
  axes: "Axes",
  frame: "Frame (spines)",
  title: "Title",
  axis: "Axis (x and y)",
  xaxis: "x axis only",
  yaxis: "y axis only",
  label: "Label",
  ticks: "Major ticks",
  minor: "Minor ticks",
  grid: "Grid",
  legend: "Legend",
  colors: "Line colours (in order)",
  lines: "Lines",
  scatter: "Scatter markers",
  image: "Heat maps and colour scales",
  colorbar: "Colour bar",
  width_mm: "Width (mm)",
  height_mm: "Height (mm)",
  dpi: "PNG / raster resolution (dpi)",
  facecolor: "Background colour",
  family: "Font",
  size_pt: "Size (pt)",
  math: "Math font",
  linewidth_pt: "Line width (pt)",
  width_pt: "Line width (pt)",
  length_pt: "Length (pt)",
  pad_pt: "Padding (pt)",
  label_size_pt: "Number size (pt)",
  unit_format: "Unit in the label",
  auto_prefix: "Automatic unit prefixes (Hz → GHz)",
  mirror: "Also on the opposite side",
  marker_size_pt: "Marker size (pt)",
  edgewidth_pt: "Edge width (pt)",
  edgecolor: "Edge colour",
  size_pct: "Width (% of plot)",
  pad_pct: "Gap (% of plot)",
  cmap: "Colour map",
  max_entries: "Most entries shown",
  location: "Position",
  frame_legend: "Frame",
};

const CMAPS = ["viridis", "plasma", "inferno", "magma", "cividis", "turbo", "gray", "RdBu_r", "coolwarm", "PuOr", "twilight"];
const MARKERS = ["o", "s", "^", "v", "D", "x", "+", ".", "*"];
const LOCATIONS = ["best", "upper right", "upper left", "lower left", "lower right", "right", "center right", "center left", "upper center", "lower center", "center"];
// Fonts: filled from the server (only fonts installed on this computer, plus generic families).
const CHOICES: Record<string, string[]> = { cmap: CMAPS, family: ["sans-serif", "serif"], marker: MARKERS, location: LOCATIONS };

function title(key: string): string {
  if (TITLES[key]) return TITLES[key];
  const s = key.replace(/_pt$/, " (pt)").replace(/_mm$/, " (mm)").replace(/_pct$/, " (%)").replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export default function StylesPage({ previewPath, onChanged }: Props) {
  const toast = useToast();
  const [list, setList] = useState<StyleEntry[]>([]);
  const [selected, setSelected] = useState<string>("default");
  const [defaults, setDefaults] = useState<JsonObject | null>(null);
  const [schema, setSchema] = useState<JsonObject | null>(null);
  const [saved, setSaved] = useState<JsonObject | null>(null); // resolved, as stored
  const [working, setWorking] = useState<JsonObject | null>(null);
  const [, setFontCount] = useState(0);
  const [rawOpen, setRawOpen] = useState(false);
  const [rawText, setRawText] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const reloadList = useCallback(async () => setList(await api.styles()), []);

  useEffect(() => {
    reloadList().catch((e) => toast(`Can't load the styles: ${(e as Error).message}`, "error"));
    api
      .styleDefaults()
      .then((d) => {
        setDefaults(d.defaults);
        setSchema(d.schema);
      })
      .catch((e) => toast(`Can't load the style settings: ${(e as Error).message}`, "error"));
    api
      .fonts()
      .then((f) => {
        CHOICES.family = [...f.generic, ...f.installed];
        setFontCount(f.installed.length); // re-render the font fields with the list
      })
      .catch((e) => toast(`Can't list the installed fonts: ${(e as Error).message}`, "error"));
  }, [reloadList, toast]);

  useEffect(() => {
    api
      .style(selected)
      .then((s) => {
        setSaved(s.resolved);
        setWorking(s.resolved);
        s.warnings.forEach((w) => toast(w, "error"));
      })
      .catch((e) => toast(e.message, "error"));
  }, [selected, toast]);

  const dirty = useMemo(() => JSON.stringify(saved) !== JSON.stringify(working), [saved, working]);
  const entry = list.find((s) => s.name === selected);

  // Live preview with the unsaved changes, using the open file.
  useEffect(() => {
    if (!previewPath || !working || !saved) return;
    let cancelled = false;
    const id = window.setTimeout(async () => {
      try {
        const r = await api.render(previewPath, null, selected, deepDiff(working, saved));
        if (!cancelled) {
          setPreview(URL.createObjectURL(new Blob([r.svg], { type: "image/svg+xml" })));
          setPreviewError(null);
        }
      } catch (e) {
        if (!cancelled) setPreviewError((e as Error).message);
      }
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(id);
    };
  }, [previewPath, working, saved, selected]);
  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);

  if (!defaults || !schema || !working) return <div className="pad muted">Loading…</div>;

  const defs = (schema.$defs ?? {}) as Record<string, SchemaNode>;

  const save = async (name = selected) => {
    try {
      await api.saveStyle(name, deepDiff(working, defaults));
      await reloadList();
      if (name !== selected) setSelected(name);
      else setSaved(working);
      await onChanged();
      toast(`Saved style "${name}"`);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const askName = (suggestion: string): string | null => {
    const name = window.prompt("Name for the style:", suggestion)?.trim();
    if (!name) return null;
    if (list.some((s) => s.name === name)) {
      toast(`A style named "${name}" already exists`, "error");
      return null;
    }
    return name;
  };

  const createNew = async () => {
    const name = askName("my style");
    if (!name) return;
    try {
      await api.saveStyle(name, {});
      await reloadList();
      setSelected(name);
      await onChanged();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const duplicate = () => {
    const name = askName(`${selected} copy`);
    if (name) save(name);
  };

  const remove = async () => {
    const msg = entry?.builtin
      ? `Reset "${selected}" to its built-in settings?`
      : `Delete the style "${selected}"? Files that name it will use the default style instead.`;
    if (!window.confirm(msg)) return;
    try {
      await api.deleteStyle(selected);
      await reloadList();
      if (!entry?.builtin) setSelected("default");
      else {
        const s = await api.style(selected);
        setSaved(s.resolved);
        setWorking(s.resolved);
      }
      await onChanged();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const makeDefault = async () => {
    try {
      await api.setDefaultStyle(selected);
      await reloadList();
      await onChanged();
      toast(`"${selected}" is now the default style`);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const exportStyle = async (format: "lbd" | "mpl") => {
    if (dirty) toast("Exporting the saved version; save your changes first to include them.", "info");
    try {
      const name = await api.exportStyle(selected, format);
      toast(`Downloaded ${name}`);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const importFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const suggestion = file.name.replace(/\.lbd\.json$/i, "").replace(/\.json$/i, "");
    const name = askName(suggestion);
    if (!name) return;
    try {
      await api.importStyle(name, await file.text());
      await reloadList();
      setSelected(name);
      await onChanged();
      toast(`Imported "${name}"`);
    } catch (err) {
      toast((err as Error).message, "error");
    }
  };

  const setAt = (path: string[], value: Json | undefined) => {
    const next = structuredClone(working);
    let node = next as JsonObject;
    for (const p of path.slice(0, -1)) {
      if (typeof node[p] !== "object" || node[p] === null || Array.isArray(node[p])) node[p] = {};
      node = node[p] as JsonObject;
    }
    const last = path[path.length - 1];
    if (value === undefined) delete node[last];
    else node[last] = value;
    setWorking(next);
  };

  const styleDef = schema as unknown as SchemaNode;
  const figureDef = resolveRef(styleDef.properties!.figure, defs);

  return (
    <div className="styles-page">
      <aside className="style-list">
        <div className="panel-head">
          <h2>
            Styles <HelpLink page="viewer/styles-page.html" topic="the Styles page" />
          </h2>
          <div className="actions">
            <button onClick={createNew}>+ New</button>
            <button onClick={() => fileInput.current?.click()} title="Add a .lbd.json style file as a preset">
              Import…
            </button>
            <input ref={fileInput} type="file" accept=".json,application/json" hidden onChange={importFile} />
          </div>
        </div>
        <ul>
          {list.map((s) => (
            <li key={s.name}>
              <button className={s.name === selected ? "active" : ""} onClick={() => setSelected(s.name)}>
                <span>{s.name}</span>
                {s.default && <span className="badge accent">default</span>}
                {s.builtin && <span className="badge">{s.customized ? "built-in, changed" : "built-in"}</span>}
              </button>
            </li>
          ))}
        </ul>
        <p className="muted small">
          The <strong>default</strong> style is used for every file, unless the file names another style or you pick one
          while plotting. Python scripts use the same styles with <code>lbd.plot</code>.
        </p>
      </aside>

      <section className="style-editor">
        <div className="editor-head">
          <h2>
            {selected} <HelpLink page="styles/settings.html" topic="every style setting" />
          </h2>
          <div className="actions">
            <button className="primary" disabled={!dirty} onClick={() => save()}>
              Save
            </button>
            <button disabled={!dirty} onClick={() => setWorking(saved)}>
              Discard changes
            </button>
            <button onClick={duplicate}>Duplicate</button>
            {!entry?.default && <button onClick={makeDefault}>Make default</button>}
            <button onClick={() => exportStyle("lbd")} title="Download this style as a file to share or keep with your data">
              Export .lbd.json
            </button>
            <button
              onClick={() => exportStyle("mpl")}
              title="matplotlib's own style format: plt.style.use('file.mplstyle'). LBD-only settings (unit format, unit prefixes, fixed scales, colour bar size, scatter size) are not included."
            >
              Export .mplstyle
            </button>
            {(!entry?.builtin || entry.customized) && (
              <button className="subtle" onClick={remove}>
                {entry?.builtin ? "Reset" : "Delete"}
              </button>
            )}
          </div>
        </div>

        <div className="editor-body">
          <div className="form">
            <label className="field">
              <span>Description</span>
              <input
                value={String(working.description ?? "")}
                placeholder="e.g. Thesis figures, single column"
                onChange={(e) => setAt(["description"], e.target.value)}
              />
            </label>

            <Group
              name="figure"
              node={figureDef}
              defs={defs}
              value={working.figure as JsonObject}
              path={["figure"]}
              setAt={setAt}
              depth={0}
            />

            <details className="group" open>
              <summary>Fixed scales per quantity</summary>
              <p className="muted small">
                Use the same colour range (or vertical range for curves) for a quantity in every file, so figures from
                different files and years can be compared. The name is a value name (e.g. <code>temperature</code>), or a
                value name plus how complex data is shown (e.g. <code>S21.db</code>). Limits are in the value&apos;s own
                unit.{" "}
                <HelpLink page="styles/scales-and-units.html" anchor="fixed-scales-per-quantity" topic="fixed scales per quantity" />
              </p>
              <Quantities value={(working.quantities as JsonObject) ?? {}} onChange={(q) => setAt(["quantities"], q)} />
            </details>

            <button
              className="link"
              onClick={() => (setRawText(JSON.stringify(deepDiff(working, defaults), null, 2)), setRawOpen((o) => !o))}
              aria-expanded={rawOpen}
            >
              {rawOpen ? "▾" : "▸"} Edit as JSON (only the settings that differ from the built-in defaults)
            </button>
            {rawOpen && (
              <div className="json-edit">
                <textarea value={rawText} onChange={(e) => setRawText(e.target.value)} rows={14} spellCheck={false} />
                <button
                  onClick={() => {
                    try {
                      const parsed = JSON.parse(rawText || "{}");
                      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
                        toast("The JSON must be an object, e.g. {\"figure\": {\"width_mm\": 120}}", "error");
                        return;
                      }
                      setWorking(deepMerge(defaults, parsed));
                    } catch (e) {
                      toast(`Invalid JSON: ${(e as Error).message}`, "error");
                    }
                  }}
                >
                  Apply JSON
                </button>
              </div>
            )}
          </div>

          <div className="preview">
            <h3>Preview</h3>
            {!previewPath && <p className="muted small">Open a data file on the Data page to preview the style with it.</p>}
            {previewPath && <p className="muted small">{baseName(previewPath)} {dirty && "· unsaved changes"}</p>}
            {previewError && <div className="error-box">{previewError}</div>}
            {previewPath && preview && <img src={preview} alt="Preview of the style" />}
          </div>
        </div>
      </section>
    </div>
  );
}

// ---- schema-driven form -----------------------------------------------------------------

function resolveRef(node: SchemaNode | undefined, defs: Record<string, SchemaNode>): SchemaNode {
  if (!node) return {};
  if (node.$ref) return defs[node.$ref.split("/").pop()!] ?? {};
  const ref = node.anyOf?.find((x) => x.$ref)?.$ref;
  if (ref) return defs[ref.split("/").pop()!] ?? {};
  return node;
}

/** The primitive part of a possibly-nullable schema node: {type, enum, limits}, and whether null is allowed. */
function primitive(node: SchemaNode): { base: SchemaNode; nullable: boolean } {
  if (node.anyOf) {
    const base = node.anyOf.find((x) => x.type !== "null") ?? {};
    return { base: { ...base, description: node.description }, nullable: node.anyOf.some((x) => x.type === "null") };
  }
  return { base: node, nullable: false };
}

interface GroupProps {
  name: string;
  node: SchemaNode;
  defs: Record<string, SchemaNode>;
  value: JsonObject;
  path: string[];
  setAt: (path: string[], value: Json | undefined) => void;
  depth: number;
}

/** A section of the style (Figure, Axes, Frame, …) with its fields and sub-sections. */
function Group({ name, node, defs, value, path, setAt, depth }: GroupProps) {
  const props = node.properties ?? {};
  const fields = Object.entries(props).filter(([, n]) => !isGroup(n, defs) && !isOverride(n));
  const groups = Object.entries(props).filter(([, n]) => isGroup(n, defs) || isOverride(n));
  return (
    <details className={`group depth-${depth}`} open={depth < 2}>
      <summary>{title(name)}</summary>
      {fields.length > 0 && (
        <div className="group-fields">
          {fields.map(([key, n]) =>
            key === "colors" ? (
              <div key={key} className="field wide">
                <span>{title(key)}</span>
                <ColorCycle value={(value?.[key] as string[]) ?? []} onChange={(c) => setAt([...path, key], c)} />
              </div>
            ) : (
              <Field key={key} name={key} schema={n} value={value?.[key]} onChange={(v) => setAt([...path, key], v)} />
            ),
          )}
        </div>
      )}
      {groups.map(([key, n]) =>
        isOverride(n) ? (
          <AxisOverride
            key={key}
            name={key}
            axisNode={resolveRef(props.axis, defs)}
            defs={defs}
            inherited={(value?.axis as JsonObject) ?? {}}
            value={(value?.[key] as JsonObject) ?? {}}
            onChange={(v) => setAt([...path, key], v)}
          />
        ) : (
          <Group
            key={key}
            name={key}
            node={resolveRef(n, defs)}
            defs={defs}
            value={(value?.[key] as JsonObject) ?? {}}
            path={[...path, key]}
            setAt={setAt}
            depth={depth + 1}
          />
        ),
      )}
    </details>
  );
}

function isGroup(n: SchemaNode, defs: Record<string, SchemaNode>): boolean {
  return !!resolveRef(n, defs).properties && !!(n.$ref || n.anyOf?.some((x) => x.$ref));
}

/** xaxis / yaxis: free objects holding only the settings that differ from `axis`. */
function isOverride(n: SchemaNode): boolean {
  return n.type === "object" && !n.properties && !n.$ref;
}

function AxisOverride(props: {
  name: string;
  axisNode: SchemaNode;
  defs: Record<string, SchemaNode>;
  inherited: JsonObject;
  value: JsonObject;
  onChange: (v: JsonObject) => void;
}) {
  const { name, axisNode, defs, inherited, value, onChange } = props;
  const set = (section: string, key: string, v: Json | undefined) => {
    const next = structuredClone(value);
    const sec = { ...((next[section] as JsonObject) ?? {}) };
    if (v === undefined) delete sec[key];
    else sec[key] = v;
    if (Object.keys(sec).length) next[section] = sec;
    else delete next[section];
    onChange(next);
  };
  const count = Object.values(value).reduce<number>((n, s) => n + Object.keys((s as JsonObject) ?? {}).length, 0);
  return (
    <details className="group override">
      <summary>
        {title(name)} {count > 0 && <span className="badge accent">{count} changed</span>}
      </summary>
      <p className="muted small">
        Empty fields use the “Axis (x and y)” settings. Fill in only what should differ for the {name === "xaxis" ? "x" : "y"}{" "}
        axis.
      </p>
      {Object.entries(axisNode.properties ?? {}).map(([section, sn]) => {
        const sec = resolveRef(sn, defs);
        return (
          <fieldset key={section}>
            <legend>{title(section)}</legend>
            <div className="group-fields">
              {Object.entries(sec.properties ?? {}).map(([key, n]) => (
                <Field
                  key={key}
                  name={key}
                  schema={n}
                  value={((value[section] as JsonObject) ?? {})[key]}
                  inherited={((inherited[section] as JsonObject) ?? {})[key]}
                  onChange={(v) => set(section, key, v)}
                />
              ))}
            </div>
          </fieldset>
        );
      })}
      {count > 0 && (
        <button className="link" onClick={() => onChange({})}>
          Use the shared axis settings again
        </button>
      )}
    </details>
  );
}

interface FieldProps {
  name: string;
  schema: SchemaNode;
  value: Json | undefined;
  onChange: (v: Json | undefined) => void;
  inherited?: Json | undefined; // set for override fields: empty = inherit
}

function Field({ name, schema, value, onChange, inherited }: FieldProps) {
  const { base, nullable } = primitive(schema);
  const label = title(name);
  const help = base.description;
  const overriding = inherited !== undefined;
  const placeholder = overriding ? `${fmt(inherited)} (shared)` : nullable ? "automatic" : undefined;

  if (base.type === "boolean") {
    if (overriding) {
      return (
        <label className="field" title={help}>
          <span>{label}</span>
          <select value={value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value === "true")}>
            <option value="">{`(shared: ${inherited ? "yes" : "no"})`}</option>
            <option value="true">yes</option>
            <option value="false">no</option>
          </select>
        </label>
      );
    }
    return (
      <label className="field check" title={help}>
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
        {label}
      </label>
    );
  }
  if (base.enum) {
    return (
      <label className="field" title={help}>
        <span>{label}</span>
        <select value={value === undefined || value === null ? "" : String(value)} onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value)}>
          {overriding && <option value="">{`(shared: ${fmt(inherited)})`}</option>}
          {base.enum.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (base.type === "number" || base.type === "integer") {
    return (
      <label className="field" title={help}>
        <span>{label}</span>
        <input
          type="number"
          step={base.type === "integer" ? 1 : "any"}
          min={base.minimum ?? base.exclusiveMinimum}
          max={base.maximum ?? base.exclusiveMaximum}
          value={value === undefined || value === null ? "" : String(value)}
          placeholder={placeholder}
          onChange={(e) => {
            if (e.target.value === "") onChange(overriding ? undefined : nullable ? null : value ?? null);
            else onChange(Number(e.target.value));
          }}
        />
        {help && !overriding && <small className="muted">{help}</small>}
      </label>
    );
  }
  const choices = CHOICES[name];
  const listId = choices ? `choices-${name}` : undefined;
  return (
    <label className="field" title={help}>
      <span>{label}</span>
      <input
        list={listId}
        value={value === undefined || value === null ? "" : String(value)}
        placeholder={placeholder}
        onChange={(e) => onChange(overriding && e.target.value === "" ? undefined : e.target.value)}
      />
      {choices && (
        <datalist id={listId}>
          {choices.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
      )}
      {help && !overriding && <small className="muted">{help}</small>}
    </label>
  );
}

function fmt(v: Json | undefined): string {
  if (v === null || v === undefined) return "automatic";
  if (typeof v === "boolean") return v ? "yes" : "no";
  return String(v);
}

function ColorCycle({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="colors">
      {value.map((c, i) => (
        <span key={i} className="color-item">
          <input type="color" value={c} aria-label={`Colour ${i + 1}`} onChange={(e) => onChange(value.map((x, j) => (j === i ? e.target.value : x)))} />
          <button className="icon subtle" aria-label={`Remove colour ${i + 1}`} disabled={value.length <= 1} onClick={() => onChange(value.filter((_, j) => j !== i))}>
            ×
          </button>
        </span>
      ))}
      <button onClick={() => onChange([...value, "#000000"])}>+ Colour</button>
    </div>
  );
}

// Unit prefixes a quantity can be fixed to (lbd.plot.units.PREFIXES).
const PREFIXES = ["f", "p", "n", "µ", "m", "c", "d", "k", "M", "G", "T", "P", "a", "da", "h", "E", "z", "y", "Z", "Y", "q", "r", "R", "Q"];

function Quantities({ value, onChange }: { value: JsonObject; onChange: (v: JsonObject) => void }) {
  const rows = Object.entries(value) as [string, JsonObject][];
  const setRow = (oldKey: string, newKey: string, q: JsonObject) => {
    const out: JsonObject = {};
    for (const [k, v] of rows) out[k === oldKey ? newKey : k] = k === oldKey ? q : v;
    onChange(out);
  };
  const num = (s: string): Json => (s === "" ? null : Number(s));
  return (
    <div>
      {rows.length > 0 && (
        <table className="quantities">
          <thead>
            <tr>
              <th>Quantity</th>
              <th>Min</th>
              <th>Max</th>
              <th>Colour map</th>
              <th>Scale</th>
              <th title="Unit prefix: automatic, none, or a fixed one such as M for MHz">Prefix</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map(([k, q]) => (
              <tr key={k}>
                <td>
                  <input defaultValue={k} aria-label="Quantity name" onBlur={(e) => e.target.value && e.target.value !== k && setRow(k, e.target.value, q)} />
                </td>
                <td>
                  <input type="number" step="any" value={q.vmin == null ? "" : String(q.vmin)} aria-label="Minimum" onChange={(e) => setRow(k, k, { ...q, vmin: num(e.target.value) })} />
                </td>
                <td>
                  <input type="number" step="any" value={q.vmax == null ? "" : String(q.vmax)} aria-label="Maximum" onChange={(e) => setRow(k, k, { ...q, vmax: num(e.target.value) })} />
                </td>
                <td>
                  <input list="choices-cmap-q" value={String(q.cmap ?? "")} placeholder="style default" aria-label="Colour map" onChange={(e) => setRow(k, k, { ...q, cmap: e.target.value || null })} />
                </td>
                <td>
                  <select value={String(q.scale ?? "linear")} aria-label="Scale" onChange={(e) => setRow(k, k, { ...q, scale: e.target.value })}>
                    <option value="linear">linear</option>
                    <option value="log">log</option>
                  </select>
                </td>
                <td>
                  <select
                    value={q.prefix == null ? "__auto" : String(q.prefix)}
                    aria-label="Unit prefix"
                    onChange={(e) => setRow(k, k, { ...q, prefix: e.target.value === "__auto" ? null : e.target.value })}
                  >
                    <option value="__auto">automatic</option>
                    <option value="">none</option>
                    {PREFIXES.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <button className="icon subtle" aria-label={`Remove ${k}`} onClick={() => onChange(Object.fromEntries(rows.filter(([x]) => x !== k)))}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <datalist id="choices-cmap-q">
        {CMAPS.map((c) => (
          <option key={c} value={c} />
        ))}
      </datalist>
      <button
        onClick={() => {
          let n = 1;
          while (`quantity${n}` in value) n++;
          onChange({ ...value, [`quantity${n}`]: { vmin: null, vmax: null, cmap: null, scale: "linear", prefix: null } });
        }}
      >
        + Quantity
      </button>
    </div>
  );
}

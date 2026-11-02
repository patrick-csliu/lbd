// Typed client for the viewer's HTTP API (python/src/lbd/viewer/server.py).

import type { View, ViewSettings } from "./ExploreView";

export interface AppState {
  version: string;
  lbd_version: string;
  roots: string[];
  default_style: string;
  styles: string[];
  platform: string;
  config_dir: string;
  warnings: string[];
  /** where files opened from Explorer / Finder appear: the open viewer page, or a new browser tab */
  open_files_in: OpenFilesIn;
  open_data_in: OpenDataIn;
  /** the viewer's colours: "system" follows the operating system */
  theme: Theme;
  /** the Library's settings (config.LIBRARY_DEFAULTS) */
  library: LibrarySettings;
  /** memory for data (config.MEMORY_DEFAULTS, server memory_now) */
  memory: MemorySettings;
  /** this computer's user name (suggested first when labelling users) */
  login: string;
}

/** Memory for data (plan 6d): GB; null = automatic (reserve) / no maximum. */
export interface MemorySettings {
  reserve_gb: number | null;
  maximum_gb: number | null;
  summary_cache_gb: number;
  /** this computer, now (read-only) */
  total_gb: number | null;
  reserve_now_gb: number | null;
  room_gb: number | null;
}

/** A summary of a map bigger than memory being made (server: summaries.Job). */
export interface SummaryJob {
  path: string;
  what: string;
  fraction: number;
  seconds: number;
}

/** Save as CSV (server: export.py, /api/explore/export-csv): the choices of the dialog. */
export interface ExportChoice {
  numbers: "shown" | "stored" | "both";
  zoomed: boolean;
  layout: "rows" | "matrix";
  rows_are: "t" | "x";
  units: "stored" | "shown";
}

/** Without a path: a file name, the size, and the choices that can't be made (with why). */
export interface ExportPlan {
  path: string;
  options: { stored: string | null; both: string | null; zoomed: string | null };
  error: string | null;
  estimate: { bytes: number; rows: number; columns: number; files: number; warnings: string[]; big: boolean } | null;
}

/** A CSV file being written (or just finished). */
export interface ExportJob extends SummaryJob {
  id: string;
  paths: string[];
  state: "writing" | "done" | "cancelled" | "failed";
  error: string | null;
}

// ---- Library (server: library.py; keep in sync with /api/library in server.py) ----

/** A column of the Library's list. */
export type LibraryColumn =
  | "name"
  | "date"
  | "sweep"
  | "values"
  | "folder"
  | "size"
  | "file"
  | "modified"
  | "star"
  | "project"
  | "users"
  | "tags"
  | "comment"
  | "copies";

export interface LibrarySettings {
  /** read each data file's header for the list (off: names, sizes and file dates only) */
  read_headers: boolean;
  /** the notice about reading headers in cloud storage was seen */
  notice_seen: boolean;
  columns: LibraryColumn[];
  /** previews drawn without being asked: every file, the rows near the selection, or none ("all" needs read_headers) */
  previews: PreviewMode;
  /** the list as rows or as pictures */
  list_view: "list" | "pictures";
}

export type PreviewMode = "all" | "nearby" | "off";

/** A file's preview (GET /api/library/preview): the picture, or why there is none yet. */
export type Preview =
  | { picture: Blob; source: "automatic"; drawn_at: number }
  | { picture: Blob; source: "chosen"; chosen_at: number; changed_since: boolean }
  | { picture: null; state: "drawing" | "off" | "error" | "writing"; reason: string | null };

/** An Explore panel as shown, for its "Library preview" button. */
export interface PreviewPanel {
  spec: PlotSpec;
  settings: ViewSettings;
  stat: ReduceStat;
  view: View | null;
}

/** One file of the Library's list. */
export interface LibraryRow {
  path: string;
  root: string;
  folder: string; // relative to its open folder, "/"-separated ("" for the folder itself)
  name: string; // file name
  size: number;
  mtime: number;
  read: number; // 1: its header was read
  title: string;
  description: string;
  created: string | null; // as written in the file (ISO-8601 with offset)
  day: string; // YYYY-MM-DD in the file's own time zone (or of the file's date)
  date_from_file: number; // 1: no readable `created`: the file's modification date
  sweep: string; // e.g. "401×31"
  points: number;
  value_names: string;
  error: string | null; // why it couldn't be read
  id: string | null; // the measurement's identity (format 1.1), null for older files
  parent_id: string | null;
  copies: number; // other files with the same id
  conflict: number; // 1: they differ (the user decides)
  star: boolean;
  project: string | null;
  users: string[];
  tags: string[];
  comment: string;
  /** a file being written (name.lbd.writing): "measuring", or "stopped" before finishing; else null */
  writing: Writing;
}

/** The state of a file being written (name.lbd.writing); null for every other file. */
export type Writing = "measuring" | "stopped" | null;

/** A nested label (project, user or tag) with the number of files that have it or one inside it. */
export interface LabelNode {
  label: string; // the full label, e.g. "Qubit A/Device 3"
  name: string; // its last part
  count: number;
  children: LabelNode[];
}

/** Changes to the labels of some files (POST /api/library/labels). */
export interface LabelChanges {
  star?: boolean;
  project?: string; // "" removes it
  comment?: string;
  add_tags?: string[];
  remove_tags?: string[];
  add_users?: string[];
  remove_users?: string[];
}

/** The other files with a file's id (GET /api/library/same). */
export interface SameId {
  id: string | null;
  conflict: boolean;
  size?: number;
  mtime?: number;
  others: { path: string; size: number; mtime: number; title: string | null; differs: string[]; newer: boolean }[];
}

/** Labels whose file can't be found (GET /api/library/missing). */
export interface MissingLabels {
  folder: string;
  id: string | null;
  name: string;
  created: string | null;
  star: boolean;
  project: string | null;
  users: string[];
  tags: string[];
  comment: string;
}

export interface LibraryPage {
  rows: LibraryRow[];
  total: number;
  generation: number;
}

export interface LibraryFolder {
  path: string;
  name: string;
  count: number;
  children: LibraryFolder[];
}

export interface LibraryFacets {
  dates: { [year: string]: { [month: string]: { [day: string]: number } } };
  folders: LibraryFolder[];
  total: number; // files under all open folders (a folder opened inside another counted once)
  conflicts: number;
  projects: LabelNode[];
  users: LabelNode[];
  tags: LabelNode[];
  starred: number;
  missing: number;
  generation: number;
}

export interface LibraryStatus {
  indexing: boolean;
  done: number;
  total: number;
  errors: { path: string; error: string }[];
  scans: number;
  generation: number;
  notes?: string[]; // about labels (merged sync copies, …): told once
  /** automatic previews: drawn (current) of total files, how many are waiting or being drawn, the mode in effect */
  previews: { drawn: number; total: number; drawing: number; mode: PreviewMode };
}

export interface LibraryQuery {
  folder: string | null;
  q: string;
  date: string;
  sort: LibraryColumn;
  order: "asc" | "desc";
  project: string;
  tags: string[];
  users: string[];
  starred: boolean;
  conflicts: boolean;
}

export type OpenFilesIn = "viewer" | "browser-tab";
/** The workspace a data file opened from Explorer / Finder goes to. */
export type OpenDataIn = "explore" | "figure";
/** The viewer's main areas: find files, explore data, make figures. */
export type Workspace = "library" | "explore" | "figure";
export type Theme = "system" | "light" | "dark";

/** A command for this page from the viewer (lbd_viewer/pages.py). */
export interface PageCommand {
  id: number;
  kind: "open" | "show" | "transfer" | "transfer_done" | "transfer_cancelled" | "event" | "pages_changed";
  data: { [k: string]: Json };
}

export interface AckResult {
  granted: string[];
  elsewhere: { [path: string]: number }; // opened by another page meanwhile: path -> page number
  busy: string[]; // being moved between pages
}

export interface PageEntry {
  page: string;
  number: number;
  files: string[];
}

/** A tab's unsaved view settings; they travel with the tab when it moves to another page. */
export interface TabState {
  spec: PlotSpec;
  preset: string | null;
  override: JsonObject;
  /** The file's version these settings were made on: if the file changed since, they are dropped. */
  version?: string | null;
}

export interface DirListing {
  path: string;
  dirs: string[];
  files: { name: string; type: FileKind; size: number; mtime: number }[];
  errors: { name: string; error: string }[];
  /** Changes when the listing changes (a file added, removed or rewritten); see watch.ts. */
  signature: string;
}

/** /api/changes: the version of each file and the signature of each folder (null = gone), and the
 *  paths the server refused, with the reason. */
export interface Changes {
  files: { [path: string]: string | null };
  dirs: { [path: string]: string | null };
  errors: { [path: string]: string };
}

export interface SearchResult {
  root: string;
  query: string;
  results: { path: string; rel: string; type: FileKind; size: number; mtime: number }[];
  truncated: boolean;
  errors: { path: string; error: string }[];
}

export interface AxisInfo {
  name: string;
  unit: string;
  label: string;
  length: number;
  dtype: string;
  min: number | null;
  max: number | null;
  /** a text for each position (format 1.2), or null: numbered */
  elements?: string[] | null;
  /** "point": an axis of a value's data point (format 1.2); null: a sweep axis */
  role?: string | null;
  /** the axis group it is in (format 2.0): its points are listed with the group's other axes */
  group?: string | null;
}

export interface ValueInfo {
  name: string;
  unit: string;
  label: string;
  axes: string[];
  shape: number[];
  dtype: string;
  complex: boolean;
  /** the axes of one data point (format 1.2): the last of `axes` */
  point_axes?: string[];
  /** a single number (no axes), as text with a unit prefix: "21 µs" */
  text?: string;
}

export interface AxisValues {
  name: string;
  label: string;
  unit: string;
  values: (number | null)[];
}

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
export type JsonObject = { [k: string]: Json };

export interface FileInfo {
  path: string;
  name: string;
  title: string;
  description: string;
  created: string | null;
  writer: string | null;
  lbd_version: string;
  size: number | null;
  axes: AxisInfo[];
  values: ValueInfo[];
  /** axis groups (format 2.0): their axes, outer to inner */
  groups?: Record<string, string[]>;
  meta: JsonObject;
  plot: PlotSpec | null;
  style: JsonObject | null;
  style_name: string | null;
  /** matplotlib version that last wrote the saved view, if any */
  matplotlib: string | null;
  /** changes when the file is written; sent back when saving, so a changed file isn't overwritten */
  version: string | null;
  /** a file being written (name.lbd.writing): "measuring" or "stopped"; else null */
  writing?: Writing;
  warnings: string[];
}

export interface Slice {
  axis: string;
  index: number;
  length: number;
  label: string;
  unit: string;
  value: number | null;
  /** the position's text, for an axis with elements (format 1.2) */
  text?: string | null;
  elements?: string[] | null;
}

export type FileKind = "lbd" | "style" | "image";

/** What kind of file a path is, from its name (same rules as the server's scan.py). */
export function fileKind(path: string): FileKind {
  const p = path.toLowerCase();
  if (p.endsWith(".lbd") || p.endsWith(".lbd.writing")) return "lbd";
  if (p.endsWith(".lbd.json")) return "style";
  return "image";
}

export interface ImageInfo {
  path: string;
  name: string;
  file_size: number;
  modified: string;
  format: string | null;
  width: number | null;
  height: number | null;
  mode: string | null;
  bit_depth: number | null;
  frames: number;
  dpi: [number, number] | null;
  size_mm: [number, number] | null;
  text: Record<string, string>;
  note: string | null;
}

export interface StyleFileInfo {
  path: string;
  name: string;
  description: string;
  resolved: JsonObject;
  size: number;
  warnings: string[];
}

export interface PlotSpec {
  kind?: "auto" | "curve" | "heatmap" | "scatter";
  values?: string[];
  complex?: string;
  x?: string;
  y?: string;
  series?: string;
  color?: string;
  index?: Record<string, number>;
  x_scale?: "linear" | "log";
  y_scale?: "linear" | "log";
  title?: string;
  x_label?: string;
  y_label?: string;
  z_label?: string;
  /** Extra matplotlib drawing: {"method": "axvline", "args": [...], "kwargs": {...}} or {"patch": "Rectangle", ...} */
  annotations?: JsonObject[];
  slices?: Slice[];
}

export interface RenderResult {
  svg: string;
  spec: PlotSpec;
  preset: string;
  size_mm: [number, number];
  warnings: string[];
}

export interface StyleEntry {
  name: string;
  builtin: boolean;
  customized: boolean;
  default: boolean;
}

export interface StyleDetail {
  name: string;
  preset: JsonObject;
  resolved: JsonObject;
  builtin: boolean;
  customized: boolean;
  warnings: string[];
}

export interface SdkCommand {
  label: string;
  code: string;
}

export interface SdkLanguage {
  id: string;
  name: string;
  order: number;
  example_file: string;
  folder: string;
  available: boolean;
  requirements: string;
  install: SdkCommand[];
  check: string;
  upgrade: string;
  uninstall: string;
  example: string;
  notes: string[];
  error: string | null;
}

export interface SdkInfo {
  version: string;
  lbd_version: string;
  bundled: boolean;
  sdk_dir: string | null;
  languages: SdkLanguage[]; // discovered from each language's language.toml, in display order
}

const TOKEN_KEY = "lbd-token";

/** Take the session token from the URL (then hide it) or from this tab's storage. */
export function initToken(): string {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    try {
      sessionStorage.setItem(TOKEN_KEY, fromUrl);
    } catch {
      /* storage unavailable: keep the token in memory only */
    }
    url.searchParams.delete("token");
    window.history.replaceState(null, "", url.toString());
    token = fromUrl;
    return fromUrl;
  }
  try {
    token = sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    token = "";
  }
  if (!token && import.meta.env.DEV) token = "dev";
  return token;
}

let token = "";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown, params?: Record<string, string>): Promise<T> {
  const r = await send(method, path, body, params);
  return (await r.json()) as T;
}

/** A request whose answer isn't JSON (e.g. a picture); errors are thrown as ApiError like call(). */
async function send(method: string, path: string, body?: unknown, params?: Record<string, string>, signal?: AbortSignal): Promise<Response> {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  const r = await fetch(path + qs, {
    method,
    headers: { "X-LBD-Token": token, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j && typeof j.detail === "string") msg = j.detail;
      else if (j && j.detail) msg = JSON.stringify(j.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(r.status, msg);
  }
  return r;
}

// ---- Explore view (server: explore.py; keep in sync with /api/explore in server.py) ----

export type ReduceStat = "max" | "min" | "mean";

export interface ExploreOpen {
  session: string;
  spec: PlotSpec;
  kind: "curve" | "heatmap";
  preset: string;
  full: [[number, number], [number, number]]; // the whole data: x and y limits
  warnings: string[];
}

/** What a picture shows: its size, where the plot area is, and its axes' limits and scales. */
export interface ExploreFrameMeta {
  format: "raw" | "png";
  width: number; // image pixels
  height: number;
  dpr: number;
  plot: [number, number, number, number]; // plot area: left, top, width, height (image pixels)
  xlim: [number, number];
  ylim: [number, number];
  xscale: string; // "linear" or "log"
  yscale: string;
  full: [[number, number], [number, number]];
  note: string; // how the data was reduced, e.g. "max of 6×6 cells per pixel"
  reduced: boolean;
  stat: ReduceStat;
  draft?: boolean; // the data was drawn at half resolution (while moving)
  ms: { wait: number; reduce: number; draw: number; encode: number; total?: number }; // server time; total: the whole request
  notes?: string[]; // about the view settings, e.g. chosen positions that no longer exist
  ops?: OpsInfo | null; // the operations' state (operations.py), when there are any
  hidden?: string[]; // what the scales hide (points ≤ 0 on a log scale, …): kept on screen
  empty?: string | null; // nothing can be shown, and why
  sync?: SyncKeys; // what panels must share to follow each other's zoom
}

/** A panel follows another's zoom along x (y) when these are the same (explore.py `sync_keys`). */
export interface SyncKeys {
  x: string; // the horizontal axis as drawn (label with unit)
  y: string; // maps: the vertical axis' label; curves: the vertical unit
}

/** One operation of the Explore view (operations.py); the list is a view setting. */
export type OpName =
  | "subtract_mean"
  | "normalize"
  | "derivative"
  | "smooth"
  | "subtract_first"
  | "subtract_previous"
  | "average"
  | "std"
  | "fft"
  | "histogram"
  | "delay"
  | "rotation"
  | "auto_rotate"
  | "iq_histogram";
export interface Op {
  op: OpName;
  along?: "x" | "traces";
  on?: boolean;
  n?: number; // smooth (mean, median): points
  method?: "mean" | "gaussian" | "median"; // smooth
  sigma?: number; // smooth, Gaussian: width in points
  bins?: number; // histogram, I/Q histogram
  tau?: number; // electrical delay, s
  phi?: number; // rotation, degrees
}
export interface OpsInfo {
  notes: (string | null)[]; // per operation: null (applied), "off", or why not
  applied: number;
  shows?: string; // what the plot shows now, e.g. "dS21/dFrequency"
  unit?: string; // in which unit, e.g. "dB/GHz"
  one_to_one?: boolean; // each shown point is still a stored point
  equations?: Record<string, { error?: string; note?: string }>; // per field (x, y, z)
  names?: { name: string; means: string }[]; // what each name in an equation stands for
}

export interface ExploreFrame {
  meta: ExploreFrameMeta;
  image: ImageData | ImageBitmap;
  /** Milliseconds from asking to having the picture, measured in the page. */
  roundTripMs: number;
}

// ---- reading values (server: reading.py) ----

export type CursorType = "cross" | "vertical" | "horizontal";

/** A cursor's position (plot units) as the page asks for it; the server snaps it to the data. */
export interface CursorAsk {
  x: number;
  y: number;
  trace?: number; // curves: stay on this trace
  free?: boolean; // keep this position (not on the data)
  step?: [number, number]; // move by stored points: along x, along y (maps) or traces (curves)
}

/** One number of a read-out, as stored (curves: as plotted, e.g. |S21| in dB). */
export interface ReadItem {
  role: "x" | "y" | "z" | "series";
  name: string;
  label: string;
  unit: string;
  value: number | null; // null: empty (missing data)
  index?: number;
  /** the position's text, for an axis with elements (format 1.2) */
  text?: string | null;
}

export interface CursorRead {
  x: number; // snapped position, plot units
  y: number;
  free: boolean;
  trace?: number;
  label?: string; // the trace's name
  index: Record<string, number>; // stored indices
  items: ReadItem[];
  table?: { rows: { trace: number; label: string; value: number | null; unit?: string; x: number | null }[]; more: number; label: string; unit: string };
  line?: ([number, number] | null)[]; // the trace as drawn (plot units), to highlight it
  stored?: { label: string; unit: string; value: number | null }; // with operations on: the stored value behind it
  cell?: [number, number, number, number]; // maps: the cell, x0 y0 x1 y1 (plot units)
  at?: [number, number]; // maps: the cell's column and row in the map as shown
}

/** A cut through a map: positions (plot units) and values (plot units) along one axis. */
export interface Cut {
  pos: number[];
  z: (number | null)[];
  range: [number | null, number | null];
  fixed: string; // the axis held fixed
  index: number;
}

export interface CursorsAnswer {
  type: CursorType;
  factors: { x: number; y: number; z: number }; // plot units per stored unit
  cursors: (CursorRead | null)[];
  cuts?: { row?: Cut; column?: Cut; zf: number };
}

export interface Histogram {
  edges: number[]; // plot units (log-spaced on a log colour scale)
  counts: number[];
  lowest: number;
  highest: number;
  auto: [number, number];
  log: boolean;
  cells: number;
  /** a map too big for memory: counted from its summary's blocks, so the shape is approximate */
  approximate?: boolean;
}

async function exploreRender(
  session: string,
  view: {
    xlim?: [number, number] | null;
    ylim?: [number, number] | null;
    stat: ReduceStat;
    format?: "raw" | "png";
    draft?: boolean; // while zooming or panning: the data at half resolution (faster)
    settings?: object; // how the data is shown: ViewSettings in ExploreView.tsx
    width?: number; // the panel's size now (CSS pixels), when it changed since opening
    height?: number;
    dpr?: number;
  },
  signal?: AbortSignal,
): Promise<ExploreFrame> {
  const t0 = performance.now();
  const r = await send("POST", `/api/explore/${encodeURIComponent(session)}/render`, { format: "raw", ...view }, undefined, signal);
  const meta = JSON.parse(r.headers.get("X-LBD-Frame") ?? "{}") as ExploreFrameMeta;
  const blob = await r.blob();
  let image: ImageData | ImageBitmap;
  if (meta.format === "png") {
    image = await createImageBitmap(blob);
  } else {
    image = new ImageData(new Uint8ClampedArray(await blob.arrayBuffer()), meta.width, meta.height);
  }
  return { meta, image, roundTripMs: performance.now() - t0 };
}

export const api = {
  /** Open an Explore session for a file, drawn for a panel of width × height CSS pixels. */
  exploreOpen: (path: string, spec: PlotSpec | null, width: number, height: number, dpr: number) =>
    call<ExploreOpen>("POST", "/api/explore", { path, spec, width: Math.round(width), height: Math.round(height), dpr }),
  exploreRender,
  exploreClose: (session: string) => call<{ ok: boolean }>("DELETE", `/api/explore/${encodeURIComponent(session)}`),
  /** Cursors snapped to the stored data, their read-outs and (maps) the cuts through cursor 1. */
  exploreCursors: (
    session: string,
    body: { cursors: CursorAsk[]; type: CursorType; xlim: number[]; ylim: number[]; width: number; height: number; cuts: boolean },
  ) => call<CursorsAnswer>("POST", `/api/explore/${encodeURIComponent(session)}/cursors`, body),
  /** Where the max, min or peak (farthest from the median) is, in a range of the stored data. */
  exploreFind: (session: string, what: "max" | "min" | "peak", xlim: number[], ylim: number[], trace?: number) =>
    call<{ x: number; y: number; trace?: number }>("POST", `/api/explore/${encodeURIComponent(session)}/find`, { what, xlim, ylim, trace }),
  /** The map's values counted, with these view settings (chosen rows, colour scale). */
  exploreHistogram: (session: string, settings: object) =>
    call<Histogram>("POST", `/api/explore/${encodeURIComponent(session)}/histogram`, { settings }),
  /** The delay (s) or rotation (degrees) that straightens the data in an x range (plot units). */
  exploreCalculate: (session: string, what: "delay" | "rotation", index: number, xlim: number[], trace?: number) =>
    call<{ value: number; unit: string }>("POST", `/api/explore/${encodeURIComponent(session)}/calculate`, { what, index, xlim, trace }),
  /** Save a cut as a new .lbd file; without a path, only suggest one. */
  exploreSaveCut: (session: string, which: "row" | "column" | "trace", index: Record<string, number>, trace?: number, path?: string) =>
    call<{ path: string }>("POST", `/api/explore/${encodeURIComponent(session)}/save-cut`, { which, index, trace, path: path ?? null }),
  /** Save what panels show as CSV: without `path` the plan (name, size, options); with it, a job. */
  exportCsv: (sessions: string[], choice: ExportChoice, views: { xlim: number[]; ylim: number[] }[] | null, path?: string) =>
    call<ExportPlan & { job: string; paths: string[] }>("POST", "/api/explore/export-csv", {
      sessions,
      ...choice,
      views,
      path: path ?? null,
    }),
  exports: () => call<{ jobs: ExportJob[] }>("GET", "/api/exports"),
  cancelExport: (job: string) => call<{ ok: boolean }>("POST", "/api/exports/cancel", { job }),
  /** The Explore view LBD remembers for a file (its database, never the file); `note` says why
   *  a remembered view no longer fits. */
  remembered: (path: string) => call<{ state: JsonObject | null; note: string | null }>("GET", "/api/explore/remembered", undefined, { path }),
  remember: (path: string, state: object) => call<{ ok: boolean }>("PUT", "/api/explore/remembered", { path, state }),
  forget: (path: string) => call<{ ok: boolean }>("DELETE", "/api/explore/remembered", undefined, { path }),
  /** Other plot settings for an open session; answers like exploreOpen. */
  exploreSpec: (session: string, spec: PlotSpec) => call<ExploreOpen>("POST", `/api/explore/${encodeURIComponent(session)}/spec`, { spec }),

  state: () => call<AppState>("GET", "/api/state"),
  heartbeat: () => call<{ ok: boolean }>("POST", "/api/heartbeat"),
  open: (path: string) => call<{ path: string }>("POST", "/api/open", { path }),
  addRoot: (path: string) => call<{ roots: string[] }>("POST", "/api/roots", { path }),
  removeRoot: (path: string) => call<{ roots: string[] }>("DELETE", "/api/roots", undefined, { path }),
  pickFolder: () => call<{ path: string | null }>("POST", "/api/pick-folder"),
  list: (path: string) => call<DirListing>("GET", "/api/list", undefined, { path }),
  /** What changed on disk: see watch.ts. Reads only sizes and times; never opens a file. */
  changes: (files: string[], dirs: string[]) => call<Changes>("POST", "/api/changes", { files, dirs }),
  search: (root: string, q: string) => call<SearchResult>("GET", "/api/search", undefined, { root, q }),
  file: (path: string) => call<FileInfo>("GET", "/api/file", undefined, { path }),
  render: (path: string, spec: PlotSpec | null, preset: string | null, style: JsonObject | null, styleFile?: string | null) =>
    call<RenderResult>("POST", "/api/render", { path, spec, preset, style, style_file: styleFile ?? null }),
  /** An axis' values in full, e.g. to jump to the point nearest a typed value. */
  axis: (path: string, name: string) => call<AxisValues>("GET", "/api/axis", undefined, { path, name }),
  imageInfo: (path: string) => call<ImageInfo>("GET", "/api/image/info", undefined, { path }),
  styleFile: (path: string) => call<StyleFileInfo>("GET", "/api/stylefile", undefined, { path }),
  importStyle: (name: string, content: unknown, overwrite = false) =>
    call<StyleDetail>("POST", "/api/styles/import", { name, content, overwrite }),
  /** Save the view into the file. With `if_version`, a file changed since then gives 409. */
  saveFilePlot: (path: string, changes: { spec?: PlotSpec | null; style?: JsonObject | null; style_name?: string | null; if_version?: string | null }) =>
    call<FileInfo>("PUT", "/api/file/plot", { path, ...changes }),
  styles: () => call<StyleEntry[]>("GET", "/api/styles"),
  style: (name: string) => call<StyleDetail>("GET", `/api/styles/${encodeURIComponent(name)}`),
  saveStyle: (name: string, preset: JsonObject) =>
    call<StyleDetail>("PUT", `/api/styles/${encodeURIComponent(name)}`, { preset }),
  deleteStyle: (name: string) => call<StyleEntry[]>("DELETE", `/api/styles/${encodeURIComponent(name)}`),
  /** Download a preset as a .lbd.json style file ("lbd") or a matplotlib .mplstyle ("mpl"). */
  async exportStyle(name: string, format: "lbd" | "mpl") {
    return download(`/api/styles/${encodeURIComponent(name)}/export?format=${format}`, "GET", undefined, `${name}.${format === "lbd" ? "lbd.json" : "mplstyle"}`);
  },
  /** An image as a blob: URL (the session token can't be sent from an <img> tag). */
  async imageUrl(path: string): Promise<string> {
    const r = await fetch(`/api/image?${new URLSearchParams({ path })}`, { headers: { "X-LBD-Token": token } });
    if (!r.ok) throw new ApiError(r.status, await errorText(r));
    return URL.createObjectURL(await r.blob());
  },
  fonts: () => call<{ installed: string[]; generic: string[] }>("GET", "/api/fonts"),
  styleDefaults: () => call<{ defaults: JsonObject; schema: JsonObject }>("GET", "/api/style-defaults"),
  setDefaultStyle: (name: string) => call<AppState>("PUT", "/api/settings", { default_style: name }),
  setOpenFilesIn: (where: OpenFilesIn) => call<AppState>("PUT", "/api/settings", { open_files_in: where }),
  setOpenDataIn: (where: OpenDataIn) => call<AppState>("PUT", "/api/settings", { open_data_in: where }),
  setTheme: (theme: Theme) => call<AppState>("PUT", "/api/settings", { theme }),
  setLibrary: (changes: Partial<LibrarySettings>) => call<AppState>("PUT", "/api/settings", { library: changes }),
  setMemory: (changes: Partial<Pick<MemorySettings, "reserve_gb" | "maximum_gb" | "summary_cache_gb">>) =>
    call<AppState>("PUT", "/api/settings", { memory: changes }),
  // summaries of maps bigger than memory (summaries.py)
  summaries: () => call<{ making: SummaryJob[]; count: number; bytes: number }>("GET", "/api/summaries"),
  cancelSummary: (path: string) => call<{ ok: boolean }>("POST", "/api/summaries/cancel", { path }),
  emptySummaries: () => call<{ removed: number; kept: number; count: number; bytes: number }>("POST", "/api/summaries/empty"),

  // ---- Library: the index of the data files under the open folders (library.py)
  libraryList: (query: LibraryQuery, offset: number, limit: number) => {
    const qs = new URLSearchParams({ q: query.q, date: query.date, sort: query.sort, order: query.order, offset: String(offset), limit: String(limit) });
    if (query.folder) qs.set("folder", query.folder);
    if (query.project) qs.set("project", query.project);
    for (const t of query.tags) qs.append("tags", t);
    for (const u of query.users) qs.append("users", u);
    if (query.starred) qs.set("starred", "true");
    if (query.conflicts) qs.set("conflicts", "true");
    return call<LibraryPage>("GET", `/api/library/list?${qs.toString()}`);
  },
  libraryFacets: (folder: string | null, q: string, date = "") =>
    call<LibraryFacets>("GET", "/api/library/facets", undefined, { ...(folder ? { folder } : {}), q, date }),
  librarySetLabels: (paths: string[], changes: LabelChanges) =>
    call<{ notes: string[] }>("POST", "/api/library/labels", { paths, ...changes }),
  librarySame: (path: string) => call<SameId>("GET", "/api/library/same", undefined, { path }),
  libraryResolve: (path: string, action: "new_id" | "same" | "trash") =>
    call<{ notes: string[] }>("POST", "/api/library/resolve", { path, action }),
  libraryDuplicate: (path: string, labels = true) => call<{ path: string; notes: string[] }>("POST", "/api/library/duplicate", { path, labels }),
  libraryGiveIds: (paths: string[]) => call<{ notes: string[] }>("POST", "/api/library/give-ids", { paths }),
  libraryMissing: () => call<{ missing: MissingLabels[] }>("GET", "/api/library/missing"),
  libraryMissingResolve: (entry: MissingLabels, path: string | null) =>
    call<{ notes: string[] }>("POST", "/api/library/missing", { entry, path }),
  libraryFile: (path: string) => call<FileInfo>("GET", "/api/library/file", undefined, { path }),
  libraryStatus: () => call<LibraryStatus>("GET", "/api/library/status"),
  // ---- Library previews (previews.py)
  /** `now`: the selected file (drawn first); else a picture in view (drawn after it). */
  libraryPreview: async (path: string, now = true, signal?: AbortSignal): Promise<Preview> => {
    const r = await send("GET", "/api/library/preview", undefined, { path, now: String(now) }, signal);
    if (r.headers.get("content-type") === "image/webp") {
      const about = JSON.parse(r.headers.get("X-LBD-Preview") ?? "{}");
      return { picture: await r.blob(), ...about } as Preview;
    }
    return { picture: null, ...(await r.json()) } as Preview;
  },
  libraryPreviewWant: (paths: string[], now: boolean) => call<{ ok: boolean }>("POST", "/api/library/preview/want", { paths, now }),
  libraryPreviewChoose: (path: string, panels: PreviewPanel[], grid: [number, number], preset: string | null) =>
    call<{ chosen_at: number; warnings: string[] }>("POST", "/api/library/preview/choose", { path, panels, grid, preset }),
  libraryPreviewReset: (path: string) => call<{ forgotten: number }>("DELETE", "/api/library/preview/choose", undefined, { path }),
  libraryPreviewCache: () => call<{ count: number; bytes: number }>("GET", "/api/library/preview/cache"),
  libraryPreviewClear: () => call<{ freed: number }>("POST", "/api/library/preview/clear"),

  // ---- pages: this browser tab among the viewer's open pages (lbd_viewer/pages.py)
  registerPage: () => call<{ page: string; number: number }>("POST", "/api/pages"),
  pages: () => call<{ pages: PageEntry[] }>("GET", "/api/pages"),
  pageFocus: (page: string) => call<{ ok: boolean }>("POST", `/api/pages/${page}/focus`),
  /** The long poll: the first command not handled yet, or null after `wait` seconds. `after`: the
   *  id of the last command handled (confirms it; a command whose answer got lost comes again). */
  pageNext: async (page: string, after: number, wait = 25) => {
    const r = await call<PageCommand | Record<string, never>>("GET", `/api/pages/${page}/next`, undefined, {
      wait: String(wait),
      after: String(after),
    });
    return "kind" in r ? (r as PageCommand) : null;
  },
  pageAck: (page: string, command: number) => call<AckResult>("POST", `/api/pages/${page}/ack/${command}`),
  /** Open a file in this page: `owner` is set if another page has it open (then don't open it). */
  acquire: (page: string, path: string) => call<{ path: string; owner?: number }>("POST", `/api/pages/${page}/acquire`, { path }),
  release: (page: string, path: string) => call<{ ok: boolean }>("POST", `/api/pages/${page}/release`, { path }),
  showElsewhere: (path: string) => call<{ page: number }>("POST", "/api/pages/show", { path }),
  startTransfer: (page: string, paths: string[], states: { [path: string]: TabState }, to: string | null) =>
    call<{ id: string; timeout: number }>("POST", "/api/transfers", { page, paths, states, to }),
  claimTransfer: (id: string, page: string) =>
    call<{ paths: string[]; states: { [path: string]: TabState }; from: number | null }>("POST", `/api/transfers/${id}/claim`, { page }),
  completeTransfer: (id: string, page: string) => call<{ paths: string[] }>("POST", `/api/transfers/${id}/complete`, { page }),
  cancelTransfer: (id: string, reason: string) => call<{ ok: boolean }>("POST", `/api/transfers/${id}/cancel`, { reason }),
  /** The page is closing: tell the viewer, even while the page unloads (keepalive). */
  pageBye: (page: string) => {
    fetch(`/api/pages/${page}/bye`, { method: "POST", keepalive: true, headers: { "X-LBD-Token": token } }).catch(() => undefined);
  },
  sdk: () => call<SdkInfo>("GET", "/api/sdk"),
  revealSdk: (lang: string) => call<{ folder: string }>("POST", "/api/sdk/reveal", undefined, { lang }),
  reveal: (path: string) => call<{ ok: boolean }>("POST", "/api/reveal", { path }),
  /** Rename a data, style or image file in its folder; the extension must stay. Returns the new path. */
  renameFile: (path: string, name: string) => call<{ path: string }>("POST", "/api/file/rename", { path, name }),
  /** Move a data, style or image file to the Recycle Bin / Trash (never deleted permanently). */
  trashFile: (path: string) => call<{ ok: boolean }>("POST", "/api/file/trash", { path }),
  /** a file whose measurement stopped before finishing (name.lbd.writing) becomes an .lbd file */
  recoverFile: (path: string) => call<{ path: string }>("POST", "/api/file/recover", { path }),

  /** Export a figure with the system's "Save as" dialog (data file's folder, name filled in).
   *  `path` is null if the user cancelled. 501: no dialog on this system, use exportFigure. */
  saveFigure: (path: string, spec: PlotSpec | null, preset: string | null, style: JsonObject | null, format: string) =>
    call<{ path: string | null; warnings: string[] }>("POST", "/api/export/save", { path, spec, preset, style, format }),

  /** Export a figure and hand it to the browser as a download. */
  async exportFigure(path: string, spec: PlotSpec | null, preset: string | null, style: JsonObject | null, format: string) {
    return download("/api/export", "POST", { path, spec, preset, style, format }, `figure.${format}`);
  },
};

async function errorText(r: Response): Promise<string> {
  try {
    const j = await r.json();
    return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    return `${r.status} ${r.statusText}`;
  }
}

/** Warnings the server sent with the last download (e.g. an export), shown by the caller. */
export let lastDownloadWarnings: string[] = [];

function parseWarnings(header: string | null): string[] {
  if (!header) return [];
  try {
    const v = JSON.parse(header);
    return Array.isArray(v) ? v.map(String) : [String(v)];
  } catch {
    return [header];
  }
}

/** Fetch a file from the API and hand it to the browser as a download. Returns the file name. */
async function download(url: string, method: string, body: unknown, fallbackName: string): Promise<string> {
  const r = await fetch(url, {
    method,
    headers: { "X-LBD-Token": token, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new ApiError(r.status, await errorText(r));
  lastDownloadWarnings = parseWarnings(r.headers.get("X-LBD-Warnings"));
  const blob = await r.blob();
  const cd = r.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? fallbackName;
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 10_000);
  return name;
}

/** The address of a new viewer browser tab: with a file to open, or a move to claim. */
/** The viewer's address in a new browser tab: opening a file (in Explore or Figure), or taking
 *  tabs moved from another page. */
export function viewerUrl(params: { open?: string; claim?: string; in?: Workspace } = {}): string {
  const q = new URLSearchParams({ token });
  if (params.open) q.set("open", params.open);
  if (params.in) q.set("in", params.in);
  if (params.claim) q.set("claim", params.claim);
  return `${window.location.origin}/?${q}`;
}

export function baseName(p: string): string {
  const parts = p.split(/[\\/]/);
  return parts[parts.length - 1] || p;
}

export function joinPath(dir: string, name: string): string {
  const sep = dir.includes("\\") && !dir.includes("/") ? "\\" : "/";
  return dir.endsWith("\\") || dir.endsWith("/") ? dir + name : dir + sep + name;
}

export function formatBytes(n: number | null | undefined): string {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`;
}

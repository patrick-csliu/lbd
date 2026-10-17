// Typed client for the viewer's HTTP API (python/src/lbd/viewer/server.py).

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
  /** the viewer's colours: "system" follows the operating system */
  theme: Theme;
}

export type OpenFilesIn = "viewer" | "browser-tab";
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
}

export interface DirListing {
  path: string;
  dirs: string[];
  files: { name: string; type: FileKind; size: number; mtime: number }[];
  errors: { name: string; error: string }[];
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
}

export interface ValueInfo {
  name: string;
  unit: string;
  label: string;
  axes: string[];
  shape: number[];
  dtype: string;
  complex: boolean;
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
  meta: JsonObject;
  plot: PlotSpec | null;
  style: JsonObject | null;
  style_name: string | null;
  /** matplotlib version that last wrote the saved view, if any */
  matplotlib: string | null;
  /** changes when the file is written; sent back when saving, so a changed file isn't overwritten */
  version: string | null;
  warnings: string[];
}

export interface Slice {
  axis: string;
  index: number;
  length: number;
  label: string;
  unit: string;
  value: number | null;
}

export type FileKind = "lbd" | "style" | "image";

/** What kind of file a path is, from its name (same rules as the server's scan.py). */
export function fileKind(path: string): FileKind {
  const p = path.toLowerCase();
  if (p.endsWith(".lbd")) return "lbd";
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
  kind?: "auto" | "curve" | "heatmap" | "scatter" | "scalar";
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
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  const r = await fetch(path + qs, {
    method,
    headers: { "X-LBD-Token": token, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
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
  return (await r.json()) as T;
}

export const api = {
  state: () => call<AppState>("GET", "/api/state"),
  heartbeat: () => call<{ ok: boolean }>("POST", "/api/heartbeat"),
  open: (path: string) => call<{ path: string }>("POST", "/api/open", { path }),
  addRoot: (path: string) => call<{ roots: string[] }>("POST", "/api/roots", { path }),
  removeRoot: (path: string) => call<{ roots: string[] }>("DELETE", "/api/roots", undefined, { path }),
  pickFolder: () => call<{ path: string | null }>("POST", "/api/pick-folder"),
  list: (path: string) => call<DirListing>("GET", "/api/list", undefined, { path }),
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
  setTheme: (theme: Theme) => call<AppState>("PUT", "/api/settings", { theme }),

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
export function viewerUrl(params: { open?: string; claim?: string } = {}): string {
  const q = new URLSearchParams({ token });
  if (params.open) q.set("open", params.open);
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

import { KeyboardEvent, MouseEvent, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { api, AppState, baseName, LibraryQuery, LibraryRow, SidebarScope } from "./api";
import { ConfirmDialog, ConfirmRequest, ContextMenu, isMenuKey, MenuAt, menuAt, MenuEntry } from "./menu";
import { fileEntries } from "./fileActions";
import { useToast } from "./toast";
import { useFileActions } from "./libraryActions";
import { PAGE, useLibraryRows, useLibraryStatus } from "./libraryRows";
import { NO_FILTERS } from "./libraryQuery";
import FolderPanel from "./FolderPanel";

/**
 * The Files sidebar of Explore and Figure (it replaced the Folders panel): a quick way to the
 * next file without going back to the Library.
 *
 * Its lists ("scopes", chosen in ⚙ Settings → Files sidebar):
 * - Library selection: the Library's list with this browser tab's filters (always offered);
 * - Folders: the folder tree, a separate way in (in Figure with images and style files);
 * - Starred: the starred data files;
 * - Recent: the data files opened lately in this browser tab.
 * Its search box narrows the list shown; it never changes the Library's filters.
 */

const ROW_H = 26; // px: a row of the compact list
export const SCOPE_TITLES: Record<SidebarScope, string> = {
  library: "Library selection",
  folders: "Folders",
  starred: "Starred",
  recent: "Recent",
};

interface Props {
  /** the button that hides the sidebar (in its heading) */
  hideButton?: ReactNode;
  workspace: "explore" | "figure";
  state: AppState;
  /** this browser tab's Library filters */
  query: LibraryQuery;
  scope: SidebarScope;
  onScope: (s: SidebarScope) => void;
  /** data files opened lately in this browser tab, newest first */
  recent: string[];
  activePath: string | null;
  /** click: show the file (the preview tab); double-click / Enter: keep it open */
  onSelect: (path: string) => void;
  onOpen: (path: string) => void;
  /** go to the Library, to change its filters (or its folders) */
  onEditInLibrary: () => void;
  onOpenIn: (path: string, where: "explore" | "figure") => void;
  onOpenInNewBrowserTab: (path: string) => void;
  onRenamed: (oldPath: string, newPath: string) => void;
  onDeleted: (path: string) => void;
}

export default function FilesSidebar(props: Props) {
  const { workspace, state, query, recent } = props;
  const offered = state.library.sidebar_scopes;
  const scope = offered.includes(props.scope) ? props.scope : "library";
  return (
    <div className="files-sidebar">
      <div className="panel-head">
        <h2>Files</h2>
        <span className="files-head-end">
        {offered.length > 1 && (
          <select className="files-scope" value={scope} onChange={(e) => props.onScope(e.target.value as SidebarScope)} aria-label="Files listed">
            {offered.map((s) => (
              <option key={s} value={s}>
                {SCOPE_TITLES[s]}
              </option>
            ))}
          </select>
        )}
        {props.hideButton}
        </span>
      </div>
      {scope === "folders" ? (
        <FolderPanel
          roots={state.roots}
          activePath={props.activePath}
          platform={state.platform}
          onManageFolders={props.onEditInLibrary}
          onSelect={props.onSelect}
          onOpen={props.onOpen}
          onOpenInNewBrowserTab={props.onOpenInNewBrowserTab}
          onRenamed={props.onRenamed}
          onDeleted={props.onDeleted}
          onOpenIn={props.onOpenIn}
          kinds={workspace === "explore" ? ["lbd"] : undefined}
        />
      ) : scope === "recent" ? (
        <RecentList {...props} paths={recent} />
      ) : (
        <LibraryList {...props} query={scope === "starred" ? { ...NO_FILTERS, starred: true } : query} showFilters={scope === "library"} />
      )}
    </div>
  );
}

/** The filters of the Library selection, read-only, with Edit ↗ to change them in the Library. */
function FilterChips({ query, onEdit }: { query: LibraryQuery; onEdit: () => void }) {
  const chips: string[] = [];
  if (query.folder) chips.push(baseName(query.folder));
  if (query.date) chips.push(query.date);
  if (query.q) chips.push(`"${query.q}"`);
  if (query.project) chips.push(`project ${query.project}`);
  for (const u of query.users) chips.push(`user ${u}`);
  for (const t of query.tags) chips.push(`tag ${t}`);
  if (query.starred) chips.push("★ starred");
  if (query.conflicts) chips.push("⚠ copies that differ");
  return (
    <div className="files-filters small">
      {chips.length ? chips.map((c) => <span key={c} className="chip">{c}</span>) : <span className="muted">All files in the Library</span>}
      <button className="link" onClick={onEdit} title="Change the filters in the Library">
        Edit ↗
      </button>
    </div>
  );
}

/** The search box of a list: narrows it only (it doesn't change the Library's filters). */
function useNarrowing(): [string, string, (v: string) => void] {
  const [typed, setTyped] = useState("");
  const [words, setWords] = useState("");
  useEffect(() => {
    const id = window.setTimeout(() => setWords(typed.trim()), 200);
    return () => window.clearTimeout(id);
  }, [typed]);
  return [typed, words, setTyped];
}

/** A list of Library rows (the Library selection, or the starred files), windowed like the Library's. */
function LibraryList(props: Props & { showFilters: boolean }) {
  const { query, state, activePath, onSelect, onOpen } = props;
  const [typed, words, setTyped] = useNarrowing();
  // the sidebar's words narrow the Library's search (all words must match)
  const shownQuery: LibraryQuery = words ? { ...query, q: [query.q, words].filter(Boolean).join(" ") } : query;
  const { generation, refresh } = useLibraryStatus(false);

  const scroller = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ top: 0, height: 400 });
  const measure = (el: HTMLElement) => setView({ top: el.scrollTop, height: el.clientHeight });
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const ro = new ResizeObserver(() => measure(el));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const queryKey = JSON.stringify(shownQuery);
  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = 0;
    setView((v) => ({ ...v, top: 0 }));
  }, [queryKey]);
  const firstPage = Math.max(0, Math.floor(Math.floor(view.top / ROW_H) / PAGE));
  const lastPage = Math.floor((Math.floor((view.top + view.height) / ROW_H) + 1) / PAGE) + 1;
  const { total, rowAt, indexOf, listError } = useLibraryRows(shownQuery, generation, firstPage, lastPage);

  const [menu, setMenu] = useState<MenuAt | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const closeMenu = useCallback(() => setMenu(null), []);
  const { toggleStar, menuEntries } = useFileActions({
    platform: state.platform,
    login: state.login,
    refresh,
    setConfirm,
    onOpenIn: props.onOpenIn,
    onOpenInNewBrowserTab: props.onOpenInNewBrowserTab,
    onRenamed: props.onRenamed,
    onDeleted: props.onDeleted,
  });
  const rowMenu = (e: MouseEvent | KeyboardEvent, r: LibraryRow) => {
    e.preventDefault();
    setMenu(menuAt(e, menuEntries([r], r)));
  };

  /** Show row i (the keys): scrolled into view. */
  const step = (i: number) => {
    if (total === null || i < 0 || i >= total) return;
    const r = rowAt(i);
    if (r) onSelect(r.path);
    const el = scroller.current;
    if (el) {
      const top = i * ROW_H;
      if (top < el.scrollTop) el.scrollTop = top;
      else if (top + ROW_H > el.scrollTop + el.clientHeight) el.scrollTop = top + ROW_H - el.clientHeight;
      measure(el);
    }
  };
  const onKey = (e: KeyboardEvent) => {
    const i = indexOf(activePath);
    const page = scroller.current ? Math.max(1, Math.floor(scroller.current.clientHeight / ROW_H) - 1) : 1;
    const current = activePath ? rowAt(i) : undefined;
    if (e.key === "ArrowDown") step(i < 0 ? 0 : i + 1);
    else if (e.key === "ArrowUp") step(Math.max(0, i - 1));
    else if (e.key === "Home") step(0);
    else if (e.key === "End" && total) step(total - 1);
    else if (e.key === "PageDown") step(Math.min((total ?? 1) - 1, Math.max(0, i) + page));
    else if (e.key === "PageUp") step(Math.max(0, i - page));
    else if (e.key === "Enter" && activePath) onOpen(activePath);
    else if (e.key === " " && current) toggleStar([current]);
    else if (isMenuKey(e) && current) rowMenu(e, current);
    else return;
    e.preventDefault();
  };

  let empty: ReactNode = null;
  if (total === 0)
    empty = words ? (
      <>No file here matches "{words}".</>
    ) : props.showFilters ? (
      <>
        No files match the Library's filters.{" "}
        <button className="link" onClick={props.onEditInLibrary}>
          Edit in Library
        </button>
      </>
    ) : (
      <>No starred files yet. Star a file with its right-click menu, or Space.</>
    );

  return (
    <>
      {props.showFilters && <FilterChips query={query} onEdit={props.onEditInLibrary} />}
      <input className="filter" type="search" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Search in these files…" aria-label="Search in these files" />
      {listError && <div className="error-box small">{listError}</div>}
      <div
        className="files-list"
        ref={scroller}
        onScroll={() => scroller.current && measure(scroller.current)}
        onKeyDown={onKey}
        tabIndex={0}
        role="listbox"
        aria-label={props.showFilters ? "Files of the Library selection" : "Starred files"}
      >
        <div className="files-rows" style={{ height: (total ?? 0) * ROW_H }}>
          {Array.from({ length: Math.max(0, Math.min(total ?? 0, (lastPage + 1) * PAGE) - firstPage * PAGE) }, (_, k) => {
            const i = firstPage * PAGE + k;
            const top = i * ROW_H;
            if (top + ROW_H < view.top - ROW_H * 5 || top > view.top + view.height + ROW_H * 5) return null;
            const r = rowAt(i);
            if (!r) return <div key={`empty-${i}`} className="files-row loading" style={{ top }} />;
            return (
              <div
                key={r.path}
                className={"files-row" + (r.path === activePath ? " active" : "") + (r.error ? " unreadable" : "")}
                style={{ top }}
                role="option"
                aria-selected={r.path === activePath}
                title={`${r.path}${r.sweep ? `\nSweep: ${r.sweep}` : ""}${r.error ? `\nCan't be read: ${r.error}` : ""}`}
                onClick={(e) => {
                  if (e.ctrlKey || e.metaKey) props.onOpenInNewBrowserTab(r.path);
                  else onSelect(r.path);
                  scroller.current?.focus({ preventScroll: true });
                }}
                onAuxClick={(e) => e.button === 1 && props.onOpenInNewBrowserTab(r.path)}
                onDoubleClick={() => onOpen(r.path)}
                onContextMenu={(e) => rowMenu(e, r)}
              >
                <span className="files-name">
                  {r.star ? <span className="mark-star">★ </span> : null}
                  {r.conflict ? <span className="mark-conflict">⚠ </span> : null}
                  {r.title || r.name}
                  {r.writing === "measuring" ? <span className="files-mark measuring"> measuring…</span> : null}
                  {r.writing === "stopped" ? <span className="files-mark stopped"> stopped</span> : null}
                </span>
                <span className="files-date muted">{shortDate(r)}</span>
              </div>
            );
          })}
        </div>
        {empty && <div className="files-empty muted small">{empty}</div>}
      </div>
      {menu && <ContextMenu menu={menu} onClose={closeMenu} />}
      {confirm && <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />}
    </>
  );
}

/** "03-14" this year, "2025-03-14" before: the file's own date, short. */
function shortDate(r: LibraryRow): string {
  const day = !r.date_from_file && r.created ? r.created.slice(0, 10) : new Date(r.mtime * 1000).toISOString().slice(0, 10);
  return day.startsWith(String(new Date().getFullYear())) ? day.slice(5) : day;
}

/** The data files opened lately in this browser tab. */
function RecentList(props: Props & { paths: string[] }) {
  const { paths, activePath, onSelect, onOpen, state } = props;
  const toast = useToast();
  const [typed, words, setTyped] = useNarrowing();
  const shown = words ? paths.filter((p) => words.toLowerCase().split(/\s+/).every((w) => p.toLowerCase().includes(w))) : paths;
  const [menu, setMenu] = useState<MenuAt | null>(null);
  const closeMenu = useCallback(() => setMenu(null), []);
  const rowMenu = (e: MouseEvent | KeyboardEvent, path: string) => {
    e.preventDefault();
    const items: MenuEntry[] = [
      { label: "Open in Explore", onClick: () => props.onOpenIn(path, "explore") },
      { label: "Open in Figure", onClick: () => props.onOpenIn(path, "figure") },
      "-",
      ...fileEntries(path, state.platform, toast),
      { label: "Open in new browser tab", onClick: () => props.onOpenInNewBrowserTab(path) },
    ];
    setMenu(menuAt(e, items));
  };
  const onKey = (e: KeyboardEvent) => {
    const i = activePath ? shown.indexOf(activePath) : -1;
    if (e.key === "ArrowDown" && shown.length) onSelect(shown[Math.min(shown.length - 1, i + 1)]);
    else if (e.key === "ArrowUp" && shown.length) onSelect(shown[Math.max(0, i - 1)]);
    else if (e.key === "Enter" && activePath) onOpen(activePath);
    else if (isMenuKey(e) && activePath) rowMenu(e, activePath);
    else return;
    e.preventDefault();
  };
  return (
    <>
      <input className="filter" type="search" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Search in these files…" aria-label="Search in these files" />
      <div className="files-list" tabIndex={0} role="listbox" aria-label="Files opened lately" onKeyDown={onKey}>
        {shown.map((p) => (
          <div
            key={p}
            className={"files-row static" + (p === activePath ? " active" : "")}
            role="option"
            aria-selected={p === activePath}
            title={p}
            onClick={(e) => (e.ctrlKey || e.metaKey ? props.onOpenInNewBrowserTab(p) : onSelect(p))}
            onDoubleClick={() => onOpen(p)}
            onContextMenu={(e) => rowMenu(e, p)}
          >
            <span className="files-name">{baseName(p).replace(/\.lbd$/i, "")}</span>
          </div>
        ))}
        {!shown.length && <div className="files-empty muted small">{words ? `No file here matches "${words}".` : "The data files you open in this browser tab are listed here."}</div>}
      </div>
      {menu && <ContextMenu menu={menu} onClose={closeMenu} />}
    </>
  );
}

/** ⚙ Settings → Files sidebar: which lists it offers (the Library selection always). */
export function SidebarScopeSettings({ state, onSettings }: { state: AppState; onSettings: (s: AppState) => void }) {
  const toast = useToast();
  // shown at once; the viewer's answer (or a refusal, with the old value) follows
  const [scopes, setScopes] = useState(state.library.sidebar_scopes);
  useEffect(() => setScopes(state.library.sidebar_scopes), [state.library.sidebar_scopes]);
  const set = (s: SidebarScope, on: boolean) => {
    const next = on ? [...scopes, s] : scopes.filter((x) => x !== s);
    setScopes(next);
    api
      .setLibrary({ sidebar_scopes: next })
      .then(onSettings)
      .catch((e) => {
        setScopes(state.library.sidebar_scopes);
        toast((e as Error).message, "error");
      });
  };
  return (
    <>
      <div className="settings-title">Files sidebar (Explore, Figure)</div>
      <label className="settings-choice">
        <input type="checkbox" checked disabled /> {SCOPE_TITLES.library} (the Library's filters)
      </label>
      {(["folders", "starred", "recent"] as SidebarScope[]).map((s) => (
        <label key={s} className="settings-choice">
          <input type="checkbox" checked={scopes.includes(s)} onChange={(e) => set(s, e.target.checked)} />
          {SCOPE_TITLES[s]}
          {s === "folders" ? " (in Figure also images and style files)" : ""}
        </label>
      ))}
    </>
  );
}

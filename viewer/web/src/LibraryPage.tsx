import { FormEvent, KeyboardEvent, MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  ApiError,
  AppState,
  baseName,
  FileInfo,
  formatBytes,
  LibraryColumn,
  LibraryFacets,
  LibraryFolder,
  LibraryQuery,
  LibraryRow,
  LibrarySettings,
  LibraryStatus,
} from "./api";
import { FileDetails } from "./FileView";
import { ConfirmDialog, ConfirmRequest, ContextMenu, isMenuKey, MenuAt, menuAt, MenuEntry, systemNames } from "./menu";
import { fileEntries, renameRequest } from "./fileActions";
import { useToast } from "./toast";

/**
 * The Library workspace: every data file under the open folders, as one list (Labber's Log
 * Browser). Left: the open folders (with counts, and All folders) and a date tree; middle: the
 * list, with search, sortable columns and the keyboard; right: the selected file.
 *
 * The list comes from LBD's index of the files (library.py), never from walking the disk: a page of
 * rows at a time (only what is on screen, plus a margin), so thousands of files scroll smoothly.
 * The index checks the folders by itself; the page asks every 2 s whether it changed
 * (`generation`) and then shows the new rows, keeping the selection and the scroll position.
 */

interface Props {
  state: AppState;
  selected: string | null;
  onSelect: (path: string | null) => void;
  onRootsChanged: (roots: string[]) => void;
  onLibrarySettings: (s: AppState) => void;
  onOpenIn: (path: string, where: "explore" | "figure") => void;
  onOpenInNewBrowserTab: (path: string) => void;
  onRenamed: (oldPath: string, newPath: string) => void;
  onDeleted: (path: string) => void;
  onOpenSettings: () => void;
}

const ROW_H = 28; // px: every row has this height (the list is windowed)
const PAGE = 100; // rows asked for at a time
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const NOTICE =
  "To list date, sweep size and values and to search inside files, LBD opens each data file and reads its header (not its data). " +
  "In a folder kept in cloud storage with files only in the cloud (Synology Drive on-demand sync, OneDrive Files On-Demand, " +
  "Dropbox online-only …), opening a file downloads all of it. Switch this off in ⚙ to list such folders by name only.";

const COLUMNS: { id: LibraryColumn; title: string; width: string }[] = [
  { id: "name", title: "Name", width: "minmax(180px, 3fr)" },
  { id: "date", title: "Date", width: "minmax(170px, 1.3fr)" },
  { id: "sweep", title: "Sweep size", width: "minmax(90px, 0.8fr)" },
  { id: "values", title: "Values", width: "minmax(120px, 1.5fr)" },
  { id: "folder", title: "Folder", width: "minmax(120px, 1.5fr)" },
  { id: "size", title: "File size", width: "minmax(80px, 0.6fr)" },
  { id: "file", title: "File name", width: "minmax(140px, 1.5fr)" },
  { id: "modified", title: "Modified", width: "minmax(140px, 1fr)" },
];

/** "2026-03-14 23:30 +08:00": the date as written in the file (its own time zone kept). */
function createdText(r: LibraryRow): string {
  if (r.date_from_file || !r.created) return localTime(r.mtime);
  const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$/i.exec(r.created);
  if (!m) return r.created;
  return `${m[1]} ${m[2]} ${m[3] === "Z" || m[3] === "z" ? "UTC" : m[3] ?? ""}`.trim();
}

function localTime(seconds: number): string {
  const d = new Date(seconds * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function cellText(r: LibraryRow, c: LibraryColumn): string {
  switch (c) {
    case "name":
      return r.title || r.name;
    case "date":
      return createdText(r);
    case "sweep":
      return r.sweep;
    case "values":
      return r.value_names;
    case "folder":
      return r.folder || "·";
    case "size":
      return formatBytes(r.size);
    case "file":
      return r.name;
    case "modified":
      return localTime(r.mtime);
  }
}

/** "2026 › Oct › 14" for a date filter "2026-10-14". */
function dateLabel(date: string): string {
  const [y, m, d] = date.split("-");
  return [y, m && MONTHS[Number(m) - 1], d && String(Number(d))].filter(Boolean).join(" › ");
}

function findFolder(trees: LibraryFolder[], path: string): LibraryFolder | null {
  for (const t of trees) {
    if (t.path === path) return t;
    const inner = findFolder(t.children, path);
    if (inner) return inner;
  }
  return null;
}

export default function LibraryPage(props: Props) {
  const { state, selected, onSelect, onRootsChanged, onLibrarySettings, onOpenIn, onOpenInNewBrowserTab, onRenamed, onDeleted, onOpenSettings } = props;
  const toast = useToast();
  const names = systemNames(state.platform);
  const settings: LibrarySettings = state.library;
  const columns = COLUMNS.filter((c) => settings.columns.includes(c.id));

  // ---- what is listed
  const [folder, setFolder] = useState<string | null>(null);
  const [typed, setTyped] = useState(""); // the search box
  const [q, setQ] = useState(""); // the search, a moment after typing stops
  const [date, setDate] = useState("");
  const [sort, setSort] = useState<LibraryColumn>("date");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  useEffect(() => {
    const id = window.setTimeout(() => setQ(typed.trim()), 200);
    return () => window.clearTimeout(id);
  }, [typed]);
  const query: LibraryQuery = useMemo(() => ({ folder, q, date, sort, order }), [folder, q, date, sort, order]);
  const queryKey = JSON.stringify(query);

  // ---- the index: changes (generation), progress
  const [status, setStatus] = useState<LibraryStatus | null>(null);
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    let live = true;
    const ask = () =>
      api
        .libraryStatus()
        .then((s) => {
          if (!live) return;
          setStatus(s);
          setGeneration(s.generation);
        })
        .catch(() => undefined); // the next try reports nothing new; the list keeps what it shows
    ask();
    const id = window.setInterval(ask, 2000);
    return () => {
      live = false;
      window.clearInterval(id);
    };
  }, []);

  // ---- facets: folders with counts, the date tree
  const [facets, setFacets] = useState<LibraryFacets | null>(null);
  useEffect(() => {
    let live = true;
    api
      .libraryFacets(folder, q)
      .then((f) => live && setFacets(f))
      .catch((e) => live && toast((e as Error).message, "error"));
    return () => {
      live = false;
    };
  }, [folder, q, generation, state.roots, toast]);

  // ---- the rows: pages of PAGE rows, asked for when they come into view
  const [total, setTotal] = useState<number | null>(null);
  const [pages, setPages] = useState<Map<number, LibraryRow[]>>(new Map());
  const asked = useRef<Map<number, string>>(new Map()); // page -> the query+generation it was asked for
  const [listError, setListError] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ top: 0, height: 600 });

  // a new query: everything afresh, from the top
  useEffect(() => {
    setPages(new Map());
    asked.current = new Map();
    setTotal(null);
    if (scroller.current) scroller.current.scrollTop = 0;
    setView((v) => ({ ...v, top: 0 }));
  }, [queryKey]);

  const firstPage = Math.max(0, Math.floor(view.top / ROW_H / PAGE) - 0);
  const lastPage = Math.floor((view.top + view.height) / ROW_H / PAGE) + 1;
  useEffect(() => {
    for (let p = firstPage; p <= lastPage; p++) {
      if (total !== null && p * PAGE >= total && p > 0) break;
      const key = `${queryKey}|${generation}`;
      if (asked.current.get(p) === key) continue;
      asked.current.set(p, key);
      api
        .libraryList(query, p * PAGE, PAGE)
        .then((r) => {
          if (asked.current.get(p) !== key) return; // a newer query or change was asked meanwhile
          setTotal(r.total);
          setListError(null);
          setPages((old) => new Map(old).set(p, r.rows));
        })
        .catch((e) => {
          asked.current.delete(p);
          setListError((e as Error).message);
        });
    }
  }, [firstPage, lastPage, queryKey, generation, query, total]);

  const rowAt = (i: number): LibraryRow | undefined => pages.get(Math.floor(i / PAGE))?.[i % PAGE];
  const indexOf = (path: string | null): number => {
    if (!path) return -1;
    for (const [p, rows] of pages) {
      const k = rows.findIndex((r) => r.path === path);
      if (k >= 0) return p * PAGE + k;
    }
    return -1;
  };
  const selectedRow = (() => {
    const i = indexOf(selected);
    return i >= 0 ? rowAt(i) ?? null : null;
  })();

  const onScroll = () => {
    const el = scroller.current;
    if (el) setView({ top: el.scrollTop, height: el.clientHeight });
  };
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setView({ top: el.scrollTop, height: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  /** Select row i (keys): asks for its page if needed, and scrolls it into view. */
  const selectIndex = (i: number) => {
    if (total === null || i < 0 || i >= total) return;
    const r = rowAt(i);
    if (r) onSelect(r.path);
    const el = scroller.current;
    if (el) {
      const top = i * ROW_H, bottom = top + ROW_H, head = ROW_H;
      if (top < el.scrollTop + head) el.scrollTop = Math.max(0, top - head);
      else if (bottom > el.scrollTop + el.clientHeight) el.scrollTop = bottom - el.clientHeight;
      setView({ top: el.scrollTop, height: el.clientHeight });
    }
  };

  // ---- menus and dialogs
  const [menu, setMenu] = useState<MenuAt | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const closeMenu = useCallback(() => setMenu(null), []);

  const askTrash = (path: string) => {
    const name = baseName(path);
    setConfirm({
      title: `Move to the ${names.trash}?`,
      text: `Move "${name}" to the ${names.trash}? You can restore it from there.`,
      action: `Move to ${names.trash}`,
      danger: true,
      onConfirm: async () => {
        await api.trashFile(path);
        onDeleted(path);
        toast(`Moved ${name} to the ${names.trash}`);
      },
    });
  };

  const rowMenu = (e: MouseEvent | KeyboardEvent, r: LibraryRow) => {
    e.preventDefault();
    onSelect(r.path);
    const items: MenuEntry[] = [
      { label: "Open in Explore", onClick: () => onOpenIn(r.path, "explore") },
      { label: "Open in Figure", onClick: () => onOpenIn(r.path, "figure") },
      "-",
      ...fileEntries(r.path, state.platform, toast),
      { label: "Open in new browser tab", onClick: () => onOpenInNewBrowserTab(r.path) },
      "-",
      { label: "Rename…", onClick: () => setConfirm(renameRequest(r.path, (newPath) => onRenamed(r.path, newPath), toast)) },
      { label: `Move to ${names.trash}…`, onClick: () => askTrash(r.path), danger: true },
    ];
    setMenu(menuAt(e, items));
  };

  const setColumns = async (cols: LibraryColumn[]) => {
    try {
      onLibrarySettings(await api.setLibrary({ columns: cols }));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const columnMenu = (e: MouseEvent) => {
    e.preventDefault();
    setMenu(
      menuAt(
        e,
        COLUMNS.map((c) => {
          const on = settings.columns.includes(c.id);
          return {
            label: `${on ? "✓" : "\u2003"} ${c.title}`,
            disabled: on && settings.columns.length === 1, // at least one column
            onClick: () => setColumns(on ? settings.columns.filter((x) => x !== c.id) : COLUMNS.map((x) => x.id).filter((x) => x === c.id || settings.columns.includes(x))),
          };
        }),
      ),
    );
  };

  const sortBy = (c: LibraryColumn) => {
    if (c === sort) setOrder((o) => (o === "asc" ? "desc" : "asc"));
    else {
      setSort(c);
      setOrder(c === "date" || c === "size" || c === "modified" || c === "sweep" ? "desc" : "asc");
    }
  };

  const onListKey = (e: KeyboardEvent) => {
    const i = indexOf(selected);
    if (e.key === "ArrowDown") selectIndex(i < 0 ? 0 : i + 1);
    else if (e.key === "ArrowUp") selectIndex(Math.max(0, i - 1));
    else if (e.key === "Home") selectIndex(0);
    else if (e.key === "End" && total) selectIndex(total - 1);
    else if (e.key === "PageDown" && scroller.current) selectIndex(Math.min((total ?? 1) - 1, Math.max(0, i) + Math.floor(scroller.current.clientHeight / ROW_H) - 1));
    else if (e.key === "PageUp" && scroller.current) selectIndex(Math.max(0, i - Math.floor(scroller.current.clientHeight / ROW_H) + 1));
    else if (e.key === "Enter" && selected) onOpenIn(selected, e.shiftKey ? "figure" : "explore");
    else if (isMenuKey(e) && selectedRow) rowMenu(e, selectedRow);
    else return;
    e.preventDefault();
  };

  // ---- the status line
  const shownFolder = folder && facets ? findFolder(facets.folders, folder) : null;
  const all = folder ? shownFolder?.count : facets?.folders.reduce((n, f) => n + f.count, 0);
  const filtered = !!(q || date);
  const gridColumns = columns.map((c) => c.width).join(" ");

  return (
    <div className="page library">
      <aside className="library-left" aria-label="Folders and dates">
        <LibraryFolders
          roots={state.roots}
          facets={facets}
          folder={folder}
          onFolder={(f) => {
            setFolder(f);
            setDate("");
          }}
          onRootsChanged={onRootsChanged}
        />
        <DateTree dates={facets?.dates ?? {}} date={date} onDate={setDate} />
      </aside>

      <section className="library-middle" aria-label="Files">
        {settings.read_headers && !settings.notice_seen && (
          <div className="library-notice" role="note">
            <p>{NOTICE}</p>
            <div className="row-controls">
              <button
                className="primary"
                onClick={() =>
                  api
                    .setLibrary({ notice_seen: true })
                    .then(onLibrarySettings)
                    .catch((e) => toast((e as Error).message, "error"))
                }
              >
                OK
              </button>
              <button onClick={onOpenSettings}>Settings</button>
            </div>
          </div>
        )}
        <input
          className="library-search"
          type="search"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder={settings.read_headers ? "Search names, descriptions, values, units, metadata…" : "Search file names…"}
          aria-label="Search the files"
        />
        <div className="library-status small" role="status">
          <span>
            {total === null ? "…" : filtered && all !== undefined ? `${total} of ${all} files` : `${total} file${total === 1 ? "" : "s"}`}
          </span>
          {folder && (
            <span className="chip">
              {shownFolder?.name ?? baseName(folder)}
              <button className="link" aria-label="Show all folders" onClick={() => setFolder(null)}>
                ×
              </button>
            </span>
          )}
          {date && (
            <span className="chip">
              {dateLabel(date)}
              <button className="link" aria-label="Any date" onClick={() => setDate("")}>
                ×
              </button>
            </span>
          )}
          {q && (
            <span className="chip">
              "{q}"
              <button
                className="link"
                aria-label="Clear the search"
                onClick={() => {
                  setTyped("");
                  setQ("");
                }}
              >
                ×
              </button>
            </span>
          )}
          {!settings.read_headers && <span className="muted">names only: reading files' details is off in ⚙</span>}
          {status?.indexing && (
            <span className="muted">
              Indexing {status.done.toLocaleString()} of {status.total.toLocaleString()}…
            </span>
          )}
          {status && status.errors.length > 0 && (
            <span className="warn" title={status.errors.map((e) => `${e.path}: ${e.error}`).join("\n")}>
              {status.errors.length} folder(s) or file(s) couldn't be read (point here for which)
            </span>
          )}
        </div>
        {listError && <div className="error-box">{listError}</div>}

        <div className="library-list" ref={scroller} onScroll={onScroll} onKeyDown={onListKey} tabIndex={0} role="grid" aria-label="Data files" aria-rowcount={total ?? undefined}>
          <div className="library-head" role="row" style={{ gridTemplateColumns: gridColumns }} onContextMenu={columnMenu} title="Click: sort; right-click: choose the columns">
            {columns.map((c) => (
              <div key={c.id} role="columnheader" aria-sort={sort === c.id ? (order === "asc" ? "ascending" : "descending") : "none"}>
                <button className="link" onClick={() => sortBy(c.id)}>
                  {c.title}
                  {sort === c.id ? (order === "asc" ? " ▴" : " ▾") : ""}
                </button>
              </div>
            ))}
          </div>
          <div className="library-rows" style={{ height: (total ?? 0) * ROW_H }}>
            {Array.from({ length: Math.max(0, Math.min(total ?? 0, (lastPage + 1) * PAGE) - firstPage * PAGE) }, (_, k) => {
              const i = firstPage * PAGE + k;
              const top = i * ROW_H;
              if (top + ROW_H < view.top - ROW_H * 5 || top > view.top + view.height + ROW_H * 5) return null;
              const r = rowAt(i);
              if (!r)
                return (
                  <div key={`empty-${i}`} className="library-row loading" style={{ top, gridTemplateColumns: gridColumns }} role="row" aria-rowindex={i + 1}>
                    <div className="muted">…</div>
                  </div>
                );
              return (
                <div
                  key={r.path}
                  className={"library-row" + (r.path === selected ? " selected" : "") + (r.error ? " unreadable" : "")}
                  style={{ top, gridTemplateColumns: gridColumns }}
                  role="row"
                  aria-rowindex={i + 1}
                  aria-selected={r.path === selected}
                  title={r.error ? `Can't be read: ${r.error}` : r.path}
                  onClick={() => {
                    onSelect(r.path);
                    scroller.current?.focus({ preventScroll: true });
                  }}
                  onDoubleClick={() => onOpenIn(r.path, "explore")}
                  onContextMenu={(e) => rowMenu(e, r)}
                >
                  {columns.map((c) => (
                    <div key={c.id} role="gridcell" className={`cell-${c.id}`}>
                      {cellText(r, c.id)}
                      {c.id === "date" && r.date_from_file ? <span className="muted small"> (file date)</span> : null}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
          {total === 0 && (
            <div className="library-empty muted">
              {state.roots.length === 0
                ? "No folders yet: add one on the left (+ Add folder)."
                : filtered
                  ? "No file matches. Remove a filter above to see more."
                  : status?.indexing || !status?.scans
                    ? "Looking for data files…"
                    : "No data files (.lbd) in this folder."}
            </div>
          )}
        </div>
      </section>

      <section className="library-detail" aria-label="The selected file">
        {selected ? (
          <SelectedFile path={selected} row={selectedRow} generation={generation} onOpenIn={onOpenIn} />
        ) : (
          <div className="empty">
            <h2>Library</h2>
            <p>Click a file to see what is inside it; double-click (or Enter) to explore it. ↑ ↓ step through the list.</p>
          </div>
        )}
      </section>
      {menu && <ContextMenu menu={menu} onClose={closeMenu} />}
      {confirm && <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />}
    </div>
  );
}

// ---- left: the open folders, with counts

function LibraryFolders({
  roots,
  facets,
  folder,
  onFolder,
  onRootsChanged,
}: {
  roots: string[];
  facets: LibraryFacets | null;
  folder: string | null;
  onFolder: (f: string | null) => void;
  onRootsChanged: (roots: string[]) => void;
}) {
  const toast = useToast();
  const [adding, setAdding] = useState(roots.length === 0);
  const [typedPath, setTypedPath] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const trees = facets?.folders ?? roots.map((r) => ({ path: r, name: baseName(r), count: 0, children: [] }));
  const total = facets?.total ?? 0;

  const addRoot = async (path: string) => {
    try {
      onRootsChanged((await api.addRoot(path)).roots);
      setTypedPath("");
      setAdding(false);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const browse = async () => {
    try {
      const r = await api.pickFolder();
      if (r.path) await addRoot(r.path);
    } catch (e) {
      // 501: no native dialog here (e.g. Linux without tkinter) — the path box still works.
      toast((e as Error).message, e instanceof ApiError && e.status === 501 ? "info" : "error");
    }
  };
  const removeRoot = async (path: string) => {
    try {
      onRootsChanged((await api.removeRoot(path)).roots);
      if (folder && (folder === path || folder.startsWith(path))) onFolder(null);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (typedPath.trim()) addRoot(typedPath.trim().replace(/^"(.*)"$/, "$1"));
  };
  const toggle = (path: string) =>
    setOpen((o) => {
      const n = new Set(o);
      if (n.has(path)) n.delete(path);
      else n.add(path);
      return n;
    });

  // open folders start unfolded (their key in `open` folds them); the folders inside start folded
  const unfolded = (f: LibraryFolder, isRoot: boolean) => (isRoot ? !open.has("-" + f.path) : open.has(f.path));
  const node = (f: LibraryFolder, depth: number, isRoot: boolean) => (
    <li key={f.path} role="treeitem" aria-expanded={f.children.length ? unfolded(f, isRoot) : undefined} aria-selected={folder === f.path}>
      <div className={"library-folder" + (folder === f.path ? " active" : "")} style={{ paddingLeft: 8 + depth * 14 }}>
        {f.children.length ? (
          <button className="link twisty" aria-label={(unfolded(f, isRoot) ? "Fold " : "Unfold ") + f.name} onClick={() => toggle(isRoot ? "-" + f.path : f.path)}>
            {unfolded(f, isRoot) ? "▾" : "▸"}
          </button>
        ) : (
          <span className="twisty" />
        )}
        <button className="link folder-name" title={f.path} onClick={() => onFolder(folder === f.path ? null : f.path)}>
          {f.name}
        </button>
        <span className="count">{f.count}</span>
        {isRoot && (
          <button className="icon subtle" title="Remove from the list (files are not deleted)" aria-label={`Remove ${f.name} from the list`} onClick={() => removeRoot(f.path)}>
            ×
          </button>
        )}
      </div>
      {f.children.length > 0 && unfolded(f, isRoot) && <ul role="group">{f.children.map((c) => node(c, depth + 1, false))}</ul>}
    </li>
  );

  return (
    <div className="library-folders">
      <div className="panel-head">
        <h2>Folders</h2>
        <div className="actions">
          <button onClick={() => setAdding((a) => !a)} aria-expanded={adding}>
            + Add folder
          </button>
        </div>
      </div>
      {adding && (
        <form className="add-folder" onSubmit={submit}>
          <button type="button" onClick={browse}>
            Browse…
          </button>
          <span className="muted">or paste a path</span>
          <div className="row">
            <input value={typedPath} onChange={(e) => setTypedPath(e.target.value)} placeholder="C:\Data\measurements  or  /home/me/data" aria-label="Folder path" />
            <button type="submit" className="primary" disabled={!typedPath.trim()}>
              Add
            </button>
          </div>
        </form>
      )}
      <ul className="library-tree" role="tree" aria-label="Folders">
        <li role="treeitem" aria-selected={folder === null}>
          <div className={"library-folder" + (folder === null ? " active" : "")} style={{ paddingLeft: 8 }}>
            <span className="twisty" />
            <button className="link folder-name" onClick={() => onFolder(null)}>
              All folders
            </button>
            <span className="count">{total}</span>
          </div>
        </li>
        {trees.map((t) => node(t, 0, true))}
      </ul>
    </div>
  );
}

// ---- left: the date tree (year → month → day), from each file's `created`

function DateTree({ dates, date, onDate }: { dates: LibraryFacets["dates"]; date: string; onDate: (d: string) => void }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  // the chosen date's year and month are unfolded
  useEffect(() => {
    if (!date) return;
    const [y, m] = date.split("-");
    setOpen((o) => new Set([...o, y, ...(m ? [`${y}-${m}`] : [])]));
  }, [date]);
  const toggle = (k: string) =>
    setOpen((o) => {
      const n = new Set(o);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  const pick = (k: string) => onDate(date === k ? "" : k);
  const years = Object.keys(dates).sort().reverse();
  const sum = (o: { [k: string]: number | { [k: string]: number } }): number =>
    Object.values(o).reduce<number>((n, v) => n + (typeof v === "number" ? v : sum(v)), 0);
  return (
    <div className="library-dates">
      <div className="panel-head">
        <h2>Date</h2>
        {date && (
          <button className="link small" onClick={() => onDate("")}>
            Any date
          </button>
        )}
      </div>
      {years.length === 0 ? (
        <p className="muted small pad">No dates yet.</p>
      ) : (
        <ul className="library-tree" role="tree" aria-label="Dates">
          {years.map((y) => (
            <li key={y} role="treeitem" aria-expanded={open.has(y)} aria-selected={date === y}>
              <div className={"library-folder" + (date === y ? " active" : "")} style={{ paddingLeft: 8 }}>
                <button className="link twisty" aria-label={(open.has(y) ? "Fold " : "Unfold ") + y} onClick={() => toggle(y)}>
                  {open.has(y) ? "▾" : "▸"}
                </button>
                <button className="link folder-name" onClick={() => pick(y)}>
                  {y}
                </button>
                <span className="count">{sum(dates[y])}</span>
              </div>
              {open.has(y) && (
                <ul role="group">
                  {Object.keys(dates[y])
                    .sort()
                    .reverse()
                    .map((m) => {
                      const ym = `${y}-${m}`;
                      return (
                        <li key={ym} role="treeitem" aria-expanded={open.has(ym)} aria-selected={date === ym}>
                          <div className={"library-folder" + (date === ym ? " active" : "")} style={{ paddingLeft: 22 }}>
                            <button className="link twisty" aria-label={(open.has(ym) ? "Fold " : "Unfold ") + `${MONTHS[Number(m) - 1]} ${y}`} onClick={() => toggle(ym)}>
                              {open.has(ym) ? "▾" : "▸"}
                            </button>
                            <button className="link folder-name" onClick={() => pick(ym)}>
                              {MONTHS[Number(m) - 1]}
                            </button>
                            <span className="count">{sum(dates[y][m])}</span>
                          </div>
                          {open.has(ym) && (
                            <ul role="group">
                              {Object.keys(dates[y][m])
                                .sort()
                                .reverse()
                                .map((d) => {
                                  const ymd = `${ym}-${d}`;
                                  return (
                                    <li key={ymd} role="treeitem" aria-selected={date === ymd}>
                                      <div className={"library-folder" + (date === ymd ? " active" : "")} style={{ paddingLeft: 50 }}>
                                        <button className="link folder-name" aria-label={`${Number(d)} ${MONTHS[Number(m) - 1]} ${y}`} onClick={() => pick(ymd)}>
                                          {Number(d)}
                                        </button>
                                        <span className="count">{dates[y][m][d]}</span>
                                      </div>
                                    </li>
                                  );
                                })}
                            </ul>
                          )}
                        </li>
                      );
                    })}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---- right: the selected file

function SelectedFile({ path, row, generation, onOpenIn }: { path: string; row: LibraryRow | null; generation: number; onOpenIn: (path: string, where: "explore" | "figure") => void }) {
  const [info, setInfo] = useState<FileInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  // read again when the file changed (its row's size or time) or another file is shown
  const version = row ? `${row.size}-${row.mtime}-${row.read}` : "";
  useEffect(() => {
    let live = true;
    setError(null);
    api
      .libraryFile(path)
      .then((i) => {
        if (!live) return;
        setInfo(i);
      })
      .catch((e) => {
        if (!live) return;
        setInfo(null);
        setError((e as Error).message);
      });
    return () => {
      live = false;
    };
    // `generation`: a file read here (headers off) fills its row; asking again is cheap (indexed)
  }, [path, version, row === null ? generation : 0]);
  const shown = info && info.path === path ? info : null;
  const date = row ? createdText(row) : shown?.created ?? "";
  return (
    <div className="file-view">
      <div className="file-head">
        <div>
          <h1>{shown?.title || row?.title || baseName(path)}</h1>
          <div className="muted small path" title={path}>
            {path}
          </div>
          {date && (
            <div className="small">
              {date}
              {row?.date_from_file ? <span className="muted"> (file date: the file has no date of its own{row.read ? "" : " read yet"})</span> : null}
            </div>
          )}
        </div>
        <div className="actions">
          <button className="primary" onClick={() => onOpenIn(path, "explore")}>
            Open in Explore
          </button>
          <button onClick={() => onOpenIn(path, "figure")}>Open in Figure</button>
        </div>
      </div>
      {(error || row?.error) && (
        <div className="error-box">
          <strong>This file can't be read.</strong> {error ?? row?.error}
        </div>
      )}
      {!shown && !error && <p className="muted">Reading…</p>}
      {shown && <FileDetails info={shown} metaFilter />}
    </div>
  );
}

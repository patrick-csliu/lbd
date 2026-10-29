import { FormEvent, KeyboardEvent, MouseEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  ApiError,
  AppState,
  baseName,
  FileInfo,
  formatBytes,
  LabelChanges,
  LabelNode,
  LibraryColumn,
  LibraryFacets,
  LibraryFolder,
  LibraryQuery,
  LibraryRow,
  LibrarySettings,
  LibraryStatus,
  MissingLabels,
  Preview,
  PreviewMode,
  SameId,
} from "./api";
import { docsUrl } from "./help";
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
 *
 * Labels (plan 8b): a star, a project, users, tags and a comment per file, kept in a small file in
 * each folder (labels.py), never in the data file. Several files can be selected (Ctrl / Shift /
 * Ctrl+A) and labelled at once; Space stars them. Files that are the same measurement in two
 * places (copies) share their labels; copies that differ are explained in plain words, and the
 * user decides what they are.
 *
 * Previews (plan 8c): a picture of the selected file on the right, drawn by the server
 * (previews.py) as Explore first shows the file, or as chosen in Explore. While stepping with the
 * arrow keys, the rows near the selection are drawn ahead. The list can show pictures instead of
 * rows ("Pictures"): the same files, selection and keys, as a grid.
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
const CARD_W = 220, CARD_H = 206; // px: a picture of the picture view, with its name and date (at least this wide)
const NEAR = 5; // rows above and below the selection whose previews are drawn ahead
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
  { id: "star", title: "★", width: "32px" },
  { id: "project", title: "Project", width: "minmax(120px, 1.2fr)" },
  { id: "users", title: "Users", width: "minmax(120px, 1.2fr)" },
  { id: "tags", title: "Tags", width: "minmax(120px, 1.5fr)" },
  { id: "comment", title: "Comment", width: "minmax(140px, 2fr)" },
  { id: "copies", title: "Copies", width: "70px" },
];
const HELP_COPIES = docsUrl("viewer/library.html", "copies-and-the-same-measurement");
const CONFLICT_TIP = "Looks like a copy of another file, but the two differ — click for details";

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
    case "star":
      return r.star ? "★" : "";
    case "project":
      return r.project ?? "";
    case "users":
      return r.users.join(", ");
    case "tags":
      return r.tags.join(", ");
    case "comment":
      return r.comment.split("\n")[0];
    case "copies":
      return r.copies ? String(r.copies) : "";
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
  const [project, setProject] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [users, setUsers] = useState<string[]>([]);
  const [starred, setStarred] = useState(false);
  const [conflicts, setConflicts] = useState(false);
  useEffect(() => {
    const id = window.setTimeout(() => setQ(typed.trim()), 200);
    return () => window.clearTimeout(id);
  }, [typed]);
  const query: LibraryQuery = useMemo(
    () => ({ folder, q, date, sort, order, project, tags, users, starred, conflicts }),
    [folder, q, date, sort, order, project, tags, users, starred, conflicts],
  );
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
          for (const n of s.notes ?? []) toast(n, "info"); // about labels: told once
        })
        .catch(() => undefined); // the next try reports nothing new; the list keeps what it shows
    ask();
    const id = window.setInterval(ask, 2000);
    return () => {
      live = false;
      window.clearInterval(id);
    };
  }, [toast]);

  /** The index changed because of something done here: show it now, not at the next check. */
  const refresh = useCallback(
    () =>
      api
        .libraryStatus()
        .then((s) => setGeneration(s.generation))
        .catch(() => undefined),
    [],
  );

  // ---- facets: folders with counts, the date tree
  const [facets, setFacets] = useState<LibraryFacets | null>(null);
  useEffect(() => {
    let live = true;
    api
      .libraryFacets(folder, q, date)
      .then((f) => live && setFacets(f))
      .catch((e) => live && toast((e as Error).message, "error"));
    return () => {
      live = false;
    };
  }, [folder, q, date, generation, state.roots, toast]);

  // ---- the rows: pages of PAGE rows, asked for when they come into view
  const [total, setTotal] = useState<number | null>(null);
  const [pages, setPages] = useState<Map<number, LibraryRow[]>>(new Map());
  const asked = useRef<Map<number, string>>(new Map()); // page -> the query+generation it was asked for
  const [listError, setListError] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ top: 0, height: 600, width: 800 });
  const measure = (el: HTMLElement) => setView({ top: el.scrollTop, height: el.clientHeight, width: el.clientWidth });
  // rows, or pictures in a grid: how many items per line, and a line's height
  const pictures = settings.list_view === "pictures";
  const perLine = pictures ? Math.max(1, Math.floor(view.width / CARD_W)) : 1;
  const lineH = pictures ? CARD_H : ROW_H;
  const head = pictures ? 0 : ROW_H; // the column titles above the rows

  // a new query: everything afresh, from the top
  useEffect(() => {
    setPages(new Map());
    asked.current = new Map();
    setTotal(null);
    if (scroller.current) scroller.current.scrollTop = 0;
    setView((v) => ({ ...v, top: 0 }));
  }, [queryKey]);

  const firstPage = Math.max(0, Math.floor((Math.floor(view.top / lineH) * perLine) / PAGE));
  const lastPage = Math.floor(((Math.floor((view.top + view.height) / lineH) + 1) * perLine) / PAGE) + 1;
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

  // ---- several selected files (Ctrl / Shift / Ctrl+A); `selected` is the one last clicked
  const [chosen, setChosen] = useState<string[]>([]);
  useEffect(() => {
    setChosen((c) => (selected && c.includes(selected) ? c : selected ? [selected] : []));
  }, [selected]);
  const loadedRows = (): LibraryRow[] => [...pages.entries()].sort((a, b) => a[0] - b[0]).flatMap(([, rows]) => rows);
  const chosenRows = (): LibraryRow[] => {
    const set = new Set(chosen);
    return loadedRows().filter((r) => set.has(r.path));
  };
  const clickRow = (e: MouseEvent, r: LibraryRow) => {
    if (e.ctrlKey || e.metaKey) {
      setChosen((c) => (c.includes(r.path) ? c.filter((x) => x !== r.path) : [...c, r.path]));
      onSelect(r.path);
    } else if (e.shiftKey && selected) {
      const a = indexOf(selected), b = indexOf(r.path);
      if (a >= 0 && b >= 0) {
        const [lo, hi] = a < b ? [a, b] : [b, a];
        const range: string[] = [];
        for (let i = lo; i <= hi; i++) {
          const x = rowAt(i);
          if (x) range.push(x.path);
        }
        setChosen(range);
      }
    } else {
      setChosen([r.path]);
      onSelect(r.path);
    }
  };

  // ---- labels and identities: what the right column, the menu and the keys change
  const [pointing, setPointing] = useState<MissingLabels | null>(null); // missing labels waiting for a file
  const [showMissing, setShowMissing] = useState(false);
  const run = async (what: Promise<{ notes: string[] }>, done?: string) => {
    try {
      const r = await what;
      for (const n of r.notes) toast(n, "info");
      if (done) toast(done);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      refresh();
    }
  };
  const label = (paths: string[], changes: LabelChanges) => run(api.librarySetLabels(paths, changes));
  const toggleStar = (rows: LibraryRow[]) => rows.length && label(rows.map((r) => r.path), { star: !rows.every((r) => r.star) });

  const onScroll = () => {
    const el = scroller.current;
    if (el) measure(el);
  };
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const ro = new ResizeObserver(() => measure(el));
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
      const top = Math.floor(i / perLine) * lineH, bottom = top + lineH + head;
      if (top < el.scrollTop) el.scrollTop = Math.max(0, top);
      else if (bottom > el.scrollTop + el.clientHeight) el.scrollTop = bottom - el.clientHeight;
      measure(el);
    }
  };

  // the previews of the rows near the selection are drawn ahead, so stepping shows them at once
  useEffect(() => {
    const i = indexOf(selected);
    if (i < 0 || settings.previews === "off") return;
    const near: string[] = [];
    for (let k = 1; k <= NEAR; k++)
      for (const j of [i + k, i - k]) {
        const r = rowAt(j);
        if (r && !r.error) near.push(r.path);
      }
    if (near.length) api.libraryPreviewWant(near, false).catch(() => undefined); // only ahead of time: no need to tell
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, pages, settings.previews]);

  const setListView = async (v: LibrarySettings["list_view"]) => {
    try {
      onLibrarySettings(await api.setLibrary({ list_view: v }));
    } catch (e) {
      toast((e as Error).message, "error");
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

  const askText = (title: string, action: string, value: string, what: string, apply: (v: string) => Promise<void>) =>
    setConfirm({
      title,
      action,
      input: { value, check: (v) => (v.trim() ? null : `Type ${what}`) },
      onConfirm: (v) => apply(v.trim()),
    });

  const askNewMeasurement = (r: LibraryRow) =>
    setConfirm({
      title: "Make this a new measurement?",
      text:
        `${r.path} gets its own identity. It is written into this file only (a small change to its header); ` +
        "the other file is not touched. Its labels are kept and stop following the other file's.",
      action: "Make it a new measurement",
      onConfirm: () => run(api.libraryResolve(r.path, "new_id"), `${r.name} is now a separate measurement`),
    });

  const askGiveIds = (rows: LibraryRow[]) =>
    setConfirm({
      title: rows.length === 1 ? "Give this file an identity?" : `Give ${rows.length} files an identity?`,
      text:
        "Files written before LBD 1.3 (or by other programs) have no hidden identity, so LBD follows them by name and date. " +
        "This writes one into each file's header (its data is not changed), so their labels follow them anywhere.",
      action: "Give them an identity",
      onConfirm: () => run(api.libraryGiveIds(rows.map((x) => x.path))),
    });

  const rowMenu = (e: MouseEvent | KeyboardEvent, r: LibraryRow) => {
    e.preventDefault();
    const many = chosen.includes(r.path) && chosen.length > 1;
    if (!many) {
      setChosen([r.path]);
      onSelect(r.path);
    }
    const rows = many ? chosenRows() : [r];
    const paths = rows.map((x) => x.path);
    const allStarred = rows.every((x) => x.star);
    const which = rows.length > 1 ? `${rows.length} files` : r.name;
    const withoutId = rows.filter((x) => !x.id && x.read && !x.error);
    const items: MenuEntry[] = [
      { label: allStarred ? "Unstar" : "Star", onClick: () => toggleStar(rows) },
      { label: "Add tag…", onClick: () => askText(`Add a tag to ${which}`, "Add", "", "a tag", (v) => label(paths, { add_tags: [v] })) },
      { label: "Set project…", onClick: () => askText(`Project of ${which}`, "Set", rows[0].project ?? "", "a project", (v) => label(paths, { project: v })) },
      { label: "Add user…", onClick: () => askText(`Add a user to ${which}`, "Add", state.login, "a user", (v) => label(paths, { add_users: [v] })) },
    ];
    // the measurement's identity (copies, older files)
    const identity: MenuEntry[] = [
      ...(rows.length === 1
        ? [
            { label: "Duplicate as new measurement", onClick: () => run(api.libraryDuplicate(r.path).then((d) => ({ notes: [`Copied as ${baseName(d.path)}`, ...d.notes] }))) },
            ...(r.copies || r.conflict ? [{ label: "Make this a new measurement…", onClick: () => askNewMeasurement(r) }] : []),
          ]
        : []),
      ...(withoutId.length ? [{ label: withoutId.length === 1 ? "Give this file an identity…" : `Give ${withoutId.length} files an identity…`, onClick: () => askGiveIds(withoutId) }] : []),
    ];
    if (identity.length) items.push("-", ...identity);
    if (!many)
      // one file: also what can be done with the file itself
      items.push(
        "-",
        { label: "Open in Explore", onClick: () => onOpenIn(r.path, "explore") },
        { label: "Open in Figure", onClick: () => onOpenIn(r.path, "figure") },
        "-",
        ...fileEntries(r.path, state.platform, toast),
        { label: "Open in new browser tab", onClick: () => onOpenInNewBrowserTab(r.path) },
        "-",
        { label: "Rename…", onClick: () => setConfirm(renameRequest(r.path, (newPath) => onRenamed(r.path, newPath), toast)) },
        { label: `Move to ${names.trash}…`, onClick: () => askTrash(r.path), danger: true },
      );
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
    const page = scroller.current ? Math.max(1, Math.floor(scroller.current.clientHeight / lineH) - 1) * perLine : perLine;
    if (e.key.startsWith("Arrow")) setChosen([]); // keys move one selection
    if (e.key === "ArrowDown") selectIndex(i < 0 ? 0 : Math.min((total ?? 1) - 1, i + perLine));
    else if (e.key === "ArrowUp") selectIndex(Math.max(0, i - perLine));
    else if (e.key === "ArrowRight" && pictures) selectIndex(i < 0 ? 0 : i + 1);
    else if (e.key === "ArrowLeft" && pictures) selectIndex(Math.max(0, i - 1));
    else if (e.key === "Home") selectIndex(0);
    else if (e.key === "End" && total) selectIndex(total - 1);
    else if (e.key === "PageDown") selectIndex(Math.min((total ?? 1) - 1, Math.max(0, i) + page));
    else if (e.key === "PageUp") selectIndex(Math.max(0, i - page));
    else if (e.key === "Enter" && selected) onOpenIn(selected, e.shiftKey ? "figure" : "explore");
    else if (e.key === " ") toggleStar(chosenRows());
    else if ((e.ctrlKey || e.metaKey) && (e.key === "a" || e.key === "A")) setChosen(loadedRows().map((r) => r.path));
    else if (e.key === "Escape" && pointing) setPointing(null);
    else if (isMenuKey(e) && selectedRow) rowMenu(e, selectedRow);
    else return;
    e.preventDefault();
  };

  // ---- the status line
  const shownFolder = folder && facets ? findFolder(facets.folders, folder) : null;
  const all = folder ? shownFolder?.count : facets?.folders.reduce((n, f) => n + f.count, 0);
  const filtered = !!(q || date || project || tags.length || users.length || starred || conflicts);
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
        <LabelFilters
          facets={facets}
          project={project}
          tags={tags}
          users={users}
          starred={starred}
          conflicts={conflicts}
          onProject={setProject}
          onTags={setTags}
          onUsers={setUsers}
          onStarred={setStarred}
          onConflicts={setConflicts}
          onMissing={() => setShowMissing(true)}
        />
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
          {project && (
            <span className="chip">
              project {project}
              <button className="link" aria-label="Any project" onClick={() => setProject("")}>
                ×
              </button>
            </span>
          )}
          {users.map((u) => (
            <span key={"u" + u} className="chip">
              user {u}
              <button className="link" aria-label={`Not only user ${u}`} onClick={() => setUsers(users.filter((x) => x !== u))}>
                ×
              </button>
            </span>
          ))}
          {tags.map((t) => (
            <span key={"t" + t} className="chip">
              tag {t}
              <button className="link" aria-label={`Not only tag ${t}`} onClick={() => setTags(tags.filter((x) => x !== t))}>
                ×
              </button>
            </span>
          ))}
          {starred && (
            <span className="chip">
              ★ starred
              <button className="link" aria-label="Starred or not" onClick={() => setStarred(false)}>
                ×
              </button>
            </span>
          )}
          {conflicts && (
            <span className="chip">
              ⚠ copies that differ
              <button className="link" aria-label="All files, not only copies that differ" onClick={() => setConflicts(false)}>
                ×
              </button>
            </span>
          )}
          {chosen.length > 1 && <span className="muted">{chosen.length} selected</span>}
          {!settings.read_headers && <span className="muted">names only: reading files' details is off in ⚙</span>}
          {status?.indexing && (
            <span className="muted">
              Indexing {status.done.toLocaleString()} of {status.total.toLocaleString()}…
            </span>
          )}
          {status?.previews && status.previews.mode === "all" && status.previews.drawing > 0 && (
            <span className="muted" title="Previews of every file are drawn in the background (⚙ Settings → Library)">
              Drawing previews {status.previews.drawn.toLocaleString()} of {status.previews.total.toLocaleString()}…
            </span>
          )}
          <span className="list-view-switch" role="group" aria-label="Show the files as">
            <button className={pictures ? "" : "on"} aria-pressed={!pictures} onClick={() => setListView("list")} title="The files as rows">
              List
            </button>
            <button className={pictures ? "on" : ""} aria-pressed={pictures} onClick={() => setListView("pictures")} title="The files as pictures">
              Pictures
            </button>
          </span>
          {status && status.errors.length > 0 && (
            <span className="warn" title={status.errors.map((e) => `${e.path}: ${e.error}`).join("\n")}>
              {status.errors.length} folder(s) or file(s) couldn't be read (point here for which)
            </span>
          )}
        </div>
        {listError && <div className="error-box">{listError}</div>}
        {!!facets?.conflicts && !conflicts && (
          <div className="library-conflicts" role="note">
            ⚠ {facets.conflicts} files look like copies of each other but differ.{" "}
            <button className="link" onClick={() => setConflicts(true)}>
              Show them
            </button>
          </div>
        )}
        {pointing && (
          <div className="library-pointing" role="note">
            Click the file the labels of <strong>{pointing.name}</strong> belong to.{" "}
            <button className="link" onClick={() => setPointing(null)}>
              Cancel
            </button>
          </div>
        )}

        <div
          className={"library-list" + (pictures ? " pictures" : "")}
          ref={scroller}
          onScroll={onScroll}
          onKeyDown={onListKey}
          tabIndex={0}
          role="grid"
          aria-label="Data files"
          aria-rowcount={total ?? undefined}
        >
          {pictures ? (
            <div className="library-cards" style={{ height: Math.ceil((total ?? 0) / perLine) * CARD_H }}>
              {Array.from({ length: Math.max(0, Math.min(total ?? 0, (lastPage + 1) * PAGE) - firstPage * PAGE) }, (_, k) => {
                const i = firstPage * PAGE + k;
                const top = Math.floor(i / perLine) * CARD_H;
                if (top + CARD_H < view.top - CARD_H || top > view.top + view.height + CARD_H) return null;
                const width = view.width / perLine;
                const r = rowAt(i);
                if (!r) return <div key={`empty-${i}`} className="library-card loading" style={{ top, left: (i % perLine) * width, width }} />;
                const on = r.path === selected || chosen.includes(r.path);
                return (
                  <PictureCard
                    key={r.path}
                    row={r}
                    generation={generation}
                    selected={on}
                    style={{ top, left: (i % perLine) * width, width }}
                    onClick={(e) => {
                      clickRow(e, r);
                      scroller.current?.focus({ preventScroll: true });
                    }}
                    onDoubleClick={() => onOpenIn(r.path, "explore")}
                    onContextMenu={(e) => rowMenu(e, r)}
                  />
                );
              })}
            </div>
          ) : (
          <>
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
                  className={
                    "library-row" +
                    (r.path === selected || chosen.includes(r.path) ? " selected" : "") +
                    (r.error ? " unreadable" : "") +
                    (r.star ? " starred" : "") +
                    (r.conflict ? " conflict" : "")
                  }
                  style={{ top, gridTemplateColumns: gridColumns }}
                  role="row"
                  aria-rowindex={i + 1}
                  aria-selected={r.path === selected || chosen.includes(r.path)}
                  title={r.error ? `Can't be read: ${r.error}` : r.conflict ? CONFLICT_TIP : r.path}
                  onClick={(e) => {
                    if (pointing) {
                      const entry = pointing;
                      setPointing(null);
                      run(api.libraryMissingResolve(entry, r.path), `The labels of ${entry.name} now belong to ${r.name}`);
                      return;
                    }
                    clickRow(e, r);
                    scroller.current?.focus({ preventScroll: true });
                  }}
                  onDoubleClick={() => onOpenIn(r.path, "explore")}
                  onContextMenu={(e) => rowMenu(e, r)}
                >
                  {columns.map((c) => (
                    <div key={c.id} role="gridcell" className={`cell-${c.id}`}>
                      {c.id === "name" && r.conflict ? (
                        <span className="mark-conflict" title={CONFLICT_TIP} aria-label="differs from its copy">
                          ⚠{" "}
                        </span>
                      ) : null}
                      {c.id === "name" && r.star ? <span className="mark-star" aria-label="starred">★ </span> : null}
                      {cellText(r, c.id)}
                      {c.id === "name" && r.copies > 0 && !r.conflict ? (
                        <span className="mark-copies muted small" title="The same measurement is also elsewhere (labels are shared)">
                          {" "}
                          {r.copies + 1} copies
                        </span>
                      ) : null}
                      {c.id === "date" && r.date_from_file ? <span className="muted small"> (file date)</span> : null}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
          </>
          )}
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
        {showMissing ? (
          <MissingPanel
            generation={generation}
            onClose={() => setShowMissing(false)}
            onPoint={(m) => {
              setPointing(m);
              setShowMissing(false);
            }}
            onDiscard={(m) =>
              setConfirm({
                title: "Discard these labels?",
                text: `The labels of ${m.name} (its file can't be found) are removed from ${m.folder}. The data files are not touched.`,
                action: "Discard",
                danger: true,
                onConfirm: () => run(api.libraryMissingResolve(m, null)),
              })
            }
          />
        ) : chosen.length > 1 ? (
          <div className="file-view">
            <div className="file-head">
              <h1>{chosen.length} files selected</h1>
            </div>
            <LabelsEditor rows={chosenRows()} facets={facets} login={state.login} onChange={(c) => label(chosenRows().map((r) => r.path), c)} />
          </div>
        ) : selected ? (
          <SelectedFile path={selected} row={selectedRow} generation={generation} onOpenIn={onOpenIn}>
            {selectedRow && !selectedRow.error && (
              <>
                <LabelsEditor rows={[selectedRow]} facets={facets} login={state.login} onChange={(c) => label([selectedRow.path], c)} />
                {(selectedRow.copies > 0 || !!selectedRow.conflict) && (
                  <SameIdBox
                    row={selectedRow}
                    generation={generation}
                    onShow={(path) => {
                      setFolder(null);
                      setConflicts(false);
                      setChosen([path]);
                      onSelect(path);
                    }}
                    onNew={() => askNewMeasurement(selectedRow)}
                    onSame={() => run(api.libraryResolve(selectedRow.path, "same"), "They count as the same measurement again")}
                    onTrash={() => askTrash(selectedRow.path)}
                  />
                )}
              </>
            )}
          </SelectedFile>
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

function SelectedFile({
  path,
  row,
  generation,
  onOpenIn,
  children,
}: {
  path: string;
  row: LibraryRow | null;
  generation: number;
  onOpenIn: (path: string, where: "explore" | "figure") => void;
  children?: ReactNode;
}) {
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
      {!row?.error && <PreviewBox path={path} version={`${version}-${generation}`} />}
      {children}
      {!shown && !error && <p className="muted">Reading…</p>}
      {shown && <FileDetails info={shown} metaFilter />}
    </div>
  );
}

// ---- previews (plan 8c, previews.py)

/** A file's preview, asked for again when `version` changes; asked again while it is drawn.
 * `now`: the selected file (drawn first); else a picture in view (drawn after it). */
function usePreview(path: string, version: string, now: boolean, nonce = 0): { preview: Preview | null; url: string | null; error: string | null } {
  const [got, setGot] = useState<{ path: string; preview: Preview; url: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const shown = useRef<string | null>(null); // the picture's object URL, freed when replaced
  useEffect(() => {
    let live = true;
    let timer = 0;
    const stop = new AbortController();
    const ask = () =>
      api
        .libraryPreview(path, now, stop.signal)
        .then((p) => {
          if (!live) return;
          setError(null);
          const url = p.picture ? URL.createObjectURL(p.picture) : null;
          if (shown.current) URL.revokeObjectURL(shown.current);
          shown.current = url;
          setGot({ path, preview: p, url });
          if (!p.picture && p.state === "drawing") timer = window.setTimeout(ask, now ? 400 : 1500);
        })
        .catch((e) => {
          if (live && (e as Error).name !== "AbortError") setError((e as Error).message);
        });
    ask();
    return () => {
      live = false;
      stop.abort();
      window.clearTimeout(timer);
    };
  }, [path, version, now, nonce]);
  useEffect(
    () => () => {
      if (shown.current) URL.revokeObjectURL(shown.current);
    },
    [],
  );
  const mine = got && got.path === path ? got : null;
  return { preview: mine?.preview ?? null, url: mine?.url ?? null, error };
}

function dateTime(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** The selected file's preview, with what it shows and, for a chosen one, Reset. */
function PreviewBox({ path, version }: { path: string; version: string }) {
  const toast = useToast();
  const [nonce, setNonce] = useState(0);
  const { preview, url, error } = usePreview(path, version, true, nonce);
  const again = () => setNonce((n) => n + 1);
  const show = () =>
    api
      .libraryPreviewWant([path], true)
      .then(again)
      .catch((e) => toast((e as Error).message, "error"));
  const reset = () =>
    api
      .libraryPreviewReset(path)
      .then(again)
      .catch((e) => toast((e as Error).message, "error"));
  let inside: ReactNode;
  if (url) inside = <img src={url} alt="Preview of the file" />;
  else if (error) inside = <span className="warn">The preview couldn't be asked for: {error}</span>;
  else if (!preview || (!preview.picture && preview.state === "drawing")) inside = <span className="muted">Drawing the preview…</span>;
  else if (!preview.picture && preview.state === "off")
    inside = (
      <span className="muted">
        Previews are off (⚙ Settings → Library).{" "}
        <button onClick={show}>Show preview</button>
      </span>
    );
  else if (!preview.picture) inside = <span className="muted">No preview: {preview.reason}</span>;
  return (
    <div className="preview" aria-label="Preview">
      <div className="preview-box" data-state={url ? "picture" : preview && !preview.picture ? preview.state : "asking"}>
        {inside}
      </div>
      {preview?.picture && (
        <div className="preview-about small muted">
          {preview.source === "chosen" ? (
            <>
              Chosen in Explore on {dateTime(preview.chosen_at)}
              {preview.changed_since && <span className="warn"> — before the file last changed; choose again in Explore to show its data now</span>}
              .{" "}
              <button className="link" onClick={reset} title="Show the automatic preview again (as Explore first shows the file)">
                Reset preview
              </button>
            </>
          ) : (
            <>As Explore first shows the file. To show another view here: Explore → Library preview.</>
          )}
        </div>
      )}
    </div>
  );
}

/** A file in the picture view: its preview, name, date and marks. */
function PictureCard({
  row,
  generation,
  selected,
  style,
  onClick,
  onDoubleClick,
  onContextMenu,
}: {
  row: LibraryRow;
  generation: number;
  selected: boolean;
  style: React.CSSProperties;
  onClick: (e: MouseEvent) => void;
  onDoubleClick: () => void;
  onContextMenu: (e: MouseEvent) => void;
}) {
  const { preview, url } = usePreview(row.path, `${row.size}-${row.mtime}-${generation}`, false);
  const name = row.title || row.name;
  return (
    <div
      className={"library-card" + (selected ? " selected" : "") + (row.error ? " unreadable" : "") + (row.conflict ? " conflict" : "")}
      style={style}
      role="row"
      aria-selected={selected}
      title={row.error ? `Can't be read: ${row.error}` : row.conflict ? CONFLICT_TIP : row.path}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onContextMenu={onContextMenu}
    >
      <div className="card-picture" role="gridcell">
        {url ? (
          <img src={url} alt="" />
        ) : (
          <span className="muted small">
            {row.error ? "Can't be read" : !preview || (!preview.picture && preview.state === "drawing") ? "Drawing…" : !preview.picture && preview.state === "off" ? "Previews are off" : "No preview"}
          </span>
        )}
      </div>
      <div className="card-name" role="gridcell">
        {row.conflict ? <span className="mark-conflict" aria-label="differs from its copy">⚠ </span> : null}
        {row.star ? <span className="mark-star" aria-label="starred">★ </span> : null}
        {name}
      </div>
      <div className="card-date muted small">{createdText(row)}</div>
    </div>
  );
}

/** Settings → Library: which previews are drawn, and the picture cache. */
export function PreviewSettings({ settings, onSettings }: { settings: LibrarySettings; onSettings: (s: AppState) => void }) {
  const toast = useToast();
  const [cache, setCache] = useState<{ count: number; bytes: number } | null>(null);
  // the choice shows at once; the viewer's answer (or a refusal, with the old value) follows
  const [mode, setMode] = useState(settings.previews);
  useEffect(() => setMode(settings.previews), [settings.previews]);
  const measure = useCallback(() => api.libraryPreviewCache().then(setCache).catch(() => setCache(null)), []);
  useEffect(() => {
    measure();
  }, [measure]);
  const choose = async (chosen: PreviewMode) => {
    setMode(chosen);
    try {
      onSettings(await api.setLibrary({ previews: chosen }));
    } catch (e) {
      setMode(settings.previews);
      toast((e as Error).message, "error");
    }
  };
  const empty = async () => {
    try {
      const { freed } = await api.libraryPreviewClear();
      toast(`Emptied the picture cache (${formatBytes(freed)}); previews are drawn again as needed.`);
      measure();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const choices: [PreviewMode, string][] = [
    ["all", "Every file, drawn in the background (previews show at once)"],
    ["nearby", "The selected file and the rows near it"],
    ["off", "Only when I click Show preview"],
  ];
  return (
    <>
      <div className="settings-subtitle">Previews</div>
      {choices.map(([value, label]) => {
        const blocked = value === "all" && !settings.read_headers;
        return (
          <label key={value} className={"settings-choice" + (blocked ? " disabled" : "")}
                 title={blocked ? 'Needs "Read each data file\'s details": drawing every preview reads every file' : undefined}>
            <input type="radio" name="previews" disabled={blocked} checked={mode === value && !blocked}
                   onChange={() => choose(value)} />
            {label}
          </label>
        );
      })}
      {!settings.read_headers && (
        <p className="settings-note small muted">
          "Every file" needs "Read each data file's details" on: drawing every preview reads every file{settings.previews === "all" ? "; until then, the selected file and the rows near it are drawn" : ""}.
        </p>
      )}
      <p className="settings-note small muted">
        Picture cache: {cache ? `${cache.count.toLocaleString()} picture${cache.count === 1 ? "" : "s"}, ${formatBytes(cache.bytes)}` : "…"}{" "}
        <button className="link" onClick={empty} disabled={!cache || cache.count === 0}>
          Empty
        </button>
        <br />
        Previews you chose in Explore are kept.
      </p>
    </>
  );
}

// ---- left: projects, users and tags (nested), starred, copies that differ, missing labels

function LabelFilters(props: {
  facets: LibraryFacets | null;
  project: string;
  tags: string[];
  users: string[];
  starred: boolean;
  conflicts: boolean;
  onProject: (p: string) => void;
  onTags: (t: string[]) => void;
  onUsers: (u: string[]) => void;
  onStarred: (s: boolean) => void;
  onConflicts: (c: boolean) => void;
  onMissing: () => void;
}) {
  const { facets, project, tags, users, starred, conflicts } = props;
  const many = (list: string[], set: (l: string[]) => void) => (label: string) =>
    set(list.includes(label) ? list.filter((x) => x !== label) : [...list, label]);
  return (
    <div className="library-labels">
      <div className="panel-head">
        <h2>Labels</h2>
      </div>
      <div className="library-label-switches">
        <label className="check">
          <input type="checkbox" checked={starred} onChange={(e) => props.onStarred(e.target.checked)} />★ Starred only
          <span className="count">{facets?.starred ?? 0}</span>
        </label>
        {!!facets?.conflicts && (
          <label className="check" title="Files that look like copies of each other but differ">
            <input type="checkbox" checked={conflicts} onChange={(e) => props.onConflicts(e.target.checked)} />⚠ Copies that differ
            <span className="count">{facets.conflicts}</span>
          </label>
        )}
        {!!facets?.missing && (
          <button className="link" onClick={props.onMissing} title="Labels whose file was renamed, moved or deleted outside LBD">
            Missing files: {facets.missing}
          </button>
        )}
      </div>
      <LabelTree title="Project" nodes={facets?.projects ?? []} chosen={project ? [project] : []} onPick={(l) => props.onProject(project === l ? "" : l)} />
      <LabelTree title="Users" nodes={facets?.users ?? []} chosen={users} onPick={many(users, props.onUsers)} />
      <LabelTree title="Tags" nodes={facets?.tags ?? []} chosen={tags} onPick={many(tags, props.onTags)} />
    </div>
  );
}

function LabelTree({ title, nodes, chosen, onPick }: { title: string; nodes: LabelNode[]; chosen: string[]; onPick: (label: string) => void }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (k: string) =>
    setOpen((o) => {
      const n = new Set(o);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  const node = (n: LabelNode, depth: number): ReactNode => (
    <li key={n.label} role="treeitem" aria-selected={chosen.includes(n.label)} aria-expanded={n.children.length ? open.has(n.label) : undefined}>
      <div className={"library-folder" + (chosen.includes(n.label) ? " active" : "")} style={{ paddingLeft: 8 + depth * 14 }}>
        {n.children.length ? (
          <button className="link twisty" aria-label={(open.has(n.label) ? "Fold " : "Unfold ") + n.label} onClick={() => toggle(n.label)}>
            {open.has(n.label) ? "▾" : "▸"}
          </button>
        ) : (
          <span className="twisty" />
        )}
        <button className="link folder-name" title={n.label} onClick={() => onPick(n.label)}>
          {n.name}
        </button>
        <span className="count">{n.count}</span>
      </div>
      {n.children.length > 0 && open.has(n.label) && <ul role="group">{n.children.map((c) => node(c, depth + 1))}</ul>}
    </li>
  );
  if (!nodes.length) return null;
  return (
    <div className="library-label-tree">
      <h3 className="small">{title}</h3>
      <ul className="library-tree" role="tree" aria-label={title}>
        {nodes.map((n) => node(n, 0))}
      </ul>
    </div>
  );
}

// ---- right: the labels of one or several files

/** Every label of a tree, with its depth: the picker's list. */
function flatten(nodes: LabelNode[], depth = 0): { node: LabelNode; depth: number }[] {
  return nodes.flatMap((n) => [{ node: n, depth }, ...flatten(n.children, depth + 1)]);
}

function LabelsEditor({ rows, facets, login, onChange }: { rows: LibraryRow[]; facets: LibraryFacets | null; login: string; onChange: (c: LabelChanges) => Promise<void> | void }) {
  const n = rows.length;
  const [picking, setPicking] = useState<"project" | "users" | "tags" | null>(null);
  const comments = [...new Set(rows.map((r) => r.comment))];
  const [comment, setComment] = useState(comments.length === 1 ? comments[0] : "");
  const key = rows.map((r) => r.path).join("|") + "|" + comments.join("|");
  useEffect(() => setComment(comments.length === 1 ? comments[0] : ""), [key]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!n) return null;
  const allStarred = rows.every((r) => r.star);
  const projects = [...new Set(rows.map((r) => r.project ?? ""))];
  const counts = (key: "users" | "tags") => {
    const m = new Map<string, number>();
    for (const r of rows) for (const l of r[key]) m.set(l, (m.get(l) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  };
  const saveComment = () => {
    if (comments.length === 1 ? comment !== comments[0] : comment.trim()) onChange({ comment });
  };
  const chips = (key: "users" | "tags") => (
    <div className="label-chips" aria-label={key === "users" ? "Users" : "Tags"}>
      {counts(key).map(([l, k]) => (
        <span key={l} className="chip">
          {l}
          {k < n && <span className="muted small"> ({k} of {n})</span>}
          <button className="link" aria-label={`Remove ${key === "users" ? "user" : "tag"} ${l}`} onClick={() => onChange(key === "users" ? { remove_users: [l] } : { remove_tags: [l] })}>
            ×
          </button>
        </span>
      ))}
      <button className="link" onClick={() => setPicking(picking === key ? null : key)} aria-label={key === "users" ? "Add a user" : "Add a tag"}>
        + Add
      </button>
      {picking === key && (
        <LabelPicker
          nodes={(key === "users" ? facets?.users : facets?.tags) ?? []}
          first={key === "users" ? login : undefined}
          placeholder={key === "users" ? "A user (group/sub-group/name), or pick one" : "A tag (nested with /), or pick one"}
          onPick={(l) => {
            setPicking(null);
            onChange(key === "users" ? { add_users: [l] } : { add_tags: [l] });
          }}
          onClose={() => setPicking(null)}
        />
      )}
    </div>
  );
  return (
    <div className="library-labels-editor" aria-label="Labels">
      <h3>Labels{n > 1 ? ` of ${n} files` : ""}</h3>
      <div className="label-row">
        <button className={"star-button" + (allStarred ? " on" : "")} aria-pressed={allStarred} onClick={() => onChange({ star: !allStarred })} title="Star (Space in the list)">
          {allStarred ? "★ Starred" : "☆ Star"}
        </button>
      </div>
      <div className="label-row">
        <span className="label-name">Project</span>
        <div className="label-chips" aria-label="Project">
          {projects.length === 1 && projects[0] ? (
            <span className="chip">
              {projects[0]}
              <button className="link" aria-label="Remove the project" onClick={() => onChange({ project: "" })}>
                ×
              </button>
            </span>
          ) : projects.length > 1 ? (
            <span className="muted small">several projects</span>
          ) : null}
          <button className="link" onClick={() => setPicking(picking === "project" ? null : "project")} aria-label="Set the project">
            {projects.length === 1 && projects[0] ? "Change" : "Set"}
          </button>
          {picking === "project" && (
            <LabelPicker
              nodes={facets?.projects ?? []}
              placeholder="A project (nested with /), or pick one"
              onPick={(l) => {
                setPicking(null);
                onChange({ project: l });
              }}
              onClose={() => setPicking(null)}
            />
          )}
        </div>
      </div>
      <div className="label-row">
        <span className="label-name">Users</span>
        {chips("users")}
      </div>
      <div className="label-row">
        <span className="label-name">Tags</span>
        {chips("tags")}
      </div>
      <div className="label-row">
        <span className="label-name">Comment</span>
        <textarea
          aria-label="Comment"
          value={comment}
          placeholder={comments.length > 1 ? "(different comments; typing here replaces them all)" : "Notes about this data (saved when you leave the box)"}
          onChange={(e) => setComment(e.target.value)}
          onBlur={saveComment}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) (e.target as HTMLTextAreaElement).blur();
          }}
          rows={3}
        />
      </div>
    </div>
  );
}

function LabelPicker({ nodes, first, placeholder, onPick, onClose }: { nodes: LabelNode[]; first?: string; placeholder: string; onPick: (label: string) => void; onClose: () => void }) {
  const [text, setText] = useState("");
  const t = text.trim().toLowerCase();
  const items = flatten(nodes).filter(({ node }) => !t || node.label.toLowerCase().includes(t));
  const suggested = first && (!t || first.toLowerCase().includes(t)) && !items.some(({ node }) => node.label === first) ? first : null;
  return (
    <div className="label-picker" role="dialog" aria-label="Pick a label">
      <input
        autoFocus
        value={text}
        placeholder={placeholder}
        aria-label="Label"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && text.trim()) onPick(text.trim());
          if (e.key === "Escape") onClose();
        }}
      />
      <ul>
        {suggested && (
          <li>
            <button className="link" onClick={() => onPick(suggested)}>
              {suggested} <span className="muted small">(this computer's user)</span>
            </button>
          </li>
        )}
        {items.map(({ node, depth }) => (
          <li key={node.label} style={{ paddingLeft: depth * 14 }}>
            <button className="link" title={node.label} onClick={() => onPick(node.label)}>
              {node.name} <span className="muted small">{node.count}</span>
            </button>
          </li>
        ))}
        {text.trim() && !items.some(({ node }) => node.label === text.trim()) && (
          <li>
            <button className="link" onClick={() => onPick(text.trim())}>
              New: {text.trim()}
            </button>
          </li>
        )}
      </ul>
      <button className="link small" onClick={onClose}>
        Close
      </button>
    </div>
  );
}

// ---- right: the same measurement in another place (copies, or copies that differ)

function SameIdBox({
  row,
  generation,
  onShow,
  onNew,
  onSame,
  onTrash,
}: {
  row: LibraryRow;
  generation: number;
  onShow: (path: string) => void;
  onNew: () => void;
  onSame: () => void;
  onTrash: () => void;
}) {
  const [same, setSame] = useState<SameId | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api
      .librarySame(row.path)
      .then((s) => live && (setSame(s), setError(null)))
      .catch((e) => live && setError((e as Error).message));
    return () => {
      live = false;
    };
  }, [row.path, row.size, row.mtime, row.conflict, generation]);
  if (error) return <div className="error-box">{error}</div>;
  if (!same || !same.others.length) return null;
  const help = (
    <a href={HELP_COPIES} target="_blank" rel="noopener">
      What is this?
    </a>
  );
  if (!same.conflict)
    return (
      <div className="library-copies" role="note" aria-label="Copies">
        {same.others.map((o) => (
          <div key={o.path}>
            Also at: <span className="path small">{o.path}</span> (an identical copy; labels are shared){" "}
            <button className="link" onClick={() => onShow(o.path)}>
              Show it
            </button>
          </div>
        ))}
        {help}
      </div>
    );
  return (
    <div className="library-conflict" role="region" aria-label="Copies of one measurement that differ">
      <h3>⚠ Copies of one measurement that differ</h3>
      <p>
        LBD gives every measurement a hidden identity when it is first saved, so it can recognise the same measurement in two places (a backup, a
        shared folder). These two files have the same identity, but their contents are no longer the same — one was probably changed after it was
        copied. {help}
      </p>
      <table className="conflict-files small">
        <thead>
          <tr>
            <th />
            <th>This file</th>
            {same.others.map((o) => (
              <th key={o.path}>The other file</th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <th>Where</th>
            <td className="path">{row.path}</td>
            {same.others.map((o) => (
              <td key={o.path} className="path">
                {o.path}{" "}
                <button className="link" onClick={() => onShow(o.path)}>
                  Show it
                </button>
              </td>
            ))}
          </tr>
          <tr>
            <th>Size</th>
            <td>{formatBytes(row.size)}</td>
            {same.others.map((o) => (
              <td key={o.path}>{formatBytes(o.size)}</td>
            ))}
          </tr>
          <tr>
            <th>Last changed</th>
            <td>
              {localTime(row.mtime)}
              {same.others.every((o) => !o.newer) ? <strong> (newer)</strong> : null}
            </td>
            {same.others.map((o) => (
              <td key={o.path}>
                {localTime(o.mtime)}
                {o.newer ? <strong> (newer)</strong> : null}
              </td>
            ))}
          </tr>
          <tr>
            <th>What differs</th>
            <td colSpan={same.others.length + 1} className="conflict-differs">
              {[...new Set(same.others.flatMap((o) => o.differs))].join(", ")}
            </td>
          </tr>
        </tbody>
      </table>
      <p className="small">What would you like to do? Nothing changes until you choose.</p>
      <ul className="conflict-actions">
        <li>
          <button onClick={onNew}>Make this a new measurement</button>
          <span className="small">
            {" "}
            This file gets its own identity; it is written into this file only, and the other file is not touched. Its labels are kept and stop
            following the other file's.
          </span>
        </li>
        <li>
          <button onClick={onSame}>They are the same measurement</button>
          <span className="small"> Nothing is written into either file; LBD remembers it, and their labels follow each other again.</span>
        </li>
        <li>
          <button onClick={onTrash}>Move this one to the Recycle Bin…</button>
          <span className="small"> You can get it back from there.</span>
        </li>
      </ul>
    </div>
  );
}

// ---- right: labels whose file can't be found

function MissingPanel({
  generation,
  onClose,
  onPoint,
  onDiscard,
}: {
  generation: number;
  onClose: () => void;
  onPoint: (m: MissingLabels) => void;
  onDiscard: (m: MissingLabels) => void;
}) {
  const [missing, setMissing] = useState<MissingLabels[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api
      .libraryMissing()
      .then((r) => live && setMissing(r.missing))
      .catch((e) => live && setError((e as Error).message));
    return () => {
      live = false;
    };
  }, [generation]);
  return (
    <div className="file-view library-missing" aria-label="Missing files">
      <div className="file-head">
        <h1>Labels of files that can't be found</h1>
        <div className="actions">
          <button onClick={onClose}>Close</button>
        </div>
      </div>
      <p className="small">
        These files were probably renamed, moved or deleted outside LBD. Point each to its file (it may have a new name or folder), or discard its
        labels. Data files are never changed here.
      </p>
      {error && <div className="error-box">{error}</div>}
      {missing && missing.length === 0 && <p className="muted">None: every labelled file was found.</p>}
      <ul className="missing-list">
        {(missing ?? []).map((m) => (
          <li key={`${m.folder}|${m.id ?? m.name}`}>
            <div>
              <strong>{m.name}</strong> <span className="muted small path">in {m.folder}</span>
            </div>
            <div className="small">
              {[m.star ? "★" : "", m.project ? `project ${m.project}` : "", ...m.users.map((u) => `user ${u}`), ...m.tags.map((t) => `tag ${t}`), m.comment ? `“${m.comment}”` : ""]
                .filter(Boolean)
                .join(" · ")}
            </div>
            <div className="row-controls">
              <button onClick={() => onPoint(m)}>Point to a file…</button>
              <button className="danger" onClick={() => onDiscard(m)}>
                Discard
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

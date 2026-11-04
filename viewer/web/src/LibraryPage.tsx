import type React from "react";
import { CSSProperties, Dispatch, FormEvent, KeyboardEvent, MouseEvent, ReactNode, RefObject, SetStateAction, useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  AppState,
  baseName,
  FileInfo,
  formatBytes,
  LabelChanges,
  LabelKind,
  LabelNode,
  LibraryColumn,
  LibraryFacets,
  LibraryFolder,
  LibraryQuery,
  LibraryRow,
  LibrarySettings,
  MissingLabels,
  Preview,
  PreviewMode,
  SameId,
} from "./api";
import { docsUrl } from "./help";
import { FileDetails, FileFacts } from "./FileView";
import { ConfirmDialog, ConfirmRequest, ContextMenu, isMenuKey, MenuAt, menuAt, useOutsideClose } from "./menu";
import { copyPath } from "./fileActions";
import { useToast } from "./toast";
import { useFileActions } from "./libraryActions";
import { cellText, COLUMNS, createdText, fittingColumns, localTime } from "./libraryColumns";
import { DRAWER_MEDIA, ONE_PANE_MEDIA, useMedia } from "./useMedia";
import { useResizable, widestContent } from "./resizable";
import { SidebarToggle } from "./SidebarToggle";
import { NO_FILTERS } from "./libraryQuery";
import { MeasuringStatus } from "./MeasuringStatus";
import { PAGE, useLibraryRows, useLibraryStatus } from "./libraryRows";

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
  /** this browser tab's Library filters (App keeps them: the Files sidebar shows the same list) */
  query: LibraryQuery;
  onQuery: Dispatch<SetStateAction<LibraryQuery>>;
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
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const NOTICE =
  "LBD opens each data file's header (not its data) to list dates, sweep sizes and values, and to search inside files. " +
  "In a cloud folder whose files are kept only online, that downloads every file.";
export const NOTICE_MORE =
  "This happens with Synology Drive on-demand sync, OneDrive Files On-Demand, Dropbox online-only and the like. " +
  "Switch it off in ⚙ Settings → Library to list such folders by name only.";

// Whether this browser tab shows the Library's filters in a wide window.
const FILTERS_KEY = "lbd-library-filters-shown";
const HELP_COPIES = docsUrl("viewer/library.html", "copies-and-the-same-measurement");
const CONFLICT_TIP = "Looks like a copy of another file, but the two differ — click for details";


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
  const { state, query, onQuery, selected, onSelect, onRootsChanged, onLibrarySettings, onOpenIn, onOpenInNewBrowserTab, onRenamed, onDeleted, onOpenSettings } = props;
  const toast = useToast();
  const settings: LibrarySettings = state.library;
  // the filters on the left: a column of their own in a wide window (it can be hidden, per
  // browser tab), else a drawer over the list; in a narrow window, one pane at a time
  const drawerMode = useMedia(DRAWER_MEDIA);
  const onePane = useMedia(ONE_PANE_MEDIA);
  const [filtersDocked, setFiltersDocked] = useState(() => {
    try {
      return sessionStorage.getItem(FILTERS_KEY) !== "no";
    } catch {
      return true;
    }
  });
  const [filtersOpen, setFiltersOpen] = useState(false); // the drawer
  useEffect(() => setFiltersOpen(false), [drawerMode]);
  const filtersShown = drawerMode ? filtersOpen : filtersDocked;
  // the widths of the filters and of the selected file: dragged at their edges, remembered
  const pageRef = useRef<HTMLDivElement>(null);
  const filtersPane = useRef<HTMLElement>(null);
  const filtersWidth = useResizable({
    key: "lbd-library-filters-width",
    initial: 250,
    min: 180,
    maxShare: 0.4,
    container: pageRef,
    fit: () => widestContent(filtersPane.current, ".library-folder .folder-name", 56),
  });
  const detailWidth = useResizable({
    key: "lbd-library-detail-width",
    initial: () => Math.round(window.innerWidth * 0.38),
    min: 300,
    maxShare: 0.7,
    side: "right",
    container: pageRef,
  });
  const toggleFilters = () => {
    if (drawerMode) setFiltersOpen((o) => !o);
    else
      setFiltersDocked((d) => {
        try {
          sessionStorage.setItem(FILTERS_KEY, d ? "no" : "yes");
        } catch {
          /* storage unavailable: not remembered */
        }
        return !d;
      });
  };
  // one pane at a time: the selected file shows over the list until ← Back (or Esc)
  const [detailOpen, setDetailOpen] = useState(false);
  useEffect(() => {
    if (!filtersOpen && !(onePane && detailOpen)) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (filtersOpen) setFiltersOpen(false);
      else setDetailOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [filtersOpen, onePane, detailOpen]);
  const chosenColumns = COLUMNS.filter((c) => settings.columns.includes(c.id));

  // ---- what is listed
  // the filters belong to this browser tab (App): the Files sidebar lists the same files
  const { folder, q, date, sort, order, project, tags, users, starred, conflicts } = query;
  const patch = (p: Partial<LibraryQuery>) => onQuery((old) => ({ ...old, ...p }));
  const setFolder = (v: string | null) => patch({ folder: v });
  const setQ = (v: string) => patch({ q: v });
  const setDate = (v: string) => patch({ date: v });
  const setProject = (v: string) => patch({ project: v });
  const setTags = (v: string[]) => patch({ tags: v });
  const setUsers = (v: string[]) => patch({ users: v });
  const setStarred = (v: boolean) => patch({ starred: v });
  const setConflicts = (v: boolean) => patch({ conflicts: v });
  /** every filter off (the sort stays) */
  const clearAll = () => {
    setTyped("");
    onQuery((old) => ({ ...NO_FILTERS, sort: old.sort, order: old.order }));
  };
  const [typed, setTyped] = useState(q); // the search box; `q` follows it a moment after typing stops
  useEffect(() => {
    const id = window.setTimeout(() => typed.trim() !== q && setQ(typed.trim()), 200);
    return () => window.clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typed]);
  useEffect(() => {
    // the search changed elsewhere (a chip's ×, another page's filters): show it in the box
    setTyped((t) => (t.trim() === q ? t : q));
  }, [q]);
  const queryKey = JSON.stringify(query);

  // ---- the index: changes (generation), progress
  const { status, generation, refresh } = useLibraryStatus(true);

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
  const scroller = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ top: 0, height: 600, width: 800 });
  const measure = (el: HTMLElement) => setView({ top: el.scrollTop, height: el.clientHeight, width: el.clientWidth });
  // rows, or pictures in a grid: how many items per line, and a line's height
  const pictures = settings.list_view === "pictures";
  const perLine = pictures ? Math.max(1, Math.floor(view.width / CARD_W)) : 1;
  const lineH = pictures ? CARD_H : ROW_H;
  const head = pictures ? 0 : ROW_H; // the column titles above the rows
  const columns = fittingColumns(chosenColumns, view.width);
  const hiddenColumns = chosenColumns.filter((c) => !columns.includes(c)).map((c) => c.title);

  // a new query: from the top
  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = 0;
    setView((v) => ({ ...v, top: 0 }));
  }, [queryKey]);

  const firstPage = Math.max(0, Math.floor((Math.floor(view.top / lineH) * perLine) / PAGE));
  const lastPage = Math.floor(((Math.floor((view.top + view.height) / lineH) + 1) * perLine) / PAGE) + 1;
  const { total, rowAt, indexOf, loadedRows, listError, pages } = useLibraryRows(query, generation, firstPage, lastPage);
  const selectedRow = (() => {
    const i = indexOf(selected);
    return i >= 0 ? rowAt(i) ?? null : null;
  })();

  // ---- several selected files (Ctrl / Shift / Ctrl+A); `selected` is the one last clicked
  const [chosen, setChosen] = useState<string[]>([]);
  useEffect(() => {
    setChosen((c) => (selected && c.includes(selected) ? c : selected ? [selected] : []));
  }, [selected]);
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
      setDetailOpen(true); // one pane at a time: the file over the list
    }
  };

  // ---- labels and identities: what the right column, the menu and the keys change
  const [pointing, setPointing] = useState<MissingLabels | null>(null); // missing labels waiting for a file
  const [showMissing, setShowMissing] = useState(false);
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

  const { run, label, toggleStar, askTrash, askNewMeasurement, menuEntries } = useFileActions({
    platform: state.platform,
    login: state.login,
    refresh,
    setConfirm,
    onOpenIn,
    onOpenInNewBrowserTab,
    onRenamed,
    onDeleted,
  });

  const rowMenu = (e: MouseEvent | KeyboardEvent, r: LibraryRow) => {
    e.preventDefault();
    const many = chosen.includes(r.path) && chosen.length > 1;
    if (!many) {
      setChosen([r.path]);
      onSelect(r.path);
    }
    setMenu(menuAt(e, menuEntries(many ? chosenRows() : [r], r)));
  };

  // ---- managing labels (the left column): new, rename, move, remove; drag and drop
  const KIND_WORD: Record<LabelKind, string> = { project: "project", users: "user", tags: "tag" };
  const kindNodes = (kind: LabelKind) => (kind === "project" ? facets?.projects : kind === "users" ? facets?.users : facets?.tags) ?? [];
  const groups = (kind: LabelKind, except?: string) =>
    flatten(kindNodes(kind))
      .map(({ node }) => node.label)
      .filter((l) => !except || (l !== except && !l.startsWith(except + "/")));
  const filesWord = (n: number) => (n === 1 ? "1 file" : `${n} files`);
  const checkName = (v: string) => (!v.trim() ? "Type a name" : /(^\/|\/$|\/\/)/.test(v.trim()) ? "A name can't start or end with /" : null);
  const manage: LabelManagement = {
    create: (kind, parent) => {
      const roots = state.roots;
      setConfirm({
        title: `New ${KIND_WORD[kind]}`,
        text: `It is kept even before a file has it; give it to files later (their labels, or drag files onto it). Nest with /, e.g. "Qubit A/Device 3".`,
        action: "Make it",
        choices: [
          { label: "Put under", value: parent ?? "", options: [{ value: "", label: "(the top level)" }, ...groups(kind).map((g) => ({ value: g, label: g }))] },
          ...(roots.length > 1 ? [{ label: "Kept in", value: roots[0], options: roots.map((r) => ({ value: r, label: baseName(r) })) }] : []),
        ],
        input: { value: "", check: checkName },
        onConfirm: (v, [under, root]) => run(api.libraryLabelCreate(kind, under ? `${under}/${v.trim()}` : v.trim(), root), `Made the ${KIND_WORD[kind]} "${under ? `${under}/` : ""}${v.trim()}"`),
      });
    },
    menu: (e, kind, node) => {
      e.preventDefault();
      const word = KIND_WORD[kind];
      const parent = node.label.includes("/") ? node.label.slice(0, node.label.lastIndexOf("/")) : "";
      const withCount = async (count: () => Promise<{ files: number }>, ask: (n: number) => void) => {
        try {
          ask((await count()).files);
        } catch (err) {
          toast((err as Error).message, "error");
        }
      };
      setMenu(
        menuAt(e, [
          { label: `New ${word} under it…`, onClick: () => manage.create(kind, node.label) },
          {
            label: "Rename…",
            onClick: () =>
              withCount(() => api.libraryLabelRename(kind, node.label, node.label, true), (n) =>
                setConfirm({
                  title: `Rename the ${word} "${node.label}"`,
                  text: `It is renamed on ${filesWord(n)}${node.children.length ? ", with the labels inside it" : ""}.`,
                  action: "Rename",
                  input: { value: lastPart(node.label), check: (v) => checkName(v) ?? (v.includes("/") ? "Use Move into… to put it into another group" : null) },
                  onConfirm: (v) => run(api.libraryLabelRename(kind, node.label, parent ? `${parent}/${v.trim()}` : v.trim()).then((r) => ({ notes: r.notes }))),
                }),
              ),
          },
          {
            label: "Move into…",
            onClick: () =>
              withCount(() => api.libraryLabelRename(kind, node.label, node.label, true), (n) =>
                setConfirm({
                  title: `Move the ${word} "${node.label}"`,
                  text: `It moves on ${filesWord(n)}${node.children.length ? ", with the labels inside it" : ""}.`,
                  action: "Move",
                  choices: [{ label: "Into", value: parent, options: [{ value: "", label: "(the top level)" }, ...groups(kind, node.label).map((g) => ({ value: g, label: g }))] }],
                  onConfirm: (_v, [into]) => {
                    const to = into ? `${into}/${node.name}` : node.name;
                    if (to !== node.label) return run(api.libraryLabelRename(kind, node.label, to).then((r) => ({ notes: r.notes })));
                  },
                }),
              ),
          },
          "-",
          {
            label: "Remove from all files…",
            danger: true,
            onClick: () =>
              withCount(() => api.libraryLabelRemove(kind, node.label, true), (n) =>
                setConfirm({
                  title: `Remove the ${word} "${node.label}"?`,
                  text: `It is taken off ${filesWord(n)}${node.children.length ? ", with the labels inside it" : ""}, and no longer kept. The data files aren't touched.`,
                  action: "Remove",
                  danger: true,
                  onConfirm: () => run(api.libraryLabelRemove(kind, node.label).then((r) => ({ notes: r.notes }))),
                }),
              ),
          },
        ]),
      );
    },
    dropLabel: (kind, from, to) => {
      const target = to ? `${to}/${lastPart(from)}` : lastPart(from);
      if (target === from || (to && (to === from || to.startsWith(from + "/")))) return;
      api
        .libraryLabelRename(kind, from, target, true)
        .then((r) =>
          setConfirm({
            title: `Move the ${KIND_WORD[kind]} "${from}"?`,
            text: `${to ? `Into "${to}"` : "To the top level"}: it becomes "${target}" on ${filesWord(r.files)}.`,
            action: "Move",
            onConfirm: () => run(api.libraryLabelRename(kind, from, target).then((x) => ({ notes: x.notes }))),
          }),
        )
        .catch((err) => toast((err as Error).message, "error"));
    },
    dropFiles: (kind, target, paths) =>
      setConfirm({
        title: kind === "project" ? `Set the project of ${filesWord(paths.length)}?` : `Give the ${KIND_WORD[kind]} "${target}" to ${filesWord(paths.length)}?`,
        text: kind === "project" ? `Their project becomes "${target}"; a project they have now is replaced.` : undefined,
        action: kind === "project" ? "Set the project" : `Give the ${KIND_WORD[kind]}`,
        onConfirm: () => label(paths, kind === "project" ? { project: target } : kind === "tags" ? { add_tags: [target] } : { add_users: [target] }),
      }),
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
        [{ label: "Columns shown", onClick: () => undefined, disabled: true }, "-" as const, ...COLUMNS.map((c) => {
          const on = settings.columns.includes(c.id);
          return {
            label: `${on ? "✓" : "\u2003"} ${c.id === "star" ? "★ Star" : c.title}`,
            disabled: on && settings.columns.length === 1, // at least one column
            onClick: () => setColumns(on ? settings.columns.filter((x) => x !== c.id) : COLUMNS.map((x) => x.id).filter((x) => x === c.id || settings.columns.includes(x))),
          };
        })],
      ),
    );
  };

  const sortBy = (c: LibraryColumn) => {
    if (c === sort) patch({ order: order === "asc" ? "desc" : "asc" });
    else patch({ sort: c, order: c === "date" || c === "size" || c === "modified" || c === "sweep" ? "desc" : "asc" });
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
  // the filters chosen on the left (not the search: it is in view), on the Filters button
  const filterCount = (folder ? 1 : 0) + (date ? 1 : 0) + (project ? 1 : 0) + tags.length + users.length + (starred ? 1 : 0) + (conflicts ? 1 : 0);
  const gridColumns = columns.map((c) => c.width).join(" ");

  return (
    <div
      ref={pageRef}
      style={{ "--filters-width": `${filtersWidth.width}px`, "--detail-width": `${detailWidth.width}px` } as CSSProperties}
      className={
        "page library" +
        (drawerMode ? " drawer-mode" : filtersDocked ? "" : " no-filters") +
        (onePane ? " one-pane" + (detailOpen && (selected || chosen.length > 1 || showMissing) ? " detail-open" : "") : "")
      }
    >
      {drawerMode && filtersOpen && <div className="drawer-backdrop" onClick={() => setFiltersOpen(false)} aria-hidden="true" />}
      {!drawerMode && filtersDocked && (
        <div className="pane-handle filters-handle" aria-label="Width of the sidebar" title="Drag to change the width · Double-click: fit the longest name" {...filtersWidth.handle} />
      )}
      {!onePane && (
        <div className="pane-handle detail-handle" aria-label="Width of the selected file" title="Drag to change the width" {...detailWidth.handle} />
      )}
      <aside className="library-left" ref={filtersPane} aria-label="Filters: folders, dates and labels" hidden={!filtersShown}>
        <LibraryFolders
          hideButton={<SidebarToggle open onToggle={toggleFilters} what="folders, dates, labels" />}
          roots={state.roots}
          facets={facets}
          folder={folder}
          onFolder={(f) => {
            patch({ folder: f, date: "" });
            setFiltersOpen(false);
          }}
          onRootsChanged={onRootsChanged}
        />
        <DateTree
          dates={facets?.dates ?? {}}
          date={date}
          onDate={(d) => {
            setDate(d);
            setFiltersOpen(false);
          }}
        />
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
          manage={manage}
        />
      </aside>

      <section className="library-middle" aria-label="Files">
        {settings.read_headers && !settings.notice_seen && (
          <div className="library-notice" role="note">
            <div className="notice-text">
              {NOTICE}
              <details className="notice-more">
                <summary>More…</summary>
                {NOTICE_MORE}
              </details>
            </div>
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
        <div className="library-search-row">
          {!filtersShown && <SidebarToggle open={false} onToggle={toggleFilters} what="folders, dates, labels" count={filterCount} />}
          <input
            className="library-search"
            type="search"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={settings.read_headers ? "Search names, descriptions, values, units, metadata…" : "Search file names…"}
            aria-label="Search the files"
          />
        </div>
        <div className="library-status small" role="status">
          <span>
            {total === null ? "…" : filtered && all !== undefined ? `${total} of ${all} files` : `${total} file${total === 1 ? "" : "s"}`}
          </span>
          {folder && (
            <span className="chip">
              Folder: {shownFolder?.name ?? baseName(folder)}
              <button className="link" aria-label="Show all folders" onClick={() => setFolder(null)}>
                ×
              </button>
            </span>
          )}
          {date && (
            <span className="chip">
              Date: {dateLabel(date)}
              <button className="link" aria-label="Any date" onClick={() => setDate("")}>
                ×
              </button>
            </span>
          )}
          {q && (
            <span className="chip">
              Search: "{q}"
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
          {(filtered || folder) && (
            <button className="link small" onClick={clearAll}>
              Clear all
            </button>
          )}
          {chosen.length > 1 && <span className="muted">{chosen.length} selected</span>}
          {!settings.read_headers && <span className="muted">names only: reading files' details is off in ⚙</span>}
          {status?.indexing && (
            <span className="muted">
              Indexing {status.done.toLocaleString()} of {status.total.toLocaleString()}…
            </span>
          )}
          {status?.previews && status.previews.mode === "all" && status.previews.drawing > 0 && status.previews.total > 0 && (
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
          <div className="library-head" role="row" style={{ gridTemplateColumns: gridColumns }} onContextMenu={columnMenu} title={"Click: sort; right-click: choose the columns" + (hiddenColumns.length ? `\nNot shown, the list is too narrow: ${hiddenColumns.join(", ")}` : "")}>
            {columns.map((c) => (
              <div key={c.id} role="columnheader" aria-sort={sort === c.id ? (order === "asc" ? "ascending" : "descending") : "none"}>
                <button className="link" onClick={() => sortBy(c.id)}>
                  {c.title}
                  {sort === c.id ? (order === "asc" ? " ▴" : " ▾") : ""}
                </button>
              </div>
            ))}
            {hiddenColumns.length > 0 && (
              <button
                className="hidden-columns small"
                onClick={columnMenu}
                title={`Not shown, the list is too narrow: ${hiddenColumns.join(", ")}. Make the window wider, or choose fewer columns.`}
              >
                +{hiddenColumns.length}
              </button>
            )}
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
                  draggable
                  onDragStart={(e) => {
                    // onto a label on the left: the selected files (this one when it isn't selected)
                    const paths = chosen.includes(r.path) ? chosen : [r.path];
                    e.dataTransfer.setData(DRAG_FILES, JSON.stringify(paths));
                    e.dataTransfer.effectAllowed = "copy";
                  }}
                >
                  {columns.map((c) => (
                    <div
                      key={c.id}
                      role="gridcell"
                      className={`cell-${c.id}` + (c.id === "date" && r.date_from_file ? " muted" : "")}
                      title={c.id === "date" && r.date_from_file ? "The file's own date (the file has no date of its own)" : undefined}
                    >
                      {c.id === "name" && r.error ? (
                        <span className="mark-conflict" aria-label="can't be read">
                          ⚠{" "}
                        </span>
                      ) : null}
                      {c.id === "name" && r.conflict ? (
                        <span className="mark-conflict" title={CONFLICT_TIP} aria-label="differs from its copy">
                          ⚠{" "}
                        </span>
                      ) : null}
                      {c.id === "name" && r.star ? <span className="mark-star" aria-label="starred">★ </span> : null}
                      {cellText(r, c.id)}
                      {c.id === "name" && r.writing ? <WritingMark writing={r.writing} /> : null}
                      {c.id === "name" && r.copies > 0 && !r.conflict ? (
                        <span className="mark-copies muted small" title="The same measurement is also elsewhere (labels are shared)">
                          {" "}
                          {r.copies + 1} copies
                        </span>
                      ) : null}
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
                ? "No folders yet: add one under Filters (+ Add folder)."
                : filtered
                  ? (
                      <>
                        No file matches{q ? <> "{q}"</> : null}.{" "}
                        {q && (
                          <button
                            className="link"
                            onClick={() => {
                              setTyped("");
                              setQ("");
                            }}
                          >
                            Clear the search
                          </button>
                        )}{" "}
                        <button className="link" onClick={clearAll}>
                          Clear all filters
                        </button>
                      </>
                    )
                  : status?.indexing || !status?.scans
                    ? "Looking for data files…"
                    : "No data files (.lbd) in this folder."}
            </div>
          )}
        </div>
      </section>

      <section className="library-detail" aria-label="The selected file">
        {onePane && (
          <button className="link back" onClick={() => setDetailOpen(false)}>
            ← Back to the list
          </button>
        )}
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
          <SelectedFile
            path={selected}
            row={selectedRow}
            generation={generation}
            onOpenIn={onOpenIn}
            preview={!pictures}
            star={selectedRow && !selectedRow.error ? { on: selectedRow.star, toggle: () => label([selectedRow.path], { star: !selectedRow.star }) } : undefined}
            labels={
              selectedRow && !selectedRow.error ? (
                <LabelsEditor compact rows={[selectedRow]} facets={facets} login={state.login} onChange={(c) => label([selectedRow.path], c)} />
              ) : undefined
            }
            status={
              selectedRow?.writing && (
                <WritingBox
                  row={selectedRow}
                  onRecovered={(path) => {
                    setChosen([path]);
                    onSelect(path);
                  }}
                />
              )
            }
          >
            {selectedRow && !selectedRow.error && (
              <>
                {(selectedRow.copies > 0 || !!selectedRow.conflict) && (
                  <SameIdBox
                    row={selectedRow}
                    generation={generation}
                    onShow={(path) => {
                      patch({ folder: null, conflicts: false });
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
  hideButton,
  roots,
  facets,
  folder,
  onFolder,
  onRootsChanged,
}: {
  /** the button that hides the sidebar (in its first heading) */
  hideButton: ReactNode;
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
          {hideButton}
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
        <p className="muted small pad">No dates here.</p>
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

const WRITING_TIP = {
  measuring: "Being written by a measurement on this computer right now: it grows as data comes in.",
  elsewhere: "Being written by a measurement on another computer, synced here: it grows as the sync brings data.",
  silent: "Measured on another computer, but no sign of it came for a while: it probably stopped, or the sync is paused.",
  stopped: "Its measurement stopped before finishing (a crash, an error, or a script that ended without closing it). " +
    "Recover makes it an .lbd file with everything it holds.",
};
const WRITING_TEXT = {
  measuring: "measuring…",
  elsewhere: "measuring elsewhere…",
  silent: "no sign lately",
  stopped: "stopped before finishing",
};

/** "measuring…", "measuring elsewhere…", "no sign lately" or "stopped before finishing", next to a
 *  file being written (name.lbd.writing). */
function WritingMark({ writing }: { writing: Exclude<LibraryRow["writing"], null> }) {
  return (
    <span className={`mark-writing ${writing} small`} title={WRITING_TIP[writing]}>
      {" "}
      {WRITING_TEXT[writing]}
    </span>
  );
}

/** What a file being written is: its status line (MeasuringStatus: progress, Recover). */
function WritingBox({ row, onRecovered }: { row: LibraryRow; onRecovered: (path: string) => void }) {
  return (
    <div className={`writing-box ${row.writing}`}>
      <MeasuringStatus path={row.path} onRecovered={(p, copy) => !copy && onRecovered(p)} />
      <p className="small muted">
        {row.writing === "stopped" ? (
          <>
            Its measurement ended without finishing it. <strong>Recover…</strong> makes it{" "}
            <code>{baseName(row.path).replace(/\.writing$/i, "")}</code> with everything it holds.
          </>
        ) : (
          <>
            This file is being written by a measurement and becomes{" "}
            <code>{baseName(row.path).replace(/\.writing$/i, "")}</code> when it finishes. LBD doesn't change, rename or recycle it
            meanwhile.
          </>
        )}
      </p>
    </div>
  );
}

function SelectedFile({
  path,
  row,
  generation,
  onOpenIn,
  preview = true,
  star,
  labels,
  status,
  children,
}: {
  path: string;
  row: LibraryRow | null;
  generation: number;
  onOpenIn: (path: string, where: "explore" | "figure") => void;
  /** show its preview (not in the picture view: the list shows the pictures) */
  preview?: boolean;
  /** its star, as a button in front of the title */
  star?: { on: boolean; toggle: () => void };
  /** its labels, beside the preview (under the description, date and size) */
  labels?: ReactNode;
  /** what is happening to the file (a measurement writing it): shown above its preview */
  status?: ReactNode;
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
  const date = row ? createdText(row, true) : shown?.created ?? "";
  return (
    <div className="file-view library-file">
      <div className="library-file-head">
        {star && (
          <button className={"star-icon" + (star.on ? " on" : "")} aria-pressed={star.on} aria-label={star.on ? "Starred (click: unstar)" : "Star"} title="Star (Space in the list)" onClick={star.toggle}>
            {star.on ? "★" : "☆"}
          </button>
        )}
        <h1>{shown?.title || row?.title || baseName(path)}</h1>
        <div className="actions">
          <button className="primary" onClick={() => onOpenIn(path, "explore")}>
            Open in Explore
          </button>
          <button onClick={() => onOpenIn(path, "figure")}>Open in Figure</button>
        </div>
        <div className="file-sub small">
          {date && (
            <span className="file-date" title={row?.date_from_file ? `The file's own date: the file has no date of its own${row.read ? "" : " read yet"}` : undefined}>
              {date}
              {row?.date_from_file ? <span className="muted"> (file date)</span> : null}
            </span>
          )}
          <PathLine path={path} />
        </div>
      </div>
      {(error || row?.error) && (
        <div className="error-box">
          <strong>This file can't be read.</strong> {plainReadError(error ?? row?.error ?? "")}
          <details className="small">
            <summary>Details</summary>
            <code className="path">{error ?? row?.error}</code>
          </details>
        </div>
      )}
      {status}
      <div className="file-top">
        {preview && !row?.error && <PreviewBox path={path} version={`${version}-${generation}`} />}
        <div className="file-facts">
          {shown && <FileFacts info={shown} />}
          {labels}
        </div>
      </div>
      {children}
      {!shown && !error && <p className="muted">Reading…</p>}
      {shown && <FileDetails info={shown} metaFilter layout="library" />}
    </div>
  );
}

/** What a read error means, in plain words (the technical message stays under Details). */
function plainReadError(e: string): string {
  if (/truncated|eof|end of file|unable to (synchronously )?open file/i.test(e)) return "It is damaged or incomplete (it ends early, e.g. a copy that didn't finish).";
  if (/not inside one of your folders/i.test(e)) return "It is no longer inside one of your folders.";
  if (/no such file|not found|doesn't exist/i.test(e)) return "It isn't there any more.";
  if (/permission|access is denied/i.test(e)) return "This computer's user may not read it.";
  return "It isn't an .lbd file this version of LBD can read.";
}

/** A path on one line: the folder is cut in the middle when it is too long ("C:\Data\…"),
 * the file's name stays whole; the full path in the tooltip and a copy button. */
function PathLine({ path }: { path: string }) {
  const toast = useToast();
  const cut = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\")) + 1;
  return (
    <div className="path-line small muted" title={path}>
      <span className="path-folder">{path.slice(0, cut)}</span>
      <span className="path-name">{path.slice(cut)}</span>
      <button className="icon subtle" aria-label="Copy the path" title="Copy the path" onClick={() => copyPath(path, toast)}>
        ⧉
      </button>
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
  else if (!preview.picture)
    // a reason that already says so ("No preview while …") is shown as it is
    inside = <span className="muted">{/^no preview\b/i.test(preview.reason ?? "") ? preview.reason : `No preview: ${preview.reason}`}</span>;
  // nothing to show (being written, can't be drawn, previews off): one line, not an empty box
  if (!url && (error || (preview && !preview.picture && preview.state !== "drawing")))
    return (
      <div className="preview preview-none small" aria-label="Preview">
        {inside}
      </div>
    );
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
          <span className="muted small" title={row.error ?? (preview && !preview.picture ? preview.reason ?? undefined : undefined)}>
            {row.error ? "Can't be read" : !preview || (!preview.picture && preview.state === "drawing") ? "Drawing…" : !preview.picture && preview.state === "off" ? "Previews are off" : "No preview"}
          </span>
        )}
      </div>
      <div className="card-name" role="gridcell">
        {row.conflict ? <span className="mark-conflict" aria-label="differs from its copy">⚠ </span> : null}
        {row.star ? <span className="mark-star" aria-label="starred">★ </span> : null}
        {name}
        {row.writing ? <WritingMark writing={row.writing} /> : null}
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

/** What can be done to the labels in the left column: made, renamed, moved, removed; dropped. */
export interface LabelManagement {
  /** + New (under `parent`, or at the top level) */
  create: (kind: LabelKind, parent?: string) => void;
  /** right-click (or the menu key) on a label */
  menu: (e: MouseEvent | KeyboardEvent, kind: LabelKind, node: LabelNode) => void;
  /** a label dropped on another (into it) or on its heading (`to` null: to the top level) */
  dropLabel: (kind: LabelKind, from: string, to: string | null) => void;
  /** files dragged from the list onto a label: given it */
  dropFiles: (kind: LabelKind, label: string, paths: string[]) => void;
}

const DRAG_LABEL = "application/x-lbd-label";
export const DRAG_FILES = "application/x-lbd-files";

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
  manage: LabelManagement;
}) {
  const { facets, project, tags, users, starred, conflicts, manage } = props;
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
      <LabelTree kind="project" title="Project" empty="No projects yet" nodes={facets?.projects ?? []} chosen={project ? [project] : []} onPick={(l) => props.onProject(project === l ? "" : l)} manage={manage} />
      <LabelTree kind="users" title="Users" empty="No users yet" nodes={facets?.users ?? []} chosen={users} onPick={many(users, props.onUsers)} manage={manage} />
      <LabelTree kind="tags" title="Tags" empty="No tags yet" nodes={facets?.tags ?? []} chosen={tags} onPick={many(tags, props.onTags)} manage={manage} />
    </div>
  );
}

/** A label's own name: its last part ("Device 3" of "Qubit A/Device 3"). */
function lastPart(label: string): string {
  return label.slice(label.lastIndexOf("/") + 1);
}

function LabelTree({
  kind,
  title,
  empty,
  nodes,
  chosen,
  onPick,
  manage,
}: {
  kind: LabelKind;
  title: string;
  empty: string;
  nodes: LabelNode[];
  chosen: string[];
  onPick: (label: string) => void;
  manage: LabelManagement;
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [over, setOver] = useState<string | null>(null); // where a drag would drop ("" : the heading)
  const toggle = (k: string) =>
    setOpen((o) => {
      const n = new Set(o);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  const dragged = (e: React.DragEvent): { label?: { kind: LabelKind; label: string }; files?: string[] } => {
    try {
      const l = e.dataTransfer.getData(DRAG_LABEL);
      if (l) return { label: JSON.parse(l) };
      const f = e.dataTransfer.getData(DRAG_FILES);
      if (f) return { files: JSON.parse(f) };
    } catch {
      /* something else was dropped */
    }
    return {};
  };
  const accepts = (e: React.DragEvent) => e.dataTransfer.types.includes(DRAG_LABEL) || e.dataTransfer.types.includes(DRAG_FILES);
  const dropTarget = (target: string | null) => ({
    onDragOver: (e: React.DragEvent) => {
      if (!accepts(e)) return;
      e.preventDefault();
      setOver(target ?? "");
    },
    onDragLeave: () => setOver(null),
    onDrop: (e: React.DragEvent) => {
      setOver(null);
      const d = dragged(e);
      e.preventDefault();
      if (d.label && d.label.kind === kind && d.label.label !== target) manage.dropLabel(kind, d.label.label, target);
      else if (d.files?.length && target) manage.dropFiles(kind, target, d.files);
    },
  });
  const node = (n: LabelNode, depth: number): ReactNode => (
    <li key={n.label} role="treeitem" aria-selected={chosen.includes(n.label)} aria-expanded={n.children.length ? open.has(n.label) : undefined}>
      <div
        className={"library-folder" + (chosen.includes(n.label) ? " active" : "") + (over === n.label ? " drop-here" : "")}
        style={{ paddingLeft: 8 + depth * 14 }}
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData(DRAG_LABEL, JSON.stringify({ kind, label: n.label }));
          e.dataTransfer.effectAllowed = "move";
        }}
        onContextMenu={(e) => manage.menu(e, kind, n)}
        onKeyDown={(e) => isMenuKey(e) && manage.menu(e, kind, n)}
        title={`${n.label} · right-click: new, rename, move, remove · drag onto another label to move it into it`}
        {...dropTarget(n.label)}
      >
        {n.children.length ? (
          <button className="link twisty" aria-label={(open.has(n.label) ? "Fold " : "Unfold ") + n.label} onClick={() => toggle(n.label)}>
            {open.has(n.label) ? "▾" : "▸"}
          </button>
        ) : (
          <span className="twisty" />
        )}
        <button className="link folder-name" onClick={() => onPick(n.label)}>
          {n.name}
        </button>
        <span className="count">{n.count}</span>
      </div>
      {n.children.length > 0 && open.has(n.label) && <ul role="group">{n.children.map((c) => node(c, depth + 1))}</ul>}
    </li>
  );
  return (
    <div className="library-label-tree">
      <div className={"label-tree-head" + (over === "" ? " drop-here" : "")} {...dropTarget(null)} title="Drop a label here to move it to the top level">
        <h3 className="small">{title}</h3>
        <button className="link small" onClick={() => manage.create(kind)} aria-label={`New ${title.toLowerCase()}`} title={`A new ${kind === "users" ? "user" : kind === "tags" ? "tag" : "project"}, kept even before a file has it`}>
          + New
        </button>
      </div>
      {nodes.length ? (
        <ul className="library-tree" role="tree" aria-label={title}>
          {nodes.map((n) => node(n, 0))}
        </ul>
      ) : (
        <p className="muted small pad label-empty">
          {empty}. <strong>+ New</strong>, or set one on a file.
        </p>
      )}
    </div>
  );
}

// ---- right: the labels of one or several files

/** Every label of a tree, with its depth: the picker's list. */
function flatten(nodes: LabelNode[], depth = 0): { node: LabelNode; depth: number }[] {
  return nodes.flatMap((n) => [{ node: n, depth }, ...flatten(n.children, depth + 1)]);
}

/** The labels of one or several files. `compact` (the selected file, beside its preview): one row
 * per kind without a box, the star being in front of the title, the comment one line until it is
 * clicked. */
function LabelsEditor({ rows, facets, login, onChange, compact = false }: { rows: LibraryRow[]; facets: LibraryFacets | null; login: string; onChange: (c: LabelChanges) => Promise<void> | void; compact?: boolean }) {
  const n = rows.length;
  const [picking, setPicking] = useState<"project" | "users" | "tags" | null>(null);
  const opener = useRef<HTMLElement | null>(null); // the Set / + Add button of the open picker
  const togglePicker = (which: "project" | "users" | "tags", e: React.MouseEvent<HTMLElement>) => {
    opener.current = e.currentTarget;
    setPicking(picking === which ? null : which);
  };
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
      <button className="link" onClick={(e) => togglePicker(key, e)} aria-expanded={picking === key} aria-label={key === "users" ? "Add a user" : "Add a tag"}>
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
          opener={opener}
        />
      )}
    </div>
  );
  return (
    <div className={compact ? "library-labels-rows" : "library-labels-editor"} aria-label="Labels">
      {!compact && <h3>Labels{n > 1 ? ` of ${n} files` : ""}</h3>}
      {!compact && (
        <div className="label-row">
          <button className={"star-button" + (allStarred ? " on" : "")} aria-pressed={allStarred} onClick={() => onChange({ star: !allStarred })} title="Star (Space in the list)">
            {allStarred ? "★ Starred" : "☆ Star"}
          </button>
        </div>
      )}
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
          <button className="link" onClick={(e) => togglePicker("project", e)} aria-expanded={picking === "project"} aria-label="Set the project">
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
              opener={opener}
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
          placeholder={comments.length > 1 ? "(different comments; typing here replaces them all)" : compact ? "Add a comment…" : "Notes about this data (saved when you leave the box)"}
          title="Saved when you leave the box (Ctrl+Enter)"
          onChange={(e) => setComment(e.target.value)}
          onBlur={saveComment}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) (e.target as HTMLTextAreaElement).blur();
          }}
          rows={compact ? 1 : 3}
        />
      </div>
    </div>
  );
}

function LabelPicker({ nodes, first, placeholder, onPick, onClose, opener }: { nodes: LabelNode[]; first?: string; placeholder: string; onPick: (label: string) => void; onClose: () => void; opener?: RefObject<HTMLElement | null> }) {
  const ref = useRef<HTMLDivElement>(null);
  const onKeyDown = useOutsideClose(ref, onClose, opener);
  const [text, setText] = useState("");
  const [under, setUnder] = useState(""); // a new label goes under this group ("" : the top level)
  const t = text.trim().toLowerCase();
  const newLabel = () => (under ? `${under}/${text.trim()}` : text.trim());
  const items = flatten(nodes).filter(({ node }) => !t || node.label.toLowerCase().includes(t));
  const suggested = first && (!t || first.toLowerCase().includes(t)) && !items.some(({ node }) => node.label === first) ? first : null;
  return (
    <div ref={ref} className="label-picker" role="dialog" aria-label="Pick a label" onKeyDown={onKeyDown}>
      <input
        autoFocus
        value={text}
        placeholder={placeholder}
        aria-label="Label"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.preventDefault(); // no keypress: it would click the button the focus goes back to
          if (e.key === "Enter" && text.trim()) onPick(items.some(({ node }) => node.label === text.trim()) ? text.trim() : newLabel());
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
          <li className="picker-new">
            <button className="link" onClick={() => onPick(newLabel())}>
              New: {newLabel()}
            </button>
            {nodes.length > 0 && (
              <label className="small muted">
                {" "}put under{" "}
                <select value={under} onChange={(e) => setUnder(e.target.value)} aria-label="Put the new label under">
                  <option value="">(the top level)</option>
                  {flatten(nodes).map(({ node }) => (
                    <option key={node.label} value={node.label}>
                      {node.label}
                    </option>
                  ))}
                </select>
              </label>
            )}
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

import { createContext, KeyboardEvent, MouseEvent, useCallback, useContext, useEffect, useState } from "react";
import { api, baseName, DirListing, FileKind, fileKind, joinPath, SearchResult } from "./api";
import { ConfirmDialog, ConfirmRequest, ContextMenu, isMenuKey, MenuAt, menuAt, MenuEntry, systemNames } from "./menu";
import { useToast } from "./toast";
import { useDiskVersion } from "./watch";
import { fileEntries, renameRequest } from "./fileActions";

interface Props {
  roots: string[];
  activePath: string | null;
  platform: string;
  /** go to where folders are added and removed (the Library) */
  onManageFolders: () => void;
  onSelect: (path: string) => void;
  onOpen: (path: string) => void;
  /** Open the file in a new browser tab (menu, Ctrl/⌘+click, middle-click). */
  onOpenInNewBrowserTab: (path: string) => void;
  onRenamed: (oldPath: string, newPath: string) => void;
  onDeleted: (path: string) => void;
  /** Open a data file in a chosen workspace (its right-click menu). */
  onOpenIn?: (path: string, where: "explore" | "figure") => void;
  /** the kinds of file listed (default: all; Explore lists data files only) */
  kinds?: FileKind[];
}

/** The kinds of file the tree lists (Props.kinds), for the folders deep inside it. */
const KindsContext = createContext<FileKind[] | null>(null);

/** What a row is, for its right-click menu: only files can be renamed or moved to the trash. */
type RowKind = "root" | "dir" | "file";
type OnMenu = (e: MouseEvent | KeyboardEvent, path: string, kind: RowKind) => void;

const EXPANDED_KEY = "lbd-expanded";

function loadExpanded(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(EXPANDED_KEY) ?? "[]"));
  } catch {
    return new Set();
  }
}

function saveExpanded(s: Set<string>) {
  try {
    localStorage.setItem(EXPANDED_KEY, JSON.stringify([...s]));
  } catch {
    /* storage unavailable: expansion just isn't remembered */
  }
}

export default function FolderPanel(props: Props) {
  const { roots, activePath, platform, onManageFolders, onSelect, onOpen, onOpenInNewBrowserTab, onRenamed, onDeleted, onOpenIn, kinds } = props;
  const shown = (k: FileKind) => !kinds || kinds.includes(k);
  const toast = useToast();
  const names = systemNames(platform);
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const s = loadExpanded();
    roots.forEach((r) => s.add(r));
    return s;
  });
  const [refreshKey, setRefreshKey] = useState(0);
  // a folder added since (in the Library) starts unfolded, as the ones there were at first
  const [known, setKnown] = useState(roots);
  useEffect(() => {
    const added = roots.filter((r) => !known.includes(r));
    if (added.length) setExpanded((prev) => new Set([...prev, ...added]));
    setKnown(roots);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roots]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [menu, setMenu] = useState<MenuAt | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const closeMenu = useCallback(() => setMenu(null), []);

  const toggle = useCallback((path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      saveExpanded(next);
      return next;
    });
  }, []);

  const collapseAll = () => {
    const none = new Set<string>();
    saveExpanded(none);
    setExpanded(none);
  };

  const refresh = () => setRefreshKey((k) => k + 1);

  // ---- right-click menu

  const askRename = (path: string) =>
    setConfirm(
      renameRequest(
        path,
        (newPath) => {
          onRenamed(path, newPath);
          refresh();
        },
        toast,
      ),
    );

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
        refresh();
        toast(`Moved ${name} to the ${names.trash}`);
      },
    });
  };

  const openMenu: OnMenu = (e, path, kind) => {
    e.preventDefault();
    e.stopPropagation();
    const items: MenuEntry[] = fileEntries(path, platform, toast);
    if (kind === "root") items.push("-", { label: "Manage folders in Library", onClick: onManageFolders });
    if (kind === "file" && onOpenIn && fileKind(path) === "lbd")
      items.unshift(
        { label: "Open in Explore", onClick: () => onOpenIn(path, "explore") },
        { label: "Open in Figure", onClick: () => onOpenIn(path, "figure") },
        "-",
      );
    if (kind === "file")
      items.push(
        { label: "Open in new browser tab", onClick: () => onOpenInNewBrowserTab(path) },
        "-",
        { label: "Rename…", onClick: () => askRename(path) },
        { label: `Move to ${names.trash}…`, onClick: () => askTrash(path), danger: true },
      );
    setMenu(menuAt(e, items));
  };

  // Filter box: search all roots recursively (debounced).
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setResults(null);
      return;
    }
    let cancelled = false;
    const id = window.setTimeout(async () => {
      const problems: string[] = [];
      const all = await Promise.all(
        roots.map((r) =>
          api.search(r, q).catch((e) => {
            problems.push(`Couldn't search ${r}: ${(e as Error).message}`);
            return null;
          }),
        ),
      );
      if (cancelled) return;
      const found = all.filter((x): x is SearchResult => x !== null);
      for (const res of found) {
        if (res.errors.length)
          problems.push(`${res.errors.length} item(s) in ${res.root} couldn't be read, so the results may be incomplete (first: ${res.errors[0].path}: ${res.errors[0].error}).`);
      }
      problems.forEach((p) => toast(p, "error"));
      setResults(found);
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(id);
    };
  }, [query, roots, refreshKey]);

  /** ⋯: what is done to the whole tree */
  const treeMenu = (e: MouseEvent) =>
    setMenu(
      menuAt(e, [
        { label: "Fold all folders", onClick: collapseAll, disabled: roots.length === 0 },
        { label: "Read the folders again", onClick: refresh },
        "-",
        { label: "Manage folders in Library", onClick: onManageFolders },
      ]),
    );

  return (
    <div className="folders">
      {roots.length > 0 ? (
        <div className="filter-row">
          <input className="filter" type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter files in all folders…" aria-label="Filter files" />
          <button className="icon subtle" title="Fold all, read again, manage folders" aria-label="Folder tree menu" onClick={treeMenu}>
            ⋯
          </button>
        </div>
      ) : (
        <p className="muted small pad">
          No folders yet.{" "}
          <button className="link" onClick={onManageFolders}>
            Add one in the Library
          </button>
        </p>
      )}

      <KindsContext.Provider value={kinds ?? null}>
      <div className="tree" role="tree">
        {results
          ? results.map((r) => (
              <div key={r.root} className="search-group">
                <div className="search-root" title={r.root}>
                  {baseName(r.root)}
                </div>
                {r.results.filter((f) => shown(f.type)).length === 0 && <div className="muted small pad">No matches</div>}
                {r.results.filter((f) => shown(f.type)).map((f) => (
                  <FileRow key={f.path} path={f.path} label={f.rel} kind={f.type} active={f.path === activePath} onSelect={onSelect} onOpen={onOpen} onOpenNew={onOpenInNewBrowserTab} onMenu={openMenu} depth={0} />
                ))}
                {r.truncated && <div className="muted small pad">More matches not shown; refine the filter.</div>}
              </div>
            ))
          : roots.map((root) => (
              <div key={root} className="root">
                <div className="root-row" onContextMenu={(e) => openMenu(e, root, "root")} onKeyDown={(e) => isMenuKey(e) && openMenu(e, root, "root")}>
                  <button className="twisty" onClick={() => toggle(root)} aria-expanded={expanded.has(root)} aria-label={expanded.has(root) ? "Collapse" : "Expand"}>
                    {expanded.has(root) ? "▾" : "▸"}
                  </button>
                  <span className="root-name row-label" title={root} onClick={() => toggle(root)}>
                    {baseName(root)}
                  </span>
                </div>
                {expanded.has(root) && (
                  <DirNode path={root} depth={1} expanded={expanded} toggle={toggle} refreshKey={refreshKey} activePath={activePath} onSelect={onSelect} onOpen={onOpen} onOpenNew={onOpenInNewBrowserTab} onMenu={openMenu} />
                )}
              </div>
            ))}
      </div>
      </KindsContext.Provider>
      {menu && <ContextMenu menu={menu} onClose={closeMenu} />}
      {confirm && <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />}
    </div>
  );
}

interface DirProps {
  path: string;
  depth: number;
  expanded: Set<string>;
  toggle: (p: string) => void;
  refreshKey: number;
  activePath: string | null;
  onSelect: (p: string) => void;
  onOpen: (p: string) => void;
  onOpenNew: (p: string) => void;
  onMenu: OnMenu;
}

function DirNode({ path, depth, expanded, toggle, refreshKey, activePath, onSelect, onOpen, onOpenNew, onMenu }: DirProps) {
  const [listing, setListing] = useState<DirListing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const kinds = useContext(KindsContext);
  // Files that another program adds, removes or rewrites show up by themselves: the folder is
  // listed again when its signature on disk differs from the listing shown.
  const disk = useDiskVersion("dir", path);
  const stale = !!listing && typeof disk.version === "string" && disk.version !== listing.signature;
  const [reloads, setReloads] = useState(0);
  useEffect(() => {
    if (stale) setReloads((n) => n + 1);
  }, [stale, disk.version]);

  useEffect(() => {
    let cancelled = false;
    api
      .list(path)
      .then((l) => !cancelled && (setListing(l), setError(null)))
      .catch((e) => !cancelled && setError((e as Error).message));
    return () => {
      cancelled = true;
    };
  }, [path, refreshKey, reloads]);

  if (error) return <div className="muted small" style={{ paddingLeft: depth * 14 + 8 }}>{error}</div>;
  if (!listing) return <div className="muted small" style={{ paddingLeft: depth * 14 + 8 }}>Loading…</div>;
  const files = kinds ? listing.files.filter((f) => kinds.includes(f.type)) : listing.files;
  if (!listing.dirs.length && !files.length && !listing.errors.length)
    return <div className="muted small" style={{ paddingLeft: depth * 14 + 8 }}>{kinds?.length === 1 && kinds[0] === "lbd" ? "No data files here" : "No data, style or image files here"}</div>;

  return (
    <>
      {listing.dirs.map((name) => {
        const p = joinPath(path, name);
        const open = expanded.has(p);
        return (
          <div key={p}>
            <div
              className="dir-row"
              style={{ paddingLeft: depth * 14 }}
              title={p}
              onClick={() => toggle(p)}
              onContextMenu={(e) => onMenu(e, p, "dir")}
              onKeyDown={(e) => {
                if (isMenuKey(e)) onMenu(e, p, "dir");
                else if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  toggle(p);
                }
              }}
              role="treeitem"
              tabIndex={0}
              aria-expanded={open}
            >
              <span className="twisty">{open ? "▾" : "▸"}</span>
              <span className="dir-name row-label">{name}</span>
            </div>
            {open && <DirNode path={p} depth={depth + 1} expanded={expanded} toggle={toggle} refreshKey={refreshKey} activePath={activePath} onSelect={onSelect} onOpen={onOpen} onOpenNew={onOpenNew} onMenu={onMenu} />}
          </div>
        );
      })}
      {files.map((f) => {
        const p = joinPath(path, f.name);
        return <FileRow key={p} path={p} label={f.name} kind={f.type} active={p === activePath} onSelect={onSelect} onOpen={onOpen} onOpenNew={onOpenNew} onMenu={onMenu} depth={depth} />;
      })}
      {listing.errors.map((e) => (
        <div key={`err-${e.name}`} className="file-row unreadable" style={{ paddingLeft: depth * 14 + 16 }} title={`${e.name}: ${e.error}`}>
          <span className="file-icon" aria-hidden>
            ⚠
          </span>
          <span className="row-label">
            {e.name} <span className="muted small">({e.error})</span>
          </span>
        </div>
      ))}
    </>
  );
}

const KIND_ICON: Record<FileKind, string> = { lbd: "◧", style: "✎", image: "▣" };
const KIND_HINT: Record<FileKind, string> = {
  lbd: "Click: details · Double-click: plot · Ctrl+click: new browser tab",
  style: "Style file · Click: preview",
  image: "Image · Click: view",
};

function FileRow(props: {
  path: string;
  label: string;
  kind?: FileKind;
  active: boolean;
  depth: number;
  onSelect: (p: string) => void;
  onOpen: (p: string) => void;
  onOpenNew: (p: string) => void;
  onMenu: OnMenu;
}) {
  const { path, label, active, depth, onSelect, onOpen, onOpenNew, onMenu } = props;
  const kind = props.kind ?? fileKind(path);
  return (
    <div
      className={"file-row" + (active ? " active" : "") + ` kind-${kind}`}
      style={{ paddingLeft: depth * 14 + 16 }}
      role="treeitem"
      tabIndex={0}
      title={`${path}
${KIND_HINT[kind]} · Right-click: more`}
      onClick={(e) => (e.ctrlKey || e.metaKey ? onOpenNew(path) : onSelect(path))}
      onAuxClick={(e) => e.button === 1 && (e.preventDefault(), onOpenNew(path))}
      onMouseDown={(e) => e.button === 1 && e.preventDefault() /* no autoscroll on middle-click */}
      onDoubleClick={() => onOpen(path)}
      onContextMenu={(e) => onMenu(e, path, "file")}
      onKeyDown={(e) => {
        if (isMenuKey(e)) onMenu(e, path, "file");
        else if (e.key === "Enter") onOpen(path);
        else if (e.key === " ") {
          e.preventDefault();
          onSelect(path);
        }
      }}
    >
      <span className="file-icon" aria-hidden>
        {KIND_ICON[kind]}
      </span>
      <span className="row-label">{label}</span>
    </div>
  );
}

import { FormEvent, KeyboardEvent, MouseEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError, baseName, DirListing, FileKind, fileKind, joinPath, SearchResult } from "./api";
import { ConfirmDialog, ConfirmRequest, ContextMenu, isMenuKey, MenuAt, menuAt, MenuEntry, systemNames } from "./menu";
import { useToast } from "./toast";
import { useDiskVersion } from "./watch";
import { fileEntries, renameRequest } from "./fileActions";

interface Props {
  roots: string[];
  activePath: string | null;
  platform: string;
  onRootsChanged: (roots: string[]) => void;
  onSelect: (path: string) => void;
  onOpen: (path: string) => void;
  /** Open the file in a new browser tab (menu, Ctrl/⌘+click, middle-click). */
  onOpenInNewBrowserTab: (path: string) => void;
  onRenamed: (oldPath: string, newPath: string) => void;
  onDeleted: (path: string) => void;
}

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
  const { roots, activePath, platform, onRootsChanged, onSelect, onOpen, onOpenInNewBrowserTab, onRenamed, onDeleted } = props;
  const toast = useToast();
  const names = systemNames(platform);
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const s = loadExpanded();
    roots.forEach((r) => s.add(r));
    return s;
  });
  const [refreshKey, setRefreshKey] = useState(0);
  const [adding, setAdding] = useState(roots.length === 0);
  const [typedPath, setTypedPath] = useState("");
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

  const addRoot = async (path: string) => {
    try {
      const r = await api.addRoot(path);
      onRootsChanged(r.roots);
      setExpanded((prev) => new Set(prev).add(r.roots[r.roots.length - 1]));
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
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

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
    if (kind === "root") items.push("-", { label: "Remove from list", onClick: () => removeRoot(path) });
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

  const submitTyped = (e: FormEvent) => {
    e.preventDefault();
    if (typedPath.trim()) addRoot(typedPath.trim().replace(/^"(.*)"$/, "$1"));
  };

  return (
    <div className="folders">
      <div className="panel-head">
        <h2>Folders</h2>
        <div className="actions">
          <button className="icon" title="Collapse all folders" aria-label="Collapse all folders" onClick={collapseAll} disabled={roots.length === 0}>
            ⊟
          </button>
          <button className="icon" title="Refresh" aria-label="Refresh" onClick={refresh}>
            ⟳
          </button>
          <button onClick={() => setAdding((a) => !a)} aria-expanded={adding}>
            + Add folder
          </button>
        </div>
      </div>

      {adding && (
        <form className="add-folder" onSubmit={submitTyped}>
          <button type="button" onClick={browse}>
            Browse…
          </button>
          <span className="muted">or paste a path</span>
          <div className="row">
            <input
              value={typedPath}
              onChange={(e) => setTypedPath(e.target.value)}
              placeholder="C:\Data\measurements  or  /home/me/data"
              aria-label="Folder path"
            />
            <button type="submit" className="primary" disabled={!typedPath.trim()}>
              Add
            </button>
          </div>
        </form>
      )}

      {roots.length > 0 && (
        <input className="filter" type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter files in all folders…" aria-label="Filter files" />
      )}

      <div className="tree" role="tree">
        {results
          ? results.map((r) => (
              <div key={r.root} className="search-group">
                <div className="search-root" title={r.root}>
                  {baseName(r.root)}
                </div>
                {r.results.length === 0 && <div className="muted small pad">No matches</div>}
                {r.results.map((f) => (
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
                  <button className="icon subtle" title="Remove from the list (files are not deleted)" aria-label={`Remove ${baseName(root)} from the list`} onClick={() => removeRoot(root)}>
                    ×
                  </button>
                </div>
                {expanded.has(root) && (
                  <DirNode path={root} depth={1} expanded={expanded} toggle={toggle} refreshKey={refreshKey} activePath={activePath} onSelect={onSelect} onOpen={onOpen} onOpenNew={onOpenInNewBrowserTab} onMenu={openMenu} />
                )}
              </div>
            ))}
      </div>
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
  if (!listing.dirs.length && !listing.files.length && !listing.errors.length)
    return <div className="muted small" style={{ paddingLeft: depth * 14 + 8 }}>No data, style or image files here</div>;

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
      {listing.files.map((f) => {
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

import { CSSProperties, KeyboardEvent, MouseEvent, PointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, AppState, baseName, fileKind, OpenFilesIn, PageCommand, TabState, viewerUrl } from "./api";
import FolderPanel from "./FolderPanel";
import FileView from "./FileView";
import ImageView from "./ImageView";
import StyleFileView from "./StyleFileView";
import StylesPage from "./StylesPage";
import SdkPage from "./SdkPage";
import { ToastProvider, useToast } from "./toast";
import { ConfirmDialog, ConfirmRequest, ContextMenu, isMenuKey, MenuAt, menuAt, MenuEntry } from "./menu";
import { attention, PageInfo, usePage } from "./pages";
import { docsUrl } from "./help";

type Page = "data" | "styles" | "sdk";

// Width of the Folders panel: dragged by the user, remembered in this browser.
const SIDEBAR_KEY = "lbd-sidebar-width";
const SIDEBAR_DEFAULT = 300;
const SIDEBAR_MIN = 180;
// Whether this browser tab shows the Folders panel (per tab: hide it in one of two windows).
const FOLDERS_SHOWN_KEY = "lbd-folders-shown";

function clampSidebar(w: number): number {
  return Math.round(Math.max(SIDEBAR_MIN, Math.min(w, window.innerWidth * 0.6)));
}

function loadSidebarWidth(): number {
  try {
    const w = Number(localStorage.getItem(SIDEBAR_KEY));
    return w > 0 ? clampSidebar(w) : SIDEBAR_DEFAULT;
  } catch {
    return SIDEBAR_DEFAULT;
  }
}

function saveSidebarWidth(w: number) {
  try {
    localStorage.setItem(SIDEBAR_KEY, String(w));
  } catch {
    /* storage unavailable: the width just isn't remembered */
  }
}

function loadFoldersShown(): boolean {
  try {
    return sessionStorage.getItem(FOLDERS_SHOWN_KEY) !== "no";
  } catch {
    return true;
  }
}

interface Tab {
  path: string;
  pinned: boolean; // false = preview tab, replaced by the next single-click
}

/** Why a tab can't be used right now: being moved to another page, or open there. */
interface Lock {
  reason: string;
  transfer?: string; // set while the tab is being moved to another page
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** A promise with its resolve function: "wait until this page is registered". */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

export default function App() {
  return (
    <ToastProvider>
      <Shell />
    </ToastProvider>
  );
}

function Shell() {
  const toast = useToast();
  const [state, setState] = useState<AppState | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [page, setPage] = useState<Page>("data");
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [styleRevision, setStyleRevision] = useState(0);
  const [tabMenu, setTabMenu] = useState<MenuAt | null>(null);
  const closeTabMenu = useCallback(() => setTabMenu(null), []);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [locks, setLocks] = useState<Map<string, Lock>>(new Map());
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const selectAnchor = useRef<string | null>(null);
  const [foldersShown, setFoldersShown] = useState(loadFoldersShown);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const pageRef = useRef<HTMLDivElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const [sidebarWidth, setSidebarWidth] = useState(loadSidebarWidth);
  const dragging = useRef(false);

  // The latest tabs and locks for async handlers (commands arrive at any time).
  const tabsRef = useRef(tabs);
  tabsRef.current = tabs;
  const locksRef = useRef(locks);
  locksRef.current = locks;
  // Unsaved settings of each data tab (reported by FileView), and the ones moved-in tabs start with.
  const tabStates = useRef(new Map<string, TabState>());
  const initialStates = useRef(new Map<string, TabState>());

  const shownWarnings = useRef(new Set<string>());
  const refreshState = useCallback(async () => {
    try {
      const s = await api.state();
      setState(s);
      for (const w of s.warnings) {
        if (!shownWarnings.current.has(w)) {
          shownWarnings.current.add(w);
          toast(w, "error");
        }
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        setFatal("This page has no valid session. Open the viewer again from its shortcut or by opening an .lbd file.");
      } else {
        setFatal(`Can't reach the viewer: ${(e as Error).message}. It may have been closed.`);
      }
    }
  }, [toast]);

  useEffect(() => {
    refreshState();
  }, [refreshState]);

  // Tell the server this tab is open; it shuts down a while after the last tab closes.
  useEffect(() => {
    // Three missed heartbeats in a row (30 s) mean the viewer has stopped or the session is gone.
    let failures = 0;
    const beat = () =>
      api
        .heartbeat()
        .then(() => {
          failures = 0;
        })
        .catch((e) => {
          failures += 1;
          if (failures >= 3) {
            setFatal(
              e instanceof ApiError && e.status === 403
                ? "This page has no valid session. Open the viewer again from its shortcut or by opening an .lbd file."
                : `The viewer stopped answering (${(e as Error).message}). Open it again from its shortcut.`,
            );
          }
        });
    beat();
    const id = window.setInterval(beat, 10_000);
    return () => window.clearInterval(id);
  }, []);

  // ---- tabs (rule 1: a file is open in one page only, so opening asks the viewer first) --------

  const pageInfo = useRef<PageInfo | null>(null);
  const [pageReady] = useState(() => deferred<PageInfo>());

  /** Add tabs locally (the viewer already agreed this page owns them). */
  const addTabs = useCallback((paths: string[], pinned: boolean) => {
    setPage("data");
    setTabs((prev) => {
      let next = prev;
      for (const path of paths) {
        const i = next.findIndex((t) => t.path === path);
        if (i >= 0) next = next.map((t) => (t.path === path ? { ...t, pinned: t.pinned || pinned } : t));
        else next = [...next, { path, pinned }];
      }
      return next;
    });
    if (paths.length) setActive(paths[paths.length - 1]);
  }, []);

  /** Remove tabs locally (after releasing them, or because they moved or were deleted). */
  const dropTabs = useCallback((paths: string[]) => {
    const gone = new Set(paths);
    setTabs((prev) => {
      const next = prev.filter((t) => !gone.has(t.path));
      setActive((a) => (a && gone.has(a) ? (next.length ? next[next.length - 1].path : null) : a));
      return next;
    });
    setSelected((prev) => new Set([...prev].filter((p) => !gone.has(p))));
    setLocks((prev) => new Map([...prev].filter(([p]) => !gone.has(p))));
    for (const p of paths) {
      tabStates.current.delete(p);
      initialStates.current.delete(p);
    }
  }, []);

  /** Tell the viewer this page closed these files, then remove the tabs. */
  const closeTabs = useCallback(
    async (paths: string[]) => {
      const moving = paths.filter((p) => locksRef.current.get(p)?.transfer);
      if (moving.length) toast(`${plural(moving.length, "file")} being moved to another page can't be closed right now.`, "error");
      const page = pageInfo.current;
      const closable = paths.filter((p) => !moving.includes(p));
      for (const p of closable) if (page) await api.release(page.id, p).catch(() => undefined);
      dropTabs(closable);
    },
    [dropTabs, toast],
  );

  /** "Already open in Page N": offer to show it there instead of opening a second copy. */
  const askShowElsewhere = useCallback((path: string, owner: number) => {
    setConfirm({
      title: `Already open in Page ${owner}`,
      text: `${baseName(path)} is open in Page ${owner}. A file is open in one page at a time, so its unsaved changes can't conflict.`,
      action: `Show it in Page ${owner}`,
      onConfirm: async () => {
        await api.showElsewhere(path);
      },
    });
  }, []);

  /** Open a file from this page: single-click (preview) or double-click (kept). */
  const openTab = useCallback(
    async (path: string, pinned: boolean) => {
      const existing = tabsRef.current.find((t) => t.path === path);
      if (existing) return addTabs([path], pinned);
      await pageReady.promise;
      const page = pageInfo.current!; // the latest registration (it changes after sleep)
      try {
        const r = await api.acquire(page.id, path);
        if (r.owner !== undefined) return askShowElsewhere(r.path, r.owner);
        if (!pinned) {
          // the next single-click replaces the preview tab
          const previews = tabsRef.current.filter((t) => !t.pinned && t.path !== r.path).map((t) => t.path);
          await closeTabs(previews);
        }
        addTabs([r.path], pinned);
      } catch (e) {
        toast((e as Error).message, "error");
      }
    },
    [addTabs, askShowElsewhere, closeTabs, pageReady, toast],
  );

  const selectFile = useCallback((path: string) => openTab(path, false), [openTab]);
  const openFile = useCallback((path: string) => openTab(path, true), [openTab]);
  const openInNewBrowserTab = useCallback(
    (path: string) => {
      if (tabsRef.current.some((t) => t.path === path)) {
        toast(`${baseName(path)} is open in this page. To take it to a new browser tab, right-click its tab → Move.`, "error");
        return;
      }
      if (!window.open(viewerUrl({ open: path }), "_blank")) {
        toast("The browser blocked the new tab. Allow pop-ups for the viewer.", "error");
      }
    },
    [toast],
  );

  // A file renamed: its tab, unsaved settings and lock follow the new name.
  const fileRenamed = useCallback((oldPath: string, newPath: string) => {
    setTabs((prev) => prev.map((t) => (t.path === oldPath ? { ...t, path: newPath } : t)));
    setActive((a) => (a === oldPath ? newPath : a));
    setSelected((prev) => new Set([...prev].map((p) => (p === oldPath ? newPath : p))));
    setLocks((prev) => new Map([...prev].map(([p, l]) => [p === oldPath ? newPath : p, l])));
    for (const m of [tabStates.current, initialStates.current]) {
      const s = m.get(oldPath);
      if (s) {
        m.delete(oldPath);
        m.set(newPath, s);
      }
    }
  }, []);

  // ---- moving tabs to another page (rule 4: a two-step hand-off, nothing lost or doubled) -----

  const lockTabs = useCallback((paths: string[], lock: Lock | null) => {
    setLocks((prev) => {
      const next = new Map(prev);
      for (const p of paths) {
        if (lock) next.set(p, lock);
        else next.delete(p);
      }
      return next;
    });
  }, []);

  const moveTabs = useCallback(
    async (paths: string[], to: { page: string; number: number } | null) => {
      const page = pageInfo.current;
      if (!page || !paths.length) return;
      // A new browser tab must be opened right away, in the click, or the browser blocks it.
      const win = to ? null : window.open("about:blank", "_blank");
      if (!to && !win) {
        toast("The browser blocked the new tab. Allow pop-ups for the viewer, or move the files to an open page.", "error");
        return;
      }
      const states: { [path: string]: TabState } = {};
      for (const p of paths) {
        const s = tabStates.current.get(p);
        if (s) states[p] = s;
      }
      // Lock first: the other page may take the files before the request below even returns.
      lockTabs(paths, { reason: `Moving to ${to ? `Page ${to.number}` : "a new browser tab"}…`, transfer: "starting" });
      try {
        const transfer = await api.startTransfer(page.id, paths, states, to ? to.page : null);
        if (win) win.location.href = viewerUrl({ claim: transfer.id });
      } catch (e) {
        lockTabs(paths, null);
        win?.close();
        toast((e as Error).message, "error");
      }
    },
    [lockTabs, toast],
  );

  /** Take moved files: claim them with their unsaved settings, confirm, then show them. */
  const receiveTransfer = useCallback(
    async (page: PageInfo, id: string) => {
      try {
        const claimed = await api.claimTransfer(id, page.id);
        await api.completeTransfer(id, page.id);
        for (const [p, s] of Object.entries(claimed.states)) initialStates.current.set(p, s);
        addTabs(claimed.paths, true);
        const from = claimed.from ? ` from Page ${claimed.from}` : "";
        toast(`${plural(claimed.paths.length, "file")} arrived${from}.`);
        attention(`${plural(claimed.paths.length, "file")} arrived`);
      } catch (e) {
        toast(`The files couldn't be moved here: ${(e as Error).message}`, "error");
      }
    },
    [addTabs, toast],
  );

  // ---- commands from the viewer, one at a time, in order (pages.ts) -------------------------

  const onCommand = useCallback(
    async (page: PageInfo, command: PageCommand) => {
      const data = command.data;
      switch (command.kind) {
        case "open": {
          // Double-clicked files (Explorer, Finder): confirm, then show the ones granted.
          const result = await api.pageAck(page.id, command.id).catch((e) => {
            toast((e as Error).message, "error");
            return null;
          });
          if (!result) return;
          addTabs(result.granted, true);
          for (const [p, n] of Object.entries(result.elsewhere)) toast(`${baseName(p)} is already open in Page ${n}.`);
          for (const p of result.busy) toast(`${baseName(p)} is being moved between pages; try again in a moment.`, "error");
          if (result.granted.length) attention(`${plural(result.granted.length, "file")} opened`);
          return;
        }
        case "show": {
          const path = data.path as string | null;
          if (path) addTabs([path], true);
          attention(path ? `${baseName(path)}` : "LBD Viewer");
          return;
        }
        case "transfer":
          return receiveTransfer(page, data.id as string);
        case "transfer_done": {
          // The other page took the files: close them here (no release: they belong there now).
          const moved = data.paths as string[];
          dropTabs(moved);
          toast(`Moved ${plural(moved.length, "file")} to Page ${data.to}.`);
          return;
        }
        case "transfer_cancelled": {
          // Not taken in time, or the other page closed: the files stay here, usable again.
          const kept = (data.paths as string[]).filter((p) => tabsRef.current.some((t) => t.path === p));
          lockTabs(kept, null);
          if (kept.length) toast(`The move was cancelled (${data.reason}); the files stay here.`, "error");
          return;
        }
        case "event":
          if (data.event === "renamed") fileRenamed(data.old as string, data.new as string);
          else if (data.event === "trashed" && tabsRef.current.some((t) => t.path === data.path)) {
            dropTabs([data.path as string]);
            toast(`${baseName(data.path as string)} was moved to the Recycle Bin / Trash; its tab was closed.`);
          } else if (data.event === "roots_changed") await refreshState();
          else if (data.event === "styles_changed") {
            await refreshState();
            setStyleRevision((n) => n + 1);
          }
      }
    },
    [addTabs, dropTabs, fileRenamed, lockTabs, receiveTransfer, refreshState, toast],
  );

  // Registered as a page: open what the address asks for, or (after sleep) re-check the tabs.
  const onRegistered = useCallback(
    async (page: PageInfo, again: boolean) => {
      pageInfo.current = page;
      pageReady.resolve(page);
      if (again) {
        // Dropped while asleep: another page may have opened some of these files meanwhile.
        for (const t of tabsRef.current) {
          try {
            const r = await api.acquire(page.id, t.path);
            if (r.owner !== undefined)
              lockTabs([t.path], { reason: `${baseName(t.path)} is now open in Page ${r.owner}; this copy can't be saved. Close it.` });
            else lockTabs([t.path], null);
          } catch (e) {
            lockTabs([t.path], { reason: `${(e as Error).message}. Close this tab.` });
          }
        }
        return;
      }
      const url = new URL(window.location.href);
      const open = url.searchParams.get("open");
      const claim = url.searchParams.get("claim");
      url.searchParams.delete("open");
      url.searchParams.delete("claim");
      window.history.replaceState(null, "", url.toString());
      if (claim) await receiveTransfer(page, claim);
      if (open) await openTab(open, true);
    },
    [lockTabs, openTab, pageReady, receiveTransfer],
  );

  const pageMe = usePage({ onCommand, onRegistered });

  // ---- tab bar: selection, menu ---------------------------------------------------------------

  const clickTab = (e: MouseEvent, path: string) => {
    if (e.ctrlKey || e.metaKey) {
      setSelected((prev) => {
        const next = new Set(prev.size ? prev : active ? [active] : []);
        if (next.has(path)) next.delete(path);
        else next.add(path);
        return next;
      });
      selectAnchor.current = path;
      return;
    }
    if (e.shiftKey && selectAnchor.current) {
      const order = tabs.map((t) => t.path);
      const [a, b] = [order.indexOf(selectAnchor.current), order.indexOf(path)].sort((x, y) => x - y);
      if (a >= 0) {
        setSelected(new Set(order.slice(a, b + 1)));
        return;
      }
    }
    setSelected(new Set());
    selectAnchor.current = path;
    setActive(path);
  };

  const openTabMenu = async (e: MouseEvent | KeyboardEvent, path: string) => {
    e.preventDefault();
    const at = menuAt(e, []);
    // The menu acts on the selection if this tab is part of it, else on this tab alone.
    const chosen = selected.has(path) ? tabs.map((t) => t.path).filter((p) => selected.has(p)) : [path];
    const what = chosen.length > 1 ? plural(chosen.length, "tab") : "";
    let others: { page: string; number: number; files: string[] }[] = [];
    try {
      others = (await api.pages()).pages.filter((p) => p.page !== pageInfo.current?.id);
    } catch {
      /* no list: only "new browser tab" is offered */
    }
    const items: MenuEntry[] = [
      { label: chosen.length > 1 ? `Close ${what}` : "Close", onClick: () => closeTabs(chosen) },
      { label: "Close others", onClick: () => closeTabs(tabs.map((t) => t.path).filter((p) => !chosen.includes(p))) },
      { label: "Close all", onClick: () => closeTabs(tabs.map((t) => t.path)) },
      "-",
      ...others.map((o) => ({
        label: `Move ${what ? `${what} ` : ""}to Page ${o.number}${o.files.length ? ` (${o.files.map(baseName).slice(0, 2).join(", ")}${o.files.length > 2 ? ", …" : ""})` : ""}`,
        onClick: () => moveTabs(chosen, o),
      })),
      { label: `Move ${what ? `${what} ` : ""}to a new browser tab`, onClick: () => moveTabs(chosen, null) },
    ];
    setTabMenu({ ...at, items });
  };

  const toggleFolders = () => {
    setFoldersShown((shown) => {
      try {
        sessionStorage.setItem(FOLDERS_SHOWN_KEY, shown ? "no" : "yes");
      } catch {
        /* storage unavailable: not remembered */
      }
      return !shown;
    });
  };

  const setOpenFilesIn = async (where: OpenFilesIn) => {
    try {
      setState(await api.setOpenFilesIn(where));
      toast(where === "viewer" ? "Files opened from Explorer / Finder now open in this viewer." : "Files opened from Explorer / Finder now open in new browser tabs.");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  // ---- Folders panel width: drag the handle, double-click to fit the longest name

  const setWidth = (w: number) => {
    const c = clampSidebar(w);
    setSidebarWidth(c);
    saveSidebarWidth(c);
  };

  const onHandleDown = (e: PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    dragging.current = true;
    document.body.classList.add("resizing");
  };

  const onHandleMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!dragging.current || !pageRef.current) return;
    setSidebarWidth(clampSidebar(e.clientX - pageRef.current.getBoundingClientRect().left));
  };

  const onHandleUp = () => {
    if (!dragging.current) return;
    dragging.current = false;
    document.body.classList.remove("resizing");
    saveSidebarWidth(sidebarWidth);
  };

  const fitToNames = () => {
    const side = sidebarRef.current;
    if (!side) return;
    const left = side.getBoundingClientRect().left;
    let widest = 0;
    side.querySelectorAll<HTMLElement>(".tree .row-label").forEach((el) => {
      widest = Math.max(widest, el.getBoundingClientRect().left - left + el.scrollWidth);
    });
    // room for the row's right padding, the folder's × button and a scroll bar
    if (widest) setWidth(widest + 48);
  };

  const onHandleKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowLeft") setWidth(sidebarWidth - 20);
    else if (e.key === "ArrowRight") setWidth(sidebarWidth + 20);
    else if (e.key === "Home") setWidth(SIDEBAR_DEFAULT);
    else return;
    e.preventDefault();
  };

  if (fatal) {
    return (
      <div className="fatal">
        <h1>LBD Viewer</h1>
        <p>{fatal}</p>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden>
            <svg viewBox="0 0 32 32" width="20" height="20">
              <rect width="32" height="32" rx="6" fill="var(--accent)" />
              <path d="M6 22 L12 14 L17 18 L26 8" stroke="white" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          LBD Viewer
          {pageMe && (
            <span className="page-badge" title="This browser tab's number among the viewer's open pages (for Move to)">
              Page {pageMe.number}
            </span>
          )}
        </div>
        <nav className="pages" role="tablist">
          {(
            [
              ["data", "Data"],
              ["styles", "Styles"],
              ["sdk", "Language modules"],
            ] as [Page, string][]
          ).map(([p, label]) => (
            <button key={p} role="tab" aria-selected={page === p} className={page === p ? "active" : ""} onClick={() => setPage(p)}>
              {label}
            </button>
          ))}
        </nav>
        <div className="version">{state ? `v${state.version} · format ${state.lbd_version}` : ""}</div>
        {state && (
          <div className="settings">
            <button className="icon" title="Settings" aria-label="Settings" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((o) => !o)}>
              ⚙
            </button>
            {settingsOpen && (
              <div className="settings-popover" role="dialog" aria-label="Settings" onMouseLeave={() => setSettingsOpen(false)}>
                <div className="settings-title">Files opened from Explorer / Finder</div>
                {(
                  [
                    ["viewer", "In the open viewer (as a tab)"],
                    ["browser-tab", "In a new browser tab"],
                  ] as [OpenFilesIn, string][]
                ).map(([value, label]) => (
                  <label key={value} className="settings-choice">
                    <input type="radio" name="open-files-in" checked={state.open_files_in === value} onChange={() => setOpenFilesIn(value)} />
                    {label}
                  </label>
                ))}
              </div>
            )}
          </div>
        )}
        <a className="help-button" href={docsUrl()} target="_blank" rel="noopener" title="Open the documentation (works offline)">
          Help
        </a>
      </header>

      <div
        className={"page" + (foldersShown ? "" : " no-folders")}
        hidden={page !== "data"}
        ref={pageRef}
        style={{ "--sidebar-width": `${sidebarWidth}px` } as CSSProperties}
      >
        <aside className="sidebar" ref={sidebarRef} hidden={!foldersShown}>
          {state && (
            <FolderPanel
              roots={state.roots}
              activePath={active}
              platform={state.platform}
              onRootsChanged={(roots) => setState({ ...state, roots })}
              onSelect={selectFile}
              onOpen={openFile}
              onOpenInNewBrowserTab={openInNewBrowserTab}
              onRenamed={fileRenamed}
              onDeleted={(path) => closeTabs([path])}
            />
          )}
        </aside>
        {foldersShown && (
          <div
            className="sidebar-handle"
            role="separator"
            aria-orientation="vertical"
            aria-label="Width of the folder panel"
            aria-valuenow={sidebarWidth}
            aria-valuemin={SIDEBAR_MIN}
            tabIndex={0}
            title="Drag to change the width · Double-click: fit the longest name"
            onPointerDown={onHandleDown}
            onPointerMove={onHandleMove}
            onPointerUp={onHandleUp}
            onPointerCancel={onHandleUp}
            onDoubleClick={fitToNames}
            onKeyDown={onHandleKey}
          />
        )}
        <main className="main">
          <div className="tabs" role="tablist">
            <button
              className="folders-toggle"
              aria-pressed={foldersShown}
              title={foldersShown ? "Hide the Folders panel (more room for plots)" : "Show the Folders panel"}
              onClick={toggleFolders}
            >
              ◧ Folders
            </button>
            {tabs.map((t) => {
              const lock = locks.get(t.path);
              return (
                <div
                  key={t.path}
                  className={
                    "tab" +
                    (t.path === active ? " active" : "") +
                    (t.pinned ? "" : " preview") +
                    (selected.has(t.path) ? " selected" : "") +
                    (lock ? " locked" : "")
                  }
                  title={`${t.path}${lock ? `\n${lock.reason}` : ""}\nCtrl+click: select several · Right-click: close, move to another page`}
                  onContextMenu={(e) => openTabMenu(e, t.path)}
                  onKeyDown={(e) => isMenuKey(e) && openTabMenu(e, t.path)}
                >
                  <button
                    role="tab"
                    aria-selected={t.path === active}
                    className="tab-label"
                    onClick={(e) => clickTab(e, t.path)}
                    onDoubleClick={() => openFile(t.path)}
                  >
                    {lock ? (lock.transfer ? "⇢ " : "🔒 ") : ""}
                    {baseName(t.path)}
                  </button>
                  <button className="tab-close" aria-label={`Close ${baseName(t.path)}`} onClick={() => closeTabs([t.path])}>
                    ×
                  </button>
                </div>
              );
            })}
          </div>
          {tabMenu && <ContextMenu menu={tabMenu} onClose={closeTabMenu} />}
          {confirm && <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />}
          {tabs.length === 0 && <EmptyMain hasRoots={!!state?.roots.length} />}
          {state &&
            tabs.map((t) => (
              <div key={t.path} className="tab-body" hidden={t.path !== active}>
                {fileKind(t.path) === "image" ? (
                  <ImageView path={t.path} onError={(m) => toast(m, "error")} />
                ) : fileKind(t.path) === "style" ? (
                  <StyleFileView
                    path={t.path}
                    previewPath={tabs.find((x) => fileKind(x.path) === "lbd")?.path ?? null}
                    onImported={async () => {
                      await refreshState();
                      setStyleRevision((n) => n + 1);
                    }}
                    onError={(m) => toast(m, "error")}
                  />
                ) : (
                  <FileView
                    path={t.path}
                    plotted={t.pinned}
                    onPlot={() => openFile(t.path)}
                    styles={state.styles}
                    defaultStyle={state.default_style}
                    styleRevision={styleRevision}
                    onError={(m) => toast(m, "error")}
                    initialState={initialStates.current.get(t.path)}
                    onStateChange={(s) => tabStates.current.set(t.path, s)}
                    locked={locks.get(t.path)?.reason ?? null}
                  />
                )}
              </div>
            ))}
        </main>
      </div>

      {page === "styles" && state && (
        <div className="page single">
          <StylesPage
            previewPath={
              tabs.find((t) => t.path === active && fileKind(t.path) === "lbd")?.path ??
              tabs.find((t) => fileKind(t.path) === "lbd")?.path ??
              null
            }
            onChanged={async () => {
              await refreshState();
              setStyleRevision((n) => n + 1);
            }}
          />
        </div>
      )}
      {page === "sdk" && (
        <div className="page single">
          <SdkPage />
        </div>
      )}
    </div>
  );
}

function EmptyMain({ hasRoots }: { hasRoots: boolean }) {
  return (
    <div className="empty">
      <h2>No file open</h2>
      {hasRoots ? (
        <p>Click a file in the folder panel to see what is inside it, and double-click it to plot it.</p>
      ) : (
        <p>
          Add a folder that contains <code>.lbd</code> files using <strong>Add folder</strong> on the left. You can also
          double-click an <code>.lbd</code> file on your computer to open it here.
        </p>
      )}
    </div>
  );
}

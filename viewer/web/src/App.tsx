import { CSSProperties, KeyboardEvent, MouseEvent, PointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, AppState, baseName, fileKind } from "./api";
import FolderPanel from "./FolderPanel";
import FileView from "./FileView";
import ImageView from "./ImageView";
import StyleFileView from "./StyleFileView";
import StylesPage from "./StylesPage";
import SdkPage from "./SdkPage";
import { ToastProvider, useToast } from "./toast";
import { ContextMenu, isMenuKey, MenuAt, menuAt } from "./menu";
import { docsUrl } from "./help";

type Page = "data" | "styles" | "sdk";

// Width of the Folders panel: dragged by the user, remembered in this browser.
const SIDEBAR_KEY = "lbd-sidebar-width";
const SIDEBAR_DEFAULT = 300;
const SIDEBAR_MIN = 180;

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

interface Tab {
  path: string;
  pinned: boolean; // false = preview tab, replaced by the next single-click
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
  const pageRef = useRef<HTMLDivElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const [sidebarWidth, setSidebarWidth] = useState(loadSidebarWidth);
  const dragging = useRef(false);

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

  // Initial state, plus a file passed on the URL (double-click / command line).
  useEffect(() => {
    refreshState();
    const url = new URL(window.location.href);
    const open = url.searchParams.get("open");
    if (open) {
      url.searchParams.delete("open");
      window.history.replaceState(null, "", url.toString());
      setTabs([{ path: open, pinned: true }]);
      setActive(open);
    }
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

  const selectFile = useCallback((path: string) => {
    setPage("data");
    setTabs((prev) => {
      if (prev.some((t) => t.path === path)) return prev;
      const kept = prev.filter((t) => t.pinned);
      return [...kept, { path, pinned: false }];
    });
    setActive(path);
  }, []);

  const openFile = useCallback((path: string) => {
    setPage("data");
    setTabs((prev) => {
      const i = prev.findIndex((t) => t.path === path);
      if (i >= 0) return prev.map((t) => (t.path === path ? { ...t, pinned: true } : t));
      return [...prev.filter((t) => t.pinned), { path, pinned: true }];
    });
    setActive(path);
  }, []);

  const closeTab = (path: string) => {
    setTabs((prev) => {
      const next = prev.filter((t) => t.path !== path);
      if (active === path) setActive(next.length ? next[next.length - 1].path : null);
      return next;
    });
  };

  const closeOthers = (path: string) => {
    setTabs((prev) => prev.filter((t) => t.path === path));
    setActive(path);
  };

  const closeAll = () => {
    setTabs([]);
    setActive(null);
  };

  const openTabMenu = (e: MouseEvent | KeyboardEvent, path: string) => {
    e.preventDefault();
    setTabMenu(
      menuAt(e, [
        { label: "Close", onClick: () => closeTab(path) },
        { label: "Close others", onClick: () => closeOthers(path) },
        { label: "Close all", onClick: closeAll },
      ]),
    );
  };

  // A file renamed in the folder panel: its tab follows the new name.
  const fileRenamed = (oldPath: string, newPath: string) => {
    setTabs((prev) => prev.map((t) => (t.path === oldPath ? { ...t, path: newPath } : t)));
    setActive((a) => (a === oldPath ? newPath : a));
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
        <a className="help-button" href={docsUrl()} target="_blank" rel="noopener" title="Open the documentation (works offline)">
          Help
        </a>
      </header>

      <div className="page" hidden={page !== "data"} ref={pageRef} style={{ "--sidebar-width": `${sidebarWidth}px` } as CSSProperties}>
        <aside className="sidebar" ref={sidebarRef}>
          {state && (
            <FolderPanel
              roots={state.roots}
              activePath={active}
              platform={state.platform}
              onRootsChanged={(roots) => setState({ ...state, roots })}
              onSelect={selectFile}
              onOpen={openFile}
              onRenamed={fileRenamed}
              onDeleted={closeTab}
            />
          )}
        </aside>
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
        <main className="main">
          {tabs.length > 0 && (
            <div className="tabs" role="tablist">
              {tabs.map((t) => (
                <div
                  key={t.path}
                  className={"tab" + (t.path === active ? " active" : "") + (t.pinned ? "" : " preview")}
                  title={`${t.path}\nRight-click: close others or all`}
                  onContextMenu={(e) => openTabMenu(e, t.path)}
                  onKeyDown={(e) => isMenuKey(e) && openTabMenu(e, t.path)}
                >
                  <button role="tab" aria-selected={t.path === active} className="tab-label" onClick={() => setActive(t.path)} onDoubleClick={() => openFile(t.path)}>
                    {baseName(t.path)}
                  </button>
                  <button className="tab-close" aria-label={`Close ${baseName(t.path)}`} onClick={() => closeTab(t.path)}>
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
          {tabMenu && <ContextMenu menu={tabMenu} onClose={closeTabMenu} />}
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

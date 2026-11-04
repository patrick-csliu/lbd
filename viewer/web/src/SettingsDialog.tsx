// Settings (⚙): a dialog with a list of sections on the left and that section's settings on the
// right. Only the right side scrolls; "Find a setting" searches every section; a dot marks a
// section with a setting not at its default, and "Reset this section…" puts it back.
// The server keeps the settings (config.py; SETTINGS_SECTIONS lists each section's settings).

import { useEffect, useMemo, useRef, useState } from "react";
import { api, AppState, OpenDataIn, OpenFilesIn, Theme } from "./api";
import { ConfirmDialog, ConfirmRequest } from "./menu";
import { MemorySettings } from "./MemorySettings";
import { MeasurementSettings } from "./MeasurementSettings";
import { SidebarScopeSettings } from "./FilesSidebar";
import { PreviewSettings } from "./LibraryPage";
import { Segmented, Setting, SettingsGroup, Switch } from "./settingsUi";
import { useToast } from "./toast";

export type SettingsSection = "general" | "library" | "sidebar" | "memory" | "measurements";

/** The sections, and for "Find a setting" every setting in them: its name and the words it is
 * found by (its help, and other words people use). */
export const SECTIONS: { id: SettingsSection; title: string; settings: { id: string; name: string; words: string }[] }[] = [
  {
    id: "general",
    title: "General",
    settings: [
      { id: "theme", name: "Theme", words: "dark light system colours colors appearance mode" },
      { id: "open_files_in", name: "Files opened from Explorer / Finder open in", words: "double-click browser tab viewer window" },
      { id: "open_data_in", name: "Data files go to", words: "explore figure double-click open" },
    ],
  },
  {
    id: "library",
    title: "Library",
    settings: [
      { id: "library.read_headers", name: "Read each file's details", words: "headers title date sweep values metadata cloud online onedrive dropbox download search" },
      { id: "library.previews", name: "Draw previews of", words: "pictures thumbnails images every file nearby" },
      { id: "library.cache", name: "Picture cache", words: "previews disk empty clear space" },
    ],
  },
  {
    id: "sidebar",
    title: "Files sidebar",
    settings: [{ id: "library.sidebar_scopes", name: "What the Files sidebar can list", words: "folders starred recent library selection explore figure" }],
  },
  {
    id: "memory",
    title: "Memory",
    settings: [
      { id: "memory.reserve_gb", name: "Leave free", words: "ram memory gb reserve limit" },
      { id: "memory.maximum_gb", name: "Use at most", words: "ram memory gb maximum limit" },
      { id: "memory.summary_cache_gb", name: "Summaries kept on disk, up to", words: "large data maps cache gb disk" },
      { id: "memory.summaries", name: "Summaries now", words: "empty clear cache disk" },
    ],
  },
  {
    id: "measurements",
    title: "Measurements",
    settings: [
      { id: "measurements.progress", name: "Show the progress", words: "status line measuring live" },
      { id: "measurements.time", name: "Time left", words: "progress estimate" },
      { id: "measurements.percent", name: "Percentage", words: "progress" },
      { id: "measurements.points", name: "Points measured", words: "progress" },
      { id: "measurements.axes", name: "Slow axes", words: "progress power" },
      { id: "measurements.notify", name: "Notify me when a measurement ends", words: "notification finished stopped background browser" },
    ],
  },
];

const LAST_KEY = "lbd-settings-section";

/** The section to open first: the one shown last in this browser tab, or General. */
export function lastSection(): SettingsSection {
  try {
    const s = sessionStorage.getItem(LAST_KEY) as SettingsSection | null;
    if (s && SECTIONS.some((x) => x.id === s)) return s;
  } catch {
    /* storage unavailable */
  }
  return "general";
}

function valueAt(state: AppState, key: string): unknown {
  return key.split(".").reduce<unknown>((o, k) => (o && typeof o === "object" ? (o as Record<string, unknown>)[k] : undefined), state);
}

/** Sections with a setting not at its default (from the viewer's `defaults`). */
function changedSections(state: AppState): Set<string> {
  const out = new Set<string>();
  for (const [section, keys] of Object.entries(state.defaults ?? {}))
    if (Object.entries(keys).some(([k, d]) => JSON.stringify(valueAt(state, k)) !== JSON.stringify(d))) out.add(section);
  return out;
}

export function SettingsDialog({
  state,
  section,
  onSection,
  onClose,
  onSettings,
  setTheme,
  setOpenFilesIn,
  setOpenDataIn,
  setReadHeaders,
}: {
  state: AppState;
  section: SettingsSection;
  onSection: (s: SettingsSection) => void;
  onClose: () => void;
  onSettings: (s: AppState) => void;
  setTheme: (t: Theme) => void;
  setOpenFilesIn: (w: OpenFilesIn) => void;
  setOpenDataIn: (w: OpenDataIn) => void;
  setReadHeaders: (on: boolean) => void;
}) {
  const toast = useToast();
  const ref = useRef<HTMLDialogElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const [find, setFind] = useState("");
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);
  useEffect(() => {
    try {
      sessionStorage.setItem(LAST_KEY, section);
    } catch {
      /* not remembered */
    }
    body.current?.scrollTo?.({ top: 0 });
  }, [section]);
  // a found setting: shown in its section and lit up for a moment
  useEffect(() => {
    if (!flash) return;
    const el = body.current?.querySelector<HTMLElement>(`[data-setting="${flash}"]`);
    el?.scrollIntoView({ block: "center" });
    el?.classList.add("found");
    const t = window.setTimeout(() => {
      el?.classList.remove("found");
      setFlash(null);
    }, 1600);
    return () => window.clearTimeout(t);
  }, [flash, section]);

  const changed = changedSections(state);
  const needle = find.trim().toLowerCase();
  const found = useMemo(
    () =>
      needle
        ? SECTIONS.flatMap((s) => s.settings.filter((x) => `${x.name} ${x.words} ${s.title}`.toLowerCase().includes(needle)).map((x) => ({ section: s, setting: x })))
        : [],
    [needle],
  );
  const title = SECTIONS.find((s) => s.id === section)!.title;

  const reset = () =>
    setConfirm({
      title: `Reset the ${title} settings?`,
      text: "They go back to how LBD starts. Your folders, presets and the Library's columns aren't changed.",
      action: "Reset",
      onConfirm: async () => {
        onSettings(await api.resetSettings(section));
        toast(`The ${title} settings are back to their defaults.`);
      },
    });

  return (
    <dialog
      ref={ref}
      className="settings-dialog"
      aria-label="Settings"
      onCancel={(e) => {
        e.preventDefault();
        if (!confirm) onClose();
      }}
      onMouseDown={(e) => {
        if (e.target === ref.current) onClose(); // a click on the backdrop
      }}
    >
      <div className="settings-dialog-head">
        <h2>Settings</h2>
        <button className="icon subtle" aria-label="Close the settings" title="Close (Esc)" onClick={onClose}>
          ×
        </button>
      </div>
      <div className="settings-dialog-body">
        <nav className="settings-nav" aria-label="Settings sections">
          <input type="search" className="settings-find" value={find} onChange={(e) => setFind(e.target.value)} placeholder="Find a setting…" aria-label="Find a setting" />
          {needle ? (
            <ul className="settings-found" aria-label="Settings found">
              {found.length === 0 && <li className="muted small">Nothing found</li>}
              {found.map(({ section: s, setting }) => (
                <li key={setting.id}>
                  <button
                    className="link"
                    onClick={() => {
                      onSection(s.id);
                      setFlash(setting.id);
                      setFind("");
                    }}
                  >
                    {setting.name} <span className="muted small">· {s.title}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="settings-sections" role="tablist" aria-orientation="vertical">
              {SECTIONS.map((s) => (
                <button key={s.id} role="tab" aria-selected={s.id === section} className={s.id === section ? "on" : ""} onClick={() => onSection(s.id)}>
                  {s.title}
                  {changed.has(s.id) && (
                    <span className="changed-dot" title="Changed from the default" aria-label="(changed)">
                      ●
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
          <button className="link small settings-reset" onClick={reset} disabled={!changed.has(section)} title={changed.has(section) ? undefined : "Every setting here is at its default"}>
            Reset this section…
          </button>
        </nav>
        <div className="settings-main" ref={body} role="tabpanel" aria-label={title}>
          <h3>{title}</h3>
          {section === "general" && (
            <>
              <Setting id="theme" name="Theme" help={`System: follows the light or dark mode of ${state.platform === "win32" ? "Windows" : state.platform === "darwin" ? "macOS" : "your system"}.`}>
                <Segmented<Theme> name="theme" label="Theme" value={state.theme} onChange={setTheme} options={[["system", "System"], ["light", "Light"], ["dark", "Dark"]]} />
              </Setting>
              <SettingsGroup title="Files opened from Explorer / Finder">
                <Setting id="open_files_in" name="Open in" help="When you double-click a .lbd file outside LBD.">
                  <Segmented<OpenFilesIn> name="open-files-in" label="Files opened from Explorer / Finder open in" value={state.open_files_in} onChange={setOpenFilesIn} options={[["viewer", "This viewer (a tab)"], ["browser-tab", "A new browser tab"]]} />
                </Setting>
                <Setting id="open_data_in" name="Data files go to" help="Explore to look at the data, Figure to make a figure.">
                  <Segmented<OpenDataIn> name="open-data-in" label="Data files opened from Explorer / Finder go to" value={state.open_data_in} onChange={setOpenDataIn} options={[["explore", "Explore"], ["figure", "Figure"]]} />
                </Setting>
              </SettingsGroup>
            </>
          )}
          {section === "library" && (
            <>
              <SettingsGroup title="Reading files">
                <Setting
                  id="library.read_headers"
                  name="Read each file's details"
                  help="Title, date, sweep size, values and metadata, to list and search them. Off: names, sizes and file dates only. Switch it off for cloud folders whose files are kept only online: reading a file there downloads all of it."
                >
                  <Switch label="Read each data file's details" checked={state.library.read_headers} onChange={setReadHeaders} />
                </Setting>
              </SettingsGroup>
              <SettingsGroup title="Previews">
                <PreviewSettings settings={state.library} onSettings={onSettings} />
              </SettingsGroup>
            </>
          )}
          {section === "sidebar" && <SidebarScopeSettings state={state} onSettings={onSettings} />}
          {section === "memory" && <MemorySettings settings={state.memory} onSettings={onSettings} />}
          {section === "measurements" && <MeasurementSettings settings={state.measurements} onSettings={onSettings} />}
        </div>
      </div>
      {confirm && <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />}
    </dialog>
  );
}

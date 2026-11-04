// The "Memory for data" settings (plan 6d, server: memory.py, config.MEMORY_DEFAULTS): how much
// memory LBD leaves free for the rest of the computer, an optional most it may use, and the size
// of the disk cache of large maps' summaries. A value that fits in the memory available loads
// whole; a bigger one is read by part.

import { useEffect, useState } from "react";
import { api, AppState, formatBytes, MemorySettings as Settings } from "./api";
import { useToast } from "./toast";
import { Setting, SettingsGroup } from "./settingsUi";

/** A number of GB typed in a box: "" means automatic / no maximum. */
function parseGb(text: string): number | null | undefined {
  const t = text.trim();
  if (t === "") return null;
  const x = Number(t);
  return Number.isFinite(x) && x >= 0 ? x : undefined;
}

export function MemorySettings({ settings, onSettings }: { settings: Settings; onSettings: (s: AppState) => void }) {
  const toast = useToast();
  const [reserve, setReserve] = useState(settings.reserve_gb === null ? "" : String(settings.reserve_gb));
  const [maximum, setMaximum] = useState(settings.maximum_gb === null ? "" : String(settings.maximum_gb));
  const [cache, setCache] = useState(String(settings.summary_cache_gb));
  useEffect(() => setReserve(settings.reserve_gb === null ? "" : String(settings.reserve_gb)), [settings.reserve_gb]);
  useEffect(() => setMaximum(settings.maximum_gb === null ? "" : String(settings.maximum_gb)), [settings.maximum_gb]);
  useEffect(() => setCache(String(settings.summary_cache_gb)), [settings.summary_cache_gb]);
  // the summaries kept now: read when the settings open (and after emptying or a new limit)
  const [kept, setKept] = useState<{ count: number; bytes: number } | null>(null);
  useEffect(() => {
    api.summaries().then(setKept, () => setKept(null));
  }, [settings.summary_cache_gb]);

  const save = async (key: keyof Settings, text: string, empty: number | null) => {
    const parsed = parseGb(text);
    if (parsed === undefined) {
      toast("Type a number of GB (or leave it empty).", "error");
      return;
    }
    const value = parsed === null ? empty : parsed;
    if (settings[key] === value) return;
    try {
      onSettings(await api.setMemory({ [key]: value }));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const empty = async () => {
    try {
      const out = await api.emptySummaries();
      setKept(out);
      if (out.kept) toast(`${out.kept} summar${out.kept === 1 ? "y is" : "ies are"} in use now and stay; close those maps, then empty again.`, "warning");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const number = (key: "reserve_gb" | "maximum_gb" | "summary_cache_gb", text: string, set: (v: string) => void, label: string, placeholder: string | undefined, empty: number | null) => (
    <span className="settings-number-unit">
      <input
        className="settings-number"
        aria-label={label}
        placeholder={placeholder}
        value={text}
        onChange={(e) => set(e.target.value)}
        onBlur={() => save(key, text, empty)}
        onKeyDown={(e) => e.key === "Enter" && save(key, text, empty)}
      />
      <span className="unit">GB</span>
    </span>
  );
  return (
    <>
      <dl className="settings-facts">
        <dt>This computer</dt>
        <dd>{settings.total_gb !== null ? `${settings.total_gb} GB` : "not known"}</dd>
        {settings.room_gb !== null && (
          <>
            <dt>Available to LBD now</dt>
            <dd>{settings.room_gb} GB</dd>
          </>
        )}
      </dl>
      <p className="settings-intro">A value that fits in the memory available is read whole; a bigger one is read by part, only what is shown.</p>
      <SettingsGroup title="Limits">
        <Setting id="memory.reserve_gb" name="Leave free" help="For the rest of the computer; empty: automatic.">
          {number("reserve_gb", reserve, setReserve, "Memory to leave free, in GB", `automatic: ${settings.reserve_now_gb ?? "2"}`, null)}
        </Setting>
        <Setting id="memory.maximum_gb" name="Use at most" help="Empty: no limit.">
          {number("maximum_gb", maximum, setMaximum, "Most memory to use, in GB", "no limit", null)}
        </Setting>
      </SettingsGroup>
      <SettingsGroup title="Summaries of large data">
        <Setting id="memory.summary_cache_gb" name="Keep on disk, up to" help="A map or curves larger than the memory are summarised once; the summary is kept so they open quickly next time, the least recently used going first.">
          {number("summary_cache_gb", cache, setCache, "Disk cache for summaries of large data, in GB", undefined, 20)}
        </Setting>
        <Setting id="memory.summaries" name="Summaries now">
          <span className="settings-value">{kept ? `${kept.count.toLocaleString()} · ${formatBytes(kept.bytes)}` : "…"}</span>
          <button onClick={empty} disabled={!kept || kept.count === 0}>
            Empty
          </button>
        </Setting>
      </SettingsGroup>
    </>
  );
}

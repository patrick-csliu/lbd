// The "Memory for data" settings (plan 6d, server: memory.py, config.MEMORY_DEFAULTS): how much
// memory LBD leaves free for the rest of the computer, an optional most it may use, and the size
// of the disk cache of large maps' summaries. A value that fits in the memory available loads
// whole; a bigger one is read by part.

import { useEffect, useState } from "react";
import { api, AppState, formatBytes, MemorySettings as Settings } from "./api";
import { useToast } from "./toast";
import { useAskFirst } from "./askFirst";
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

  const askFirst = useAskFirst();
  const put = async (key: keyof Settings, value: number | null) => {
    try {
      onSettings(await api.setMemory({ [key]: value }));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const save = (key: keyof Settings, text: string, empty: number | null) => {
    const parsed = parseGb(text);
    if (parsed === undefined) {
      toast("Type a number of GB (or leave it empty).", "error");
      return;
    }
    const value = parsed === null ? empty : parsed;
    if (settings[key] === value) return;
    // less room than the summaries kept take: the least recently used are deleted, asked first (18.7)
    const over = key === "summary_cache_gb" && value !== null && kept ? kept.bytes - value * 1e9 : 0;
    if (over > 0)
      return askFirst({
        title: "Delete summaries?",
        text: `The summaries kept take ${formatBytes(kept!.bytes)}; with room for ${value} GB, about ${formatBytes(over)} of them are deleted (the least recently used). They are made again, slowly, when those files are opened.`,
        action: "Delete them",
        danger: true,
        onConfirm: () => put(key, value),
      });
    void put(key, value);
  };

  // emptying deletes every summary not in use: asked first (18.7)
  const empty = () =>
    askFirst({
      title: "Empty the summaries?",
      text: `${kept ? `${kept.count.toLocaleString()} summar${kept.count === 1 ? "y" : "ies"} (${formatBytes(kept.bytes)}) are deleted` : "The summaries are deleted"}; large maps and curves are summarised again, slowly, when opened.`,
      action: "Empty",
      danger: true,
      onConfirm: async () => {
        try {
          const out = await api.emptySummaries();
          setKept(out);
          if (out.kept) toast(`${out.kept} summar${out.kept === 1 ? "y is" : "ies are"} in use now and stay; close those maps, then empty again.`, "warning");
        } catch (e) {
          toast((e as Error).message, "error");
        }
      },
    });
  // risky limits: said under the field, the value can still be kept (18.7)
  const gb = (t: string) => (parseGb(t) ?? null);
  const reserveNote = gb(reserve) !== null && gb(reserve)! < 1 && gb(reserve)! > 0
    ? "Less than 1 GB left free: the computer may slow down while LBD reads a large file."
    : null;
  const maximumNote = gb(maximum) !== null && settings.total_gb !== null && gb(maximum)! > settings.total_gb
    ? `More than this computer has (${settings.total_gb} GB): reading a large file may freeze it while the system moves programs to disk.`
    : gb(maximum) !== null && gb(maximum)! > 0 && gb(maximum)! < 0.5
      ? "Very little: large files are read part by part and slowly."
      : null;

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
        <Setting id="memory.reserve_gb" name="Leave free" help="For the rest of the computer. Empty: 0, the viewer uses what the computer reports as available (the system makes room by moving idle programs to disk). Data under 64 MB is always read whole.">
          {number("reserve_gb", reserve, setReserve, "Memory to leave free, in GB", "0", null)}
          {reserveNote && <span className="small export-warning settings-note" role="note">{reserveNote}</span>}
        </Setting>
        <Setting id="memory.maximum_gb" name="Use at most" help="Empty: no limit.">
          {number("maximum_gb", maximum, setMaximum, "Most memory to use, in GB", "no limit", null)}
          {maximumNote && <span className="small export-warning settings-note" role="note">{maximumNote}</span>}
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

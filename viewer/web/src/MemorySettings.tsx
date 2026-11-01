// The "Memory for data" settings (plan 6d, server: memory.py, config.MEMORY_DEFAULTS): how much
// memory LBD leaves free for the rest of the computer, an optional most it may use, and the size
// of the disk cache of large maps' summaries. A value that fits in the memory available loads
// whole; a bigger one is read by part.

import { useEffect, useState } from "react";
import { api, AppState, MemorySettings as Settings } from "./api";
import { useToast } from "./toast";

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

  const here = settings.total_gb !== null ? `${settings.total_gb} GB in this computer` : "this computer's memory isn't known";
  return (
    <>
      <div className="settings-title">Memory for data</div>
      <p className="settings-note small muted">
        A value that fits in the memory available is read whole; a bigger one is read by part, only what is shown. LBD uses what
        is free and always leaves some for the rest of the computer ({here}
        {settings.room_gb !== null ? `; ${settings.room_gb} GB available to LBD now` : ""}).
      </p>
      <label className="settings-choice">
        Leave free (GB)
        <input
          className="settings-number"
          aria-label="Memory to leave free, in GB"
          placeholder={`automatic: ${settings.reserve_now_gb ?? "2"}`}
          value={reserve}
          onChange={(e) => setReserve(e.target.value)}
          onBlur={() => save("reserve_gb", reserve, null)}
          onKeyDown={(e) => e.key === "Enter" && save("reserve_gb", reserve, null)}
        />
      </label>
      <label className="settings-choice">
        Use at most (GB)
        <input
          className="settings-number"
          aria-label="Most memory to use, in GB"
          placeholder="no limit"
          value={maximum}
          onChange={(e) => setMaximum(e.target.value)}
          onBlur={() => save("maximum_gb", maximum, null)}
          onKeyDown={(e) => e.key === "Enter" && save("maximum_gb", maximum, null)}
        />
      </label>
      <label className="settings-choice">
        Summaries of large maps on disk, up to (GB)
        <input
          className="settings-number"
          aria-label="Disk cache for summaries of large maps, in GB"
          value={cache}
          onChange={(e) => setCache(e.target.value)}
          onBlur={() => save("summary_cache_gb", cache, 20)}
          onKeyDown={(e) => e.key === "Enter" && save("summary_cache_gb", cache, 20)}
        />
      </label>
    </>
  );
}
